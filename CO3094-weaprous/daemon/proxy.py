# daemon/proxy.py
import socket, threading, json, time
from urllib import request as ureq, error as uerr
from itertools import cycle

from .utils import parse_cookies          
from .response import Response            

CRLF = b"\r\n"
HDR_END = b"\r\n\r\n"
BUF = 16384
TIMEOUT = 35

# ------------------------ DB-backed auth --------------------

DB_BASE = "http://127.0.0.1:9010"
_SID_CACHE = {}        # sid -> (ok_bool, expires_epoch)
_SID_CACHE_TTL = 3.0   # seconds

def _db_session_valid(sid: str) -> bool:
    try:
        payload = json.dumps({"sid": sid}).encode("utf-8")
        req = ureq.Request(
            DB_BASE + "/db/session/get",
            data=payload,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with ureq.urlopen(req, timeout=2.0) as r:
            data = json.loads(r.read().decode("utf-8", "ignore"))
            return "session" in data
    except (uerr.HTTPError, uerr.URLError, TimeoutError, OSError, ValueError):
        return False

def is_authenticated(headers: dict) -> bool:
    cookies = parse_cookies(headers.get("cookie", ""))
    sid = cookies.get("sid", "")
    if not sid:
        return False
    now = time.time()
    cached = _SID_CACHE.get(sid)
    if cached and cached[1] > now:
        return cached[0]
    ok = _db_session_valid(sid)
    _SID_CACHE[sid] = (ok, now + _SID_CACHE_TTL)
    return ok

# ------------------------ small helpers & auth gate ---------------------------

def _send_redirect(conn, location="/login.html"):
    body = b""
    head = (
        f"HTTP/1.1 302 Found\r\nLocation: {location}\r\n"
        f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n"
    ).encode("utf-8")
    conn.sendall(head + body)

# public assets (no auth)
_PUBLIC_PREFIXES = ("/images", "/css", "/js", "/static")
_PUBLIC_FILES = ("/favicon.ico", "/styles.css")

def _is_public(path: str) -> bool:
    if path in ("/", "/restool.html", "/landing.html", "/login.html"):
        return True
    if path in _PUBLIC_FILES:
        return True
    return any(path.startswith(p) for p in _PUBLIC_PREFIXES)

# ----------------------------- wire-level io ---------------------------------

def _recv_until_headers(conn) -> bytes:
    buf = bytearray()
    while True:
        chunk = conn.recv(BUF)
        if not chunk:
            break
        buf += chunk
        if HDR_END in buf:
            break
    return bytes(buf)

def _recv_exact(conn, n: int) -> bytes:
    buf = bytearray()
    left = n
    while left > 0:
        chunk = conn.recv(min(BUF, left))
        if not chunk:
            break
        buf += chunk
        left -= len(chunk)
    return bytes(buf)

def _read_until(sock, token: bytes, bufsize=BUF, max_bytes=8_388_608):
    out = bytearray()
    while True:
        chunk = sock.recv(bufsize)
        if not chunk:
            break
        out += chunk
        if token in out:
            break
        if len(out) > max_bytes:
            break
    return bytes(out)

def _parse_request_line_and_headers(head_bytes: bytes):
    text = head_bytes.decode("iso-8859-1", "ignore")
    lines = text.split("\r\n")
    if not lines or not lines[0]:
        return None, None, None, {}
    method, path, version = lines[0].split()
    headers = {}
    for line in lines[1:]:
        if not line:
            continue
        if ":" in line:
            k, v = line.split(":", 1)
            headers[k.strip().lower()] = v.strip()
    return method, path, version, headers

def _sanitize_hop_by_hop(headers: dict):
    # remove hop-by-hop headers per RFC 7230 §6.1
    for k in ("connection", "proxy-connection", "keep-alive",
              "te", "trailer", "transfer-encoding", "upgrade"):
        headers.pop(k, None)

def _build_request_bytes(method, path, version, headers: dict, body: bytes) -> bytes:
    # IMPORTANT: 'path' may contain query; keep it as-is.
    start = f"{method} {path} {version}\r\n".encode("iso-8859-1")
    out = bytearray(start)
    for k, v in headers.items():
        # Re-emit header names using standard casing; HTTP/1.1 header field-names are case-insensitive.
        name = "-".join(part.capitalize() for part in k.split("-"))
        out += f"{name}: {v}\r\n".encode("iso-8859-1")
    out += b"\r\n"
    if body:
        out += body
    return bytes(out)

def _x_forwarded(headers: dict, client_addr):
    ip = client_addr[0]
    xf = headers.get("x-forwarded-for")
    headers["x-forwarded-for"] = (xf + ", " + ip) if xf else ip
    headers.setdefault("x-forwarded-proto", "http")

# --------------------------- upstream forwarding ------------------------------

def forward_request(host, port, request):
    request_bytes = request if isinstance(request, (bytes, bytearray)) else str(request).encode("iso-8859-1")
    backend = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    backend.settimeout(30)
    try:
        backend.connect((host, port))
        backend.sendall(request_bytes)
        print(f"[Proxy] Forwarding request to {host}:{port}")

        head_and_tail = _read_until(backend, HDR_END)
        if not head_and_tail:
            raise OSError("empty upstream response")

        head, _, tail = head_and_tail.partition(HDR_END)

        # Read body by Content-Length if present; otherwise try to drain briefly.
        clen = 0
        for line in head.decode("iso-8859-1", "ignore").split("\r\n")[1:]:
            if not line:
                continue
            if ":" in line:
                k, v = line.split(":", 1)
                if k.strip().lower() == "content-length":
                    try:
                        clen = int(v.strip() or "0")
                    except ValueError:
                        clen = 0
                    break

        body = tail
        if clen > len(tail):
            body += _recv_exact(backend, clen - len(tail))

        if clen == 0:
            backend.settimeout(1.0)
            try:
                while True:
                    chunk = backend.recv(BUF)
                    if not chunk:
                        break
                    body += chunk
            except socket.timeout:
                pass

        return head + HDR_END + body

    except OSError as e:
        print(f"[Proxy] upstream error to {host}:{port} -> {e}")
        return (
            b"HTTP/1.1 502 Bad Gateway\r\n"
            b"Content-Type: text/plain\r\n"
            b"Content-Length: 11\r\n"
            b"Connection: close\r\n\r\nBad Gateway"
        )
    finally:
        try:
            backend.close()
        except Exception:
            pass

# --------------------------- routing & policy layer ---------------------------

class RoundRobinPool:
    def __init__(self, backends):
        self._backs = list(backends) if backends else [("127.0.0.1", 9)]
        self._it = cycle(self._backs)
    def pick(self):
        backend = next(self._it)
        print(f"[Proxy] Round-robin picked {backend[0]}:{backend[1]}")
        return backend

def _normalize_routes(routes):
    canon = {}
    for host, conf in (routes or {}).items():
        backs = []
        for url in conf.get("proxy_pass", []):
            val = url.split("://", 1)[-1]
            h, p = val.split(":", 1)
            backs.append((h.strip(), int(p)))
        if not backs:
            backs = [("127.0.0.1", 9)]
        canon[host] = {
            "pool": RoundRobinPool(backs),
            "preserve_host": bool(conf.get("preserve_host", False)),
            "policy": conf.get("policy", "round-robin"),
        }
    return canon

def _routes_already_normalized(routes: dict) -> bool:
    for v in (routes or {}).values():
        if isinstance(v, dict) and "pool" in v:
            return True
    return False

def resolve_routing_policy(hostname, routes):
    if not hostname:
        hostname = ""
    print(f"[Proxy] Resolving host: {hostname}")
    conf = routes.get(hostname) or routes.get(hostname.split(":", 1)[0]) or routes.get("*")
    if not conf:
        print(f"[Proxy] No route found for {hostname}, returning dummy.")
        return "127.0.0.1", 9, False
    up_host, up_port = conf["pool"].pick()
    print(f"[Proxy] Routed to {up_host}:{up_port} for {hostname or '*'}")
    return up_host, up_port, conf.get("preserve_host", False)

# --------- /api/* router (auth → auth.local, everything else → p2p.local) -----

_AUTH_PATHS = {"/login", "/logout", "/me"}

def _pick_upstream_for_api(api_path: str, routes):
    """
    api_path is the full path including '/api/...'
    We forward:
      - '/api/login', '/api/logout', '/api/me'  -> auth.local
      - ALL OTHER '/api/*'                      -> p2p.local

    NOTE: We DO NOT strip the querystring. It rides in `api_path`.
    """
    if not api_path.startswith("/api/"):
        return None, None, False, None

    # preserve query string (e.g., "/api/get-list?channel=x" -> "/get-list?channel=x")
    upstream_path = api_path[len("/api"):] or "/"

    # auth
    if upstream_path in _AUTH_PATHS:
        conf = routes.get("auth.local")
        if conf:
            up_host, up_port = conf["pool"].pick()
            return up_host, up_port, conf.get("preserve_host", False), upstream_path

    # default: p2p
    conf = routes.get("p2p.local")
    if conf:
        up_host, up_port = conf["pool"].pick()
        return up_host, up_port, conf.get("preserve_host", False), upstream_path

    # nothing configured
    return None, None, False, None

# ------------------------------- static serving -------------------------------

def _serve_static(conn, method, path, headers):
    class _R: pass
    req = _R()
    req.method = method
    req.path = path                      # let Response handle '/' -> landing.html
    req.headers = headers
    wire = Response().build_response(req)
    conn.sendall(wire)

# --------------------------------- main loop ----------------------------------

def handle_client(ip, port, conn, addr, routes):
    try:
        head_and_tail = _recv_until_headers(conn)
        if not head_and_tail:
            return

        head, _, tail = head_and_tail.partition(HDR_END)
        method, path, version, headers = _parse_request_line_and_headers(head)
        if not method:
            return

        # Read body if Content-Length present
        clen = int(headers.get("content-length", "0") or "0")
        already = tail[:clen]
        missing = clen - len(already)
        body = already + (_recv_exact(conn, missing) if missing > 0 else b"")

        # -------------------- /api/* → upstream --------------------
        if path.startswith("/api/"):
            up_host, up_port, preserve_host, upstream_path = _pick_upstream_for_api(path, routes)
            if not up_host:
                host_hdr = headers.get("host", "")
                up_host, up_port, preserve_host = resolve_routing_policy(host_hdr, routes)
                upstream_path = path[len("/api"):] or "/"

            # Hop-by-hop cleanup and proxy headers
            _sanitize_hop_by_hop(headers)
            _x_forwarded(headers, addr)

            # Host header
            if not preserve_host:
                headers["host"] = f"{up_host}:{up_port}"

            # Connection policy
            headers["connection"] = "close"

            # Content-Length only if we actually have a body
            if body:
                headers["content-length"] = str(len(body))
            else:
                headers.pop("content-length", None)

            # Build and forward
            outgoing = _build_request_bytes(method, upstream_path, version, headers, body)
            print(f"[Proxy] {method} {upstream_path} -> {up_host}:{up_port}")
            upstream = forward_request(up_host, up_port, outgoing)
            conn.sendall(upstream)
            return

        # --------------- Static (auth-gated except public) ---------------
        if not _is_public(path):
            if not is_authenticated(headers):
                _send_redirect(conn, "/login.html")
                return

        _serve_static(conn, method, path, headers)

    except Exception as e:
        try:
            msg = f"Internal Server Error: {e}".encode("utf-8")
            conn.sendall(
                b"HTTP/1.1 500 Internal Server Error\r\nContent-Type: text/plain\r\n"
                + f"Content-Length: {len(msg)}\r\n".encode("iso-8859-1")
                + b"Connection: close\r\n\r\n" + msg
            )
        except Exception:
            pass
    finally:
        try:
            conn.close()
        except Exception:
            pass

# ----------------------------------- server -----------------------------------

def run_proxy(ip, port, routes):
    if not _routes_already_normalized(routes):
        routes = _normalize_routes(routes)

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((ip, port))
    srv.listen(128)
    print(f"[Proxy] Listening on {ip}:{port}")

    try:
        while True:
            c, a = srv.accept()
            threading.Thread(
                target=handle_client,
                args=(ip, port, c, a, routes),
                daemon=True
            ).start()
    finally:
        srv.close()

def create_proxy(ip, port, routes):
    run_proxy(ip, port, routes)
