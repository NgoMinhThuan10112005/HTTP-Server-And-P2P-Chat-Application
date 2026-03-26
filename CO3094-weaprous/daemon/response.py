# daemon/response.py
# -----------------------------------------------------------------------------
# HTTP Response object: MIME detection, file loading, header serialization
# -----------------------------------------------------------------------------

import datetime
import os
import mimetypes
from .dictionary import CaseInsensitiveDict

# Project root = parent of this file's directory (daemon/)
BASE_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))

class Response:
    __attrs__ = [
        "_content",
        "_header",
        "status_code",
        "method",
        "headers",
        "url",
        "history",
        "encoding",
        "reason",
        "cookies",
        "elapsed",
        "request",
        "body",
        "reason",
    ]

    def __init__(self, request=None):
        self._content = b""
        self._content_consumed = False
        self._next = None

        self.status_code = 200
        self.headers = {}
        self.url = None
        self.encoding = None
        self.history = []
        self.reason = "OK"
        self.cookies = CaseInsensitiveDict()
        self.elapsed = datetime.timedelta(0)
        self.request = request

    # ---------- MIME & path resolution ----------

    def get_mime_type(self, path: str) -> str:
        try:
            mime_type, _ = mimetypes.guess_type(path)
        except Exception:
            return "application/octet-stream"
        return mime_type or "application/octet-stream"

    def _handle_text_other(self, sub_type: str):
        raise ValueError(f"Unsupported text subtype: {sub_type}")

    def prepare_content_type(self, mime_type="text/html"):
        """
        Set Content-Type and return a base directory for the requested resource.
        """
        base_dir = ""
        main_type, sub_type = mime_type.split("/", 1)
        print(f"[Response] processing MIME main_type={main_type} sub_type={sub_type}")
        if main_type == "text":
            self.headers["Content-Type"] = f"text/{sub_type}"
            if sub_type == "html":
                base_dir = os.path.join(BASE_DIR, "www")
            elif sub_type == "css":
                base_dir = os.path.join(BASE_DIR)
            elif sub_type in ("javascript", "js"):
                base_dir = os.path.join(BASE_DIR)
            elif sub_type == "plain":
                base_dir = os.path.join(BASE_DIR, "static")
            else:
                self._handle_text_other(sub_type)
        elif main_type == "image":
            base_dir = os.path.join(BASE_DIR)
            self.headers["Content-Type"] = f"image/{sub_type}"
        elif main_type == "application":
            base_dir = os.path.join(BASE_DIR, "apps")
            self.headers["Content-Type"] = f"application/{sub_type}"
        else:
            raise ValueError(f"Invalid MIME type: {main_type}/{sub_type}")

        return base_dir

    # ---------- Content & headers ----------

    def build_content(self, path: str, base_dir: str):
        """
        Read file content from disk safely under base_dir.
        Return (length:int, bytes). 0-length means not found/forbidden.
        """
        abs_base = os.path.abspath(base_dir)
        abs_target = os.path.abspath(os.path.join(abs_base, path.lstrip("/")))

        # prevent traversal
        if not (abs_target == abs_base or abs_target.startswith(abs_base + os.sep)):
            return 0, b""

        print(f"[Response] serving the object at location {abs_target}")
        if not os.path.isfile(abs_target):
            return 0, b""

        with open(abs_target, "rb") as f:
            content = f.read()
        return len(content), content

    def build_response_header(self, request):
        """
        Build a proper HTTP/1.1 response header block based on current state.
        """
        status = int(self.status_code or 200)
        reason = self.reason or ("OK" if status == 200 else "Error")

        # Ensure core headers
        self.headers.setdefault("Content-Type", "text/html; charset=utf-8")
        self.headers.setdefault("Content-Length", str(len(self._content or b"")))
        self.headers.setdefault("Connection", "close")
        self.headers.setdefault(
            "Date",
            datetime.datetime.utcnow().strftime("%a, %d %b %Y %H:%M:%S GMT"),
        )

        lines = [f"HTTP/1.1 {status} {reason}\r\n"]
        for k, v in self.headers.items():
            lines.append(f"{k}: {v}\r\n")
        lines.append("\r\n")
        return "".join(lines).encode("utf-8")

    def build_notfound(self):
        body = b"404 Not Found"
        head = (
            "HTTP/1.1 404 Not Found\r\n"
            "Accept-Ranges: bytes\r\n"
            "Content-Type: text/html\r\n"
            f"Content-Length: {len(body)}\r\n"
            "Cache-Control: max-age=86000\r\n"
            "Connection: close\r\n"
            "\r\n"
        ).encode("utf-8")
        return head + body

    def build_response(self, request):
        """
        Serve static assets (HTML/CSS/images/JS). Strip ?query for file lookup.
        """
        raw_path = request.path or "/"
        path = raw_path.split("?", 1)[0]  

        # Root -> landing page (static policy)
        if path == "/":
            path = "/landing.html"

        mime_type = self.get_mime_type(path)
        print(f"[Request] {request.method} path {raw_path} mime_type {mime_type}")

        if path == "/favicon.ico":
            base_dir = os.path.join(BASE_DIR, "static", "images")
            mime_type = "image/x-icon"
        elif path.endswith(".html") or mime_type == "text/html":
            base_dir = self.prepare_content_type("text/html")
        elif mime_type == "text/css":
            base_dir = self.prepare_content_type("text/css")
        elif mime_type in ("application/javascript", "text/javascript"):
            base_dir = self.prepare_content_type("text/javascript")
        elif mime_type and mime_type.startswith("image/"):
            base_dir = self.prepare_content_type(mime_type)
        else:
            return self.build_notfound()

        c_len, self._content = self.build_content(path, base_dir)
        if c_len == 0:
            return self.build_notfound()

        self.status_code = 200
        self.reason = "OK"
        self.headers["Content-Length"] = str(c_len)
        self.headers["Content-Type"] = mime_type
        self._header = self.build_response_header(request)
        return self._header + self._content
