# /db/app_state.py
# -----------------------------------------------------------------------------
# Single-process in-memory state DB exposed over HTTP for all replicas.
# Port: 127.0.0.1:9010
# -----------------------------------------------------------------------------

import os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from daemon.weaprous import WeApRous
import json, time, threading
from collections import defaultdict, deque
from daemon.weaprous import WeApRous

app = WeApRous()
app.prepare_address("127.0.0.1", 9010)

def _now_s()  -> int: return int(time.time())
def _now_ms() -> int: return int(time.time() * 1000)

def _json(data, status=200, headers=None):
    body = json.dumps(data).encode("utf-8")
    hdrs = {"Content-Type": "application/json; charset=utf-8",
            "Content-Length": str(len(body))}
    if headers: hdrs.update(headers)
    return (status, hdrs, body)

LOCK = threading.Lock()

# -------------------------- Storage & TTLs -----------------------------------
SESSION_TTL_DEFAULT = 3600                 # seconds
SESSIONS: dict[str, dict] = {}             # sid -> session

PEER_TTL_MS = 3_600_000
PEERS: dict[str, dict] = {}                # peerId -> {public_ip, private_ip, lastSeen}

CHANNELS: dict[str, dict] = {}             # name -> {"members": {peerId: {...}}, "created": ms, "lastSeen": ms}

OFFERS_TO:  dict[str, deque] = defaultdict(lambda: deque(maxlen=16))
ANSWERS_TO: dict[str, deque] = defaultdict(lambda: deque(maxlen=16))
MSG_TTL_MS = 20_000

WAIT_MAX_MS = 5_000
WAIT_SLEEP  = 0.05

# ------------------------------ GC -------------------------------------------
def _gc_sessions(now_s=None):
    now = now_s or _now_s()
    for sid in list(SESSIONS):
        if SESSIONS[sid].get("exp", 0) <= now:
            SESSIONS.pop(sid, None)

def _gc_peers(now_ms=None):
    now = now_ms or _now_ms()
    stale = [pid for pid, info in PEERS.items()
             if (now - int(info.get("lastSeen", 0))) > PEER_TTL_MS]
    for pid in stale:
        PEERS.pop(pid, None)
        for ch in CHANNELS.values():
            ch["members"].pop(pid, None)

def _gc_mailboxes(now_ms=None):
    now = now_ms or _now_ms()
    def _purge(q: deque):
        while q and (now - int(q[0].get("ts", 0))) > MSG_TTL_MS:
            q.popleft()
    for q in OFFERS_TO.values():  _purge(q)
    for q in ANSWERS_TO.values(): _purge(q)

def _gc_loop():
    while True:
        time.sleep(60)
        with LOCK:
            _gc_sessions()
            _gc_peers()
            _gc_mailboxes()

threading.Thread(target=_gc_loop, daemon=True).start()

def _ok(**kw): d={"ok":True}; d.update(kw); return _json(d)
def _bad(msg, code=400): return _json({"error": msg}, status=code)

# ------------------------------ Health ---------------------------------------
@app.route("/db/health", methods=["GET"])
def health(headers="guest", body=b""):
    with LOCK:
        return _ok(now=_now_ms(),
                   sessions=len(SESSIONS),
                   peers=len(PEERS),
                   channels=len(CHANNELS))

# ------------------------------ Sessions -------------------------------------
# POST /db/session/create {user:{id,username,roles?}, ttlSec?} -> {ok,sid}
@app.route("/db/session/create", methods=["POST"])
def session_create(headers="guest", body=b""):
    try:
        d = json.loads((body).decode("utf-8","ignore"))
    except Exception:
        return _bad("bad json")
    user = d.get("user") or {}
    ttl  = int(d.get("ttlSec") or SESSION_TTL_DEFAULT)
    if not user or "id" not in user or "username" not in user:
        return _bad("user.id and user.username required")
    import secrets
    sid = secrets.token_hex(16)
    now = _now_s()
    sess = {"id": sid, "user_id": user["id"], "username": user["username"],
            "roles": user.get("roles", []), "created_at": now,
            "last_seen": now, "exp": now + ttl}
    with LOCK:
        SESSIONS[sid] = sess
    return _ok(sid=sid)

