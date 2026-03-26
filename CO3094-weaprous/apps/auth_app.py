# apps/auth_app.py
import json
from urllib import request, error
from daemon.weaprous import WeApRous
from daemon.utils import parse_form_urlencoded, parse_cookies

DB_BASE = "http://127.0.0.1:9010"

def _json(data, status=200, headers=None):
    body = json.dumps(data).encode("utf-8")
    hdrs = {"Content-Type": "application/json; charset=utf-8",
            "Content-Length": str(len(body))}
    if headers: hdrs.update(headers)
    return (status, hdrs, body)

def _db_post(path, payload, headers=None, timeout=5):
    data = json.dumps(payload).encode("utf-8")
    req  = request.Request(DB_BASE + path, data=data, method="POST",
                           headers={"Content-Type":"application/json", **(headers or {})})
    try:
        with request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8")), r.getcode()
    except error.HTTPError as e:
        body = e.read().decode("utf-8") or "{}"
        try: return json.loads(body), e.code
        except: return {"error": body or "http error"}, e.code

app = WeApRous()
app.prepare_address("127.0.0.1", 9001)

SESSION_TTL = 3600  # seconds

@app.route("/login", methods=["POST"])
def login(headers="guest", body=b""):
    form = parse_form_urlencoded(body or b"")
    if form.get("username") == "admin" and form.get("password") == "password":
        user = {"id": 1, "username": "admin", "roles": ["admin"]}
        resp, code = _db_post("/db/session/create", {"user": user, "ttlSec": SESSION_TTL})
        if code == 200 and resp.get("ok"):
            sid = resp["sid"]
            set_cookie = f"sid={sid}; Path=/; HttpOnly; SameSite=Lax"
            return _json({"ok": True, "sid": sid}, headers={"Set-Cookie": set_cookie})
        return _json({"error": "session create failed"}, status=500)
    return (401, {"Content-Type":"text/html; charset=utf-8"}, b"<h1>401 Unauthorized</h1>")

@app.route("/logout", methods=["POST"])
def logout(headers="guest", body=b""):
    cookies = parse_cookies(headers.get("cookie","") if isinstance(headers, dict) else "")
    sid = cookies.get("sid","")
    if sid:
        _db_post("/db/session/destroy", {"sid": sid})
    return _json({"ok": True}, headers={"Set-Cookie": "sid=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax"})

@app.route("/me", methods=["GET"])
def me(headers="guest", body=b""):
    cookies = parse_cookies(headers.get("cookie","") if isinstance(headers, dict) else "")
    sid = cookies.get("sid","")
    if not sid: return _json({"error":"unauthorized"}, status=401)
    resp, code = _db_post("/db/session/get", {"sid": sid})
    if code == 200 and "session" in resp:
        s = resp["session"]
        return _json({"user": {"id": s["user_id"], "username": s["username"], "roles": s.get("roles", [])}})
    return _json({"error":"unauthorized"}, status=401)
