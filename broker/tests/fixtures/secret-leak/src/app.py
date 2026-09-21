import hashlib
import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer

SECRET_NAME = "LIKAY_TEST_SECRET"


def check_secret() -> dict:
    value = os.environ.get(SECRET_NAME)
    if not value:
        return {"received": False}
    # Nunca devolver el valor crudo -- ni siquiera en la respuesta de
    # esta prueba, que un humano puede llegar a ver en una terminal.
    # El hash alcanza para confirmar que el valor exacto llegó, sin
    # convertirse él mismo en un vector de fuga adicional.
    return {"received": True, "sha256": hashlib.sha256(value.encode()).hexdigest(), "uid": os.getuid()}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        body = json.dumps(check_secret()).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args) -> None:
        pass


if __name__ == "__main__":
    HTTPServer(("0.0.0.0", 8000), Handler).serve_forever()