# POST /db/session/get {sid} -> {session}|{error}
@app.route("/db/session/get", methods=["POST"])
def session_get(headers="guest", body=b""):
    try:
        d = json.loads((body).decode("utf-8","ignore"))
    except Exception:
        return _bad("bad json")
    sid = (d.get("sid") or "").strip()
    if not sid: return _bad("sid required")
    with LOCK:
        s = SESSIONS.get(sid)
        if not s: return _bad("not found", 404)
        now = _now_s()
        if s["exp"] <= now:
            SESSIONS.pop(sid, None)
            return _bad("expired", 404)
        s["last_seen"] = now
        view = {k: s[k] for k in ("id","user_id","username","roles","created_at","last_seen","exp")}
        return _json({"session": view})

# POST /db/session/destroy {sid} -> {ok}
@app.route("/db/session/destroy", methods=["POST"])
def session_destroy(headers="guest", body=b""):
    try:
        d = json.loads((body).decode("utf-8","ignore"))
    except Exception:
        return _bad("bad json")
    sid = (d.get("sid") or "").strip()
    if not sid: return _bad("sid required")
    with LOCK:
        SESSIONS.pop(sid, None)
    return _ok()

# ------------------------------- Peers ---------------------------------------
# POST /db/peer/upsert {peerId, public_ip, private_ip} -> {ok}
@app.route("/db/peer/upsert", methods=["POST"])
def peer_upsert(headers="guest", body=b""):
    try:
        d = json.loads((body).decode("utf-8","ignore"))
    except Exception:
        return _bad("bad json")
    pid = (d.get("peerId") or "").strip()
    if not pid: return _bad("peerId required")
    pub  = (d.get("public_ip")  or "").strip()
    priv = (d.get("private_ip") or "").strip()
    with LOCK:
        PEERS[pid] = {"public_ip": pub, "private_ip": priv, "lastSeen": _now_ms()}
    return _ok()

# POST /db/peer/get {peerId} -> {peer}|{error}
@app.route("/db/peer/get", methods=["POST"])
def peer_get(headers="guest", body=b""):
    try:
        d = json.loads((body).decode("utf-8","ignore"))
    except Exception:
        return _bad("bad json")
    pid = (d.get("peerId") or "").strip()
    if not pid: return _bad("peerId required")
    with LOCK:
        p = PEERS.get(pid)
        if not p: return _bad("not found", 404)
        return _json({"peer": {"peerId": pid, **p}})

# ------------------------------ Channels -------------------------------------
# POST /db/channel/join {channel, peerId} -> {ok, channel, members}
@app.route("/db/channel/join", methods=["POST"])
def channel_join(headers="guest", body=b""):
    try:
        d = json.loads((body).decode("utf-8","ignore"))
    except Exception:
        return _bad("bad json")
    name = (d.get("channel") or "").strip()
    pid  = (d.get("peerId")  or "").strip()
    if not name or not pid: return _bad("channel and peerId required")
    with LOCK:
        p = PEERS.get(pid)
        if not p: return _bad("peer not registered", 400)
        now = _now_ms()
        ch = CHANNELS.get(name) or {"members": {}, "created": now, "lastSeen": now}
        ch["members"][pid] = {"public_ip": p["public_ip"], "private_ip": p["private_ip"], "lastSeen": now}
        ch["lastSeen"] = now
        CHANNELS[name] = ch
        members = [{"peerId": k, **v} for k, v in ch["members"].items()]
    return _ok(channel=name, members=members)

# POST /db/channel/leave {channel, peerId} -> {ok}
@app.route("/db/channel/leave", methods=["POST"])
def channel_leave(headers="guest", body=b""):
    try:
        d = json.loads((body) .decode("utf-8","ignore"))
    except Exception:
        return _bad("bad json")
    name = (d.get("channel") or "").strip()
    pid  = (d.get("peerId")  or "").strip()
    if not name or not pid: return _bad("channel and peerId required")
    with LOCK:
        ch = CHANNELS.get(name)
        if ch:
            ch["members"].pop(pid, None)
            ch["lastSeen"] = _now_ms()
    return _ok()

