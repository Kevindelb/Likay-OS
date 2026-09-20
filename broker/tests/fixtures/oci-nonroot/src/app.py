import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer

STATE_DIR = os.environ.get("AGENT_STATE_DIR", "/var/lib/likay-agent/state")
MARKER_PATH = os.path.join(STATE_DIR, "write-test.txt")


def attempt_write() -> dict:
    try:
        with open(MARKER_PATH, "w") as f:
            f.write("ok\n")
        return {"write_state_dir": "OK"}
    except OSError as e:
        return {"write_state_dir": "DENIED", "error": str(e)}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        result = attempt_write()
        result["uid"] = os.getuid()
        body = json.dumps(result).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args) -> None:
        pass


if __name__ == "__main__":
    HTTPServer(("0.0.0.0", 8000), Handler).serve_forever()
