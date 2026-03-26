# daemon/httpadapter.py
"""
daemon.httpadapter
~~~~~~~~~~~~~~~~~~

HTTP adapter: read bytes from socket → Request, dispatch route hook (if any),
or fall back to static Response, then serialize and write back.
"""
import json

from .request import Request
from .response import Response
from urllib.parse import parse_qs

CRLF = b"\r\n"
HDR_END = b"\r\n\r\n"


class HttpAdapter:
    __attrs__ = [
        "ip",
        "port",
        "conn",
        "connaddr",
        "routes",
        "request",
        "response",
    ]

    def __init__(self, ip, port, conn, connaddr, routes):
        self.ip = ip
        self.port = port
        self.conn = conn
        self.connaddr = connaddr
        self.routes = routes or {}
        self.request = Request()
        self.response = Response()

    # --------------------------- wire utils ----------------------------------

    def _recv_until_headers(self, conn) -> bytes:
        buf = bytearray()
        while True:
            chunk = conn.recv(4096)
            if not chunk:
                break
            buf += chunk
            if HDR_END in buf:
                break
        return bytes(buf)

    def _recv_exact(self, conn, n: int) -> bytes:
        buf = bytearray()
        left = n
        while left > 0:
            chunk = conn.recv(min(4096, left))
            if not chunk:
                break
            buf += chunk
            left -= len(chunk)
        return bytes(buf)

    # -------------------------- route helpers --------------------------------

    def _match_route(self, method: str, path: str):
        """Try exact path; if no match and path has '?', try without query."""
        hook = self.routes.get((method, path))
        if hook:
            return hook, path
        if "?" in path:
            bare = path.split("?", 1)[0]
            hook = self.routes.get((method, bare))
            if hook:
                return hook, bare
        return None, path

    # --------------------------- response helpers -----------------------------

    @staticmethod
    def _ensure_bytes(body):
        if body is None:
            return b""
        if isinstance(body, bytes):
            return body
        if isinstance(body, str):
            return body.encode("utf-8", errors="replace")
        # Fallback: JSON-encode arbitrary objects
        try:
            return json.dumps(body).encode("utf-8")
        except Exception:
            return b""

    @staticmethod
    def _serialize_tuple_response(status: int, headers: dict, body: bytes, head_only: bool = False) -> bytes:
        status = int(status or 200)
        reason = "OK" if status == 200 else "Error"
        headers = dict(headers or {})
        headers.setdefault("Connection", "close")
        headers.setdefault("Content-Length", str(len(body)))

        head_lines = [f"HTTP/1.1 {status} {reason}\r\n"]
        head_lines += [f"{k}: {v}\r\n" for k, v in headers.items()]
        head_lines.append("\r\n")
        wire = "".join(head_lines).encode("utf-8")
        return wire if head_only else wire + body

    # ------------------------------ main -------------------------------------

    def handle_client(self, conn, addr, routes):
        self.conn = conn
        self.connaddr = addr
        self.routes = routes or {}

        try:
            head_and_tail = self._recv_until_headers(conn)
            if not head_and_tail:
                return

            head, _, tail = head_and_tail.partition(HDR_END)
            head_text = head.decode("latin-1", errors="ignore")

            req = self.request
            req.prepare(head_text, self.routes)  

            if not req.hook:
                hook, matched_path = self._match_route(req.method, req.path or "/")
                if hook:
                    req.hook = hook
                    try:
                        print(f"[HttpAdapter] hook {hook._route_methods} {hook._route_path}")
                    except Exception:
                        print(f"[HttpAdapter] hook (resolved) {req.method} {matched_path}")

            clen = int(req.headers.get("content-length", "0") or "0")
            if clen:
                already = tail[:clen]
                missing = clen - len(already)
                more = self._recv_exact(conn, missing) if missing > 0 else b""
                req.body = already + more
            else:
                req.body = b""

            head_only = (req.method == "HEAD")

            # dispatch
            if req.hook:
                # Call handler
                full_path = req.path or "/"
                path_noq  = req.path_noq or full_path.split("?", 1)[0]
                raw_query = req.query or (full_path.split("?", 1)[1] if "?" in full_path else "")

                # put helpful hints into headers (don’t clobber if upstream set them)
                req.headers.setdefault("x-path", full_path)
                req.headers.setdefault("x-path-noq", path_noq)
                req.headers.setdefault("x-query", raw_query)

                try:
                    qd = parse_qs(raw_query, keep_blank_values=True)
                    norm = {k: (v[0] if len(v) == 1 else v) for k, v in qd.items()}
                    qjson = json.dumps(norm, separators=(",", ":"))
                except Exception:
                    qjson = "{}"
                req.headers.setdefault("x-query-json", qjson)

                if req.method == "GET" and not req.body and raw_query:
                    req.body = qjson.encode("utf-8")
                    req.headers.setdefault("content-type", "application/json")

                # Call handler
                result = req.hook(headers=req.headers, body=req.body)

                # Cases:
                # 1) tuple(status, headers, bodyLike)
                if isinstance(result, tuple):
                    status = int(result[0])
                    headers = dict(result[1] or {})
                    body_bytes = self._ensure_bytes(result[2] if len(result) >= 3 else b"")
                    wire = self._serialize_tuple_response(status, headers, body_bytes, head_only=head_only)

                # 2) dict → JSON 200
                elif isinstance(result, dict):
                    payload = json.dumps(result or {}).encode("utf-8")
                    headers = {
                        "Content-Type": "application/json; charset=utf-8",
                        "Connection": "close",
                        "Content-Length": str(len(payload)),
                    }
                    head = (
                        f"HTTP/1.1 200 OK\r\n"
                        + "".join(f"{k}: {v}\r\n" for k, v in headers.items())
                        + "\r\n"
                    ).encode("utf-8")
                    wire = head if head_only else head + payload

                # 3) bytes/str → 200 text/plain
                else:
                    body_bytes = self._ensure_bytes(result)
                    headers = {
                        "Content-Type": "text/plain; charset=utf-8",
                        "Connection": "close",
                        "Content-Length": str(len(body_bytes)),
                    }
                    head = (
                        f"HTTP/1.1 200 OK\r\n"
                        + "".join(f"{k}: {v}\r\n" for k, v in headers.items())
                        + "\r\n"
                    ).encode("utf-8")
                    wire = head if head_only else head + body_bytes

            else:
                # no hook → serve static
                wire = self.response.build_response(req)
                if head_only:
                    # strip body but keep headers as-is
                    wire = wire.split(b"\r\n\r\n", 1)[0] + b"\r\n\r\n"

            conn.sendall(wire)

        except Exception as e:
            # fail closed
            msg = f"Internal Server Error: {e}".encode("utf-8")
            try:
                conn.sendall(
                    b"HTTP/1.1 500 Internal Server Error\r\n"
                    b"Content-Type: text/plain\r\n"
                    + f"Content-Length: {len(msg)}\r\n".encode()
                    + b"Connection: close\r\n\r\n"
                    + msg
                )
            except Exception:
                pass
        finally:
            try:
                conn.close()
            except Exception:
                pass
