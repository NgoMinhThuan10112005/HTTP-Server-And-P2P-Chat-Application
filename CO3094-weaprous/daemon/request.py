# daemon/request.py
# -----------------------------------------------------------------------------
# HTTP Request object: parse request line + headers; normalize path; cookies
# -----------------------------------------------------------------------------

from .dictionary import CaseInsensitiveDict
from .utils import parse_cookies

class Request:
    __attrs__ = [
        "method",
        "url",
        "headers",
        "body",
        "reason",
        "cookies",
        "body",
        "routes",
        "hook",
    ]

    def __init__(self):
        self.method = None          
        self.url = None
        self.headers = {}            
        self.path = None             
        self.path_noq = None        
        self.query = ""              
        self.cookies = {}            
        self.body = b""              
        self.routes = {}             
        self.hook = None             
        self.version = "HTTP/1.1"    # default
        self.reason = None

    def extract_request_line(self, raw: str):
        """
        Parse 'GET /path?x=1 HTTP/1.1'. Return (method, path, version).
        Do not rewrite '/' here; static policy handles that in Response.
        """
        try:
            lines = raw.splitlines()
            first_line = lines[0]
            method, path, version = first_line.split()
            if "?" in path:
                p, q = path.split("?", 1)
                self.path_noq, self.query = p, q
            else:
                self.path_noq, self.query = path, ""
            return method, path, version
        except Exception:
            return None, None, None

    def prepare_headers(self, raw: str) -> dict:
        """
        Parse headers into a lowercase-keyed dict. Stops at the blank line.
        """
        headers = {}
        head, _, _ = raw.partition("\r\n\r\n")
        lines = head.split("\r\n")
        for line in lines[1:]:
            if not line:
                break
            if ":" in line:
                key, val = line.split(":", 1)
                headers[key.strip().lower()] = val.strip()
        return headers

    def prepare(self, raw: str, routes=None):
        """
        Prepare fields from raw HTTP header bytes (string).
        Adapter is responsible for reading the remaining body via Content-Length.
        """
        self.method, self.path, self.version = self.extract_request_line(raw)
        print(f"[Request] {self.method} path {self.path} version {self.version}")

        self.headers = self.prepare_headers(raw)
        self.cookies = parse_cookies(self.headers.get("cookie", ""))

        # Resolve route hook: exact match first, then queryless path
        routes = routes or {}
        if routes:
            self.routes = routes
            self.hook = routes.get((self.method, self.path)) or routes.get((self.method, self.path_noq))
        return

    # Optional helpers (kept minimal for this assignment)
    def prepare_cookies(self, cookie_header_value: str):
        self.headers["cookie"] = cookie_header_value
