# apps/p2p_app.py
import json, time
import urllib.parse as urlparse
from urllib import request, error
from daemon.weaprous import WeApRous
from daemon.utils import is_authenticated

DB_BASE = "http://127.0.0.1:9010"

def _json(data, status=200, headers=None):
    body = json.dumps(data).encode("utf-8")
    hdrs = {
        "Content-Type": "application/json; charset=utf-8",
        "Content-Length": str(len(body)),
        "Cache-Control": "no-store",
    }
    if headers:
        hdrs.update(headers)
    return (status, hdrs, body)

def _db_post(path, payload, headers=None, timeout=6):
    data = json.dumps(payload).encode("utf-8")
    req  = request.Request(
        DB_BASE + path,
        data=data,
        method="POST",
        headers={"Content-Type": "application/json", **(headers or {})},
    )
    try:
        with request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8")), r.getcode()
    except error.HTTPError as e:
        body = e.read().decode("utf-8") or "{}"
        try: return json.loads(body), e.code
        except: return {"error": body or "http error"}, e.code

def _db_get(path, headers=None, timeout=6):
    req = request.Request(DB_BASE + path, method="GET", headers=headers or {})
    try:
        with request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8")), r.getcode()
    except error.HTTPError as e:
        body = e.read().decode("utf-8") or "{}"
        try: return json.loads(body), e.code
        except: return {"error": body or "http error"}, e.code

def _params_from(headers: dict, body: bytes) -> dict:
    """
    Extract parameters for handlers. Order:
      1) JSON body (if present)
      2) adapter-injected x-query-json (if present)
      3) raw query in x-path (fallback)
    """
    # 1) body JSON
    if body:
        try:
            return json.loads(body.decode("utf-8", "ignore"))
        except Exception:
            pass

    # 2) adapter-injected header
    if isinstance(headers, dict):
        try:
            qjson = headers.get("x-query-json", "{}")
            return json.loads(qjson)
        except Exception:
            pass

        # 3) raw query
        raw_path = headers.get("x-path", "") or ""
        qs = raw_path.split("?", 1)[1] if "?" in raw_path else ""
        if qs:
            qd = urlparse.parse_qs(qs, keep_blank_values=True)
            return {k: (v[0] if len(v) == 1 else v) for k, v in qd.items()}

    return {}

app = WeApRous()
app.prepare_address("127.0.0.1", 9005)  # signaling only

# --------------------------- submit-info ---------------------------
@app.route("/submit-info", methods=["POST"])
def submit_info(headers="guest", body=b""):
    if not is_authenticated(headers): return _json({"error": "unauthorized"}, 401)
    try: data = json.loads((body or b"").decode("utf-8", "ignore"))
    except Exception: return _json({"error": "bad json"}, 400)

    peerId     = (data.get("peerId") or "").strip()
    public_ip  = (data.get("public_ip") or "").strip()
    private_ip = (data.get("private_ip") or "").strip()
    if not peerId: return _json({"error": "peerId required"}, 400)

    resp, code = _db_post("/db/peer/upsert", {"peerId": peerId, "public_ip": public_ip, "private_ip": private_ip})
    return _json(resp if code == 200 else {"error": resp.get("error", "failed")}, status=code)

# ----------------------------- add-list / leave-list -------------------------
@app.route("/add-list", methods=["POST"])
def add_list(headers="guest", body=b""):
    if not is_authenticated(headers): return _json({"error": "unauthorized"}, 401)
    try: data = json.loads((body or b"").decode("utf-8", "ignore"))
    except Exception: return _json({"error": "bad json"}, 400)
    name   = (data.get("channel") or "").strip()
    peerId = (data.get("peerId")  or "").strip()
    if not name or not peerId: return _json({"error": "channel and peerId required"}, 400)

    resp, code = _db_post("/db/channel/join", {"channel": name, "peerId": peerId})
    return _json(resp if code == 200 else {"error": resp.get("error", "failed")}, status=code)

@app.route("/leave-list", methods=["POST"])
def leave_list(headers="guest", body=b""):
    if not is_authenticated(headers): return _json({"error": "unauthorized"}, 401)
    try: data = json.loads((body or b"").decode("utf-8", "ignore"))
    except Exception: return _json({"error": "bad json"}, 400)
    name   = (data.get("channel") or "").strip()
    peerId = (data.get("peerId")  or "").strip()
    if not name or not peerId: return _json({"error": "channel and peerId required"}, 400)

    resp, code = _db_post("/db/channel/leave", {"channel": name, "peerId": peerId})
    return _json(resp if code == 200 else {"error": resp.get("error", "failed")}, status=code)

