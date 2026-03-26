# daemon/utils.py
# -----------------------------------------------------------------------------
# Cookie + form helpers and a DB-backed auth check with tiny TTL cache
# -----------------------------------------------------------------------------
import os, json, time, threading
from urllib.parse import parse_qs
from urllib import request, error

DB_BASE = os.getenv("DB_BASE", "http://127.0.0.1:9010")
AUTH_CACHE_TTL = int(os.getenv("AUTH_CACHE_TTL", "5"))  # seconds

# sid -> (valid_bool, expires_at_epoch)
_AUTH_CACHE: dict[str, tuple[bool, float]] = {}
_AUTH_LOCK = threading.Lock()

def parse_cookies(raw: str) -> dict:
    out = {}
    if not raw:
        return out
    for part in raw.split(";"):
        part = part.strip()
        if not part:
            continue
        if "=" not in part:
            out[part] = ""
            continue
        k, v = part.split("=", 1)
        out[k.strip()] = v.strip()
    return out

def parse_form_urlencoded(body: bytes) -> dict:
    if not body:
        return {}
    s = body.decode("utf-8", errors="ignore")
    return {k: (v[0] if v else "") for k, v in parse_qs(s, keep_blank_values=True).items()}

def _db_session_get(sid: str, timeout=3) -> bool:
    """
    Ask DB service if sid is valid: POST /db/session/get {"sid": "..."} -> 200 + {"session":{...}}
    Fail-closed (return False) on errors.
    """
    payload = json.dumps({"sid": sid}).encode("utf-8")
    req = request.Request(
        DB_BASE + "/db/session/get",
        data=payload, method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with request.urlopen(req, timeout=timeout) as r:
            if r.status != 200:
                return False
            resp = json.loads(r.read().decode("utf-8"))
            return "session" in resp
    except Exception:
        return False  # fail-closed

def is_authenticated(headers: dict) -> bool:
    """
    Validate sid via DB with a tiny TTL cache.
    Source of truth = DB (cache only for a few seconds).
    """
    sid = parse_cookies(headers.get("cookie", "")).get("sid")
    if not sid:
        return False

    now = time.time()
    with _AUTH_LOCK:
        hit = _AUTH_CACHE.get(sid)
        if hit and hit[1] > now:
            return hit[0]

    valid = _db_session_get(sid)
    with _AUTH_LOCK:
        _AUTH_CACHE[sid] = (valid, now + AUTH_CACHE_TTL)
    return valid

def invalidate_sid(sid: str) -> None:
    """Optional: call this if you ever want to purge cache on logout response handling."""
    if not sid:
        return
    with _AUTH_LOCK:
        _AUTH_CACHE.pop(sid, None)