# GET /db/channel/members  (header: x-channel: <name>) -> {channel, members}
@app.route("/db/channel/members", methods=["GET"])
def channel_members(headers="guest", body=b""):
    name = (headers.get("x-channel") or "").strip() if isinstance(headers, dict) else ""
    if not name: return _bad("channel required (x-channel header)")
    with LOCK:
        ch = CHANNELS.get(name)
        if not ch: return _json({"channel": name, "members": []})
        # remove members whose peer vanished
        for pid in list(ch["members"]):
            if pid not in PEERS:
                ch["members"].pop(pid, None)
        members = [{"peerId": k, **v} for k, v in ch["members"].items()]
    return _json({"channel": name, "members": members})

# ----------------------------- Signaling -------------------------------------
def _purge_head(q: deque, now_ms: int):
    while q and (now_ms - int(q[0].get("ts", 0))) > MSG_TTL_MS:
        q.popleft()

# POST /db/signal/offer/push {to, frm, sdp} -> {ok,id}
@app.route("/db/signal/offer/push", methods=["POST"])
def offer_push(headers="guest", body=b""):
    try:
        d = json.loads((body).decode("utf-8","ignore"))
    except Exception:
        return _bad("bad json")
    to  = (d.get("to")  or "").strip()
    frm = (d.get("frm") or "").strip()
    sdp = d.get("sdp")
    if not to or not frm or not sdp: return _bad("to, frm, sdp required")
    now = _now_ms()
    with LOCK:
        OFFERS_TO[to].append({"id": now, "from": frm, "sdp": sdp, "ts": now})
    return _ok(id=now)

# POST /db/signal/offer/pop {peerId, wait?} -> {} | {id, from, sdp, ts}
@app.route("/db/signal/offer/pop", methods=["POST"])
def offer_pop(headers="guest", body=b""):
    try:
        d = json.loads((body).decode("utf-8","ignore"))
    except Exception:
        d = {}
    me      = (d.get("peerId") or "").strip()
    do_wait = str(d.get("wait", "")).lower() in ("1","true","yes")
    if not me: return _bad("peerId required")
    deadline = _now_ms() + (WAIT_MAX_MS if do_wait else 0)
    while True:
        with LOCK:
            q = OFFERS_TO.get(me)
            if q:
                _purge_head(q, _now_ms())
                if q:
                    return _json(q.popleft())
        if not do_wait or _now_ms() >= deadline:
            return _json({})
        time.sleep(WAIT_SLEEP)

# POST /db/signal/answer/push {to, frm, sdp} -> {ok,id}
@app.route("/db/signal/answer/push", methods=["POST"])
def answer_push(headers="guest", body=b""):
    try:
        d = json.loads((body).decode("utf-8","ignore"))
    except Exception:
        return _bad("bad json")
    to  = (d.get("to")  or "").strip()
    frm = (d.get("frm") or "").strip()
    sdp = d.get("sdp")
    if not to or not frm or not sdp: return _bad("to, frm, sdp required")
    now = _now_ms()
    with LOCK:
        ANSWERS_TO[to].append({"id": now, "from": frm, "sdp": sdp, "ts": now})
    return _ok(id=now)

# POST /db/signal/answer/pop {peerId, wait?} -> {} | {id, from, sdp, ts}
@app.route("/db/signal/answer/pop", methods=["POST"])
def answer_pop(headers="guest", body=b""):
    try:
        d = json.loads((body).decode("utf-8","ignore"))
    except Exception:
        d = {}
    me      = (d.get("peerId") or "").strip()
    do_wait = str(d.get("wait", "")).lower() in ("1","true","yes")
    if not me: return _bad("peerId required")
    deadline = _now_ms() + (WAIT_MAX_MS if do_wait else 0)
    while True:
        with LOCK:
            q = ANSWERS_TO.get(me)
            if q:
                _purge_head(q, _now_ms())
                if q:
                    return _json(q.popleft())
        if not do_wait or _now_ms() >= deadline:
            return _json({})
        time.sleep(WAIT_SLEEP)

if __name__ == "__main__":
    app.run()