# ------------------------------ get-list (query OR header) -------------------
@app.route("/get-list", methods=["GET"])
def get_list(headers="guest", body=b""):
    if not is_authenticated(headers):
        return _json({"error":"unauthorized"}, 401)

    # prefer header (UI sends this now)
    channel = (headers.get("x-channel") or "").strip() if isinstance(headers, dict) else ""

    if not channel:
        return _json({"error":"channel required (x-channel header)"}, 400)

    # Call DB the way it expects (x-channel header)
    resp, code = _db_get("/db/channel/members", headers={"x-channel": channel})
    if code != 200:
        return _json({"error": resp.get("error", "failed")}, status=code)

    # Normalize shape to { "peers": [ {peerId, lastSeen?} ] }
    peers = []
    if isinstance(resp, dict):
        raw = None
        if isinstance(resp.get("peers"), list):
            raw = resp["peers"]
        elif isinstance(resp.get("members"), list):
            raw = resp["members"]
        elif isinstance(resp.get("list"), list):
            raw = resp["list"]
        else:
            raw = []

        for it in raw:
            if isinstance(it, str):
                peers.append({"peerId": it})
            elif isinstance(it, dict):
                pid = it.get("peerId") or it.get("id") or it.get("name") or ""
                # try to pick a timestamp-ish field
                ts = it.get("lastSeen") or it.get("last_seen") or it.get("ts") or it.get("updated_at") or 0
                # coerce numeric if possible
                try:
                    if isinstance(ts, str): ts = float(ts)
                except Exception:
                    ts = 0
                peers.append({"peerId": pid, "lastSeen": ts})
    return _json({"peers": peers}, 200)

# --------------------------- signaling (offer/answer) ------------------------
@app.route("/connect-peer", methods=["POST"])
def connect_peer(headers="guest", body=b""):
    if not is_authenticated(headers): return _json({"error": "unauthorized"}, 401)
    try: data = json.loads((body or b"").decode("utf-8", "ignore"))
    except Exception: return _json({"error": "bad json"}, 400)
    frm = (data.get("from") or "").strip()
    to  = (data.get("to")   or "").strip()
    sdp = data.get("sdp")
    if not frm or not to or not sdp: return _json({"error": "from, to, sdp required"}, 400)
    resp, code = _db_post("/db/signal/offer/push", {"to": to, "frm": frm, "sdp": sdp})
    return _json(resp if code == 200 else {"error": resp.get("error", "failed")}, status=code)

@app.route("/connect-peer/get", methods=["POST"])
def connect_peer_get(headers="guest", body=b""):
    if not is_authenticated(headers): return _json({"error": "unauthorized"}, 401)
    try: data = json.loads((body or b"").decode("utf-8", "ignore"))
    except Exception: data={}
    me      = (data.get("peerId") or "").strip()
    do_wait = str(data.get("wait","")).lower() in ("1","true","yes")
    if not me: return _json({"error": "peerId required"}, 400)
    resp, code = _db_post("/db/signal/offer/pop", {"peerId": me, "wait": do_wait})
    return _json(resp if code == 200 else {"error": resp.get("error", "failed")}, status=code)

# Graceful no-op for declines so UI doesn't 404; you can wire to DB if supported.
@app.route("/connect-peer/decline", methods=["POST"])
def connect_peer_decline(headers="guest", body=b""):
    if not is_authenticated(headers): return _json({"error": "unauthorized"}, 401)
    # Optional: try to pop & discard a pending offer (non-blocking). Ignore errors.
    try:
        data = json.loads((body or b"").decode("utf-8", "ignore"))
        me = (data.get("peerId") or "").strip()
        if me:
            _db_post("/db/signal/offer/pop", {"peerId": me, "wait": False})
    except Exception:
        pass
    return _json({"ok": True}, 200)

@app.route("/send-peer", methods=["POST"])
def send_peer(headers="guest", body=b""):
    if not is_authenticated(headers): return _json({"error": "unauthorized"}, 401)
    try: data = json.loads((body or b"").decode("utf-8", "ignore"))
    except Exception: return _json({"error": "bad json"}, 400)
    frm = (data.get("from") or "").strip()
    to  = (data.get("to")   or "").strip()
    sdp = data.get("sdp")
    if not frm or not to or not sdp: return _json({"error": "from, to, sdp required"}, 400)
    resp, code = _db_post("/db/signal/answer/push", {"to": to, "frm": frm, "sdp": sdp})
    return _json(resp if code == 200 else {"error": resp.get("error", "failed")}, status=code)

@app.route("/send-peer/get", methods=["POST"])
def send_peer_get(headers="guest", body=b""):
    if not is_authenticated(headers): return _json({"error": "unauthorized"}, 401)
    try: data = json.loads((body or b"").decode("utf-8", "ignore"))
    except Exception: data={}
    me      = (data.get("peerId") or "").strip()
    do_wait = str(data.get("wait","")).lower() in ("1","true","yes")
    if not me: return _json({"error": "peerId required"}, 400)
    resp, code = _db_post("/db/signal/answer/pop", {"peerId": me, "wait": do_wait})
    return _json(resp if code == 200 else {"error": resp.get("error", "failed")}, status=code)
