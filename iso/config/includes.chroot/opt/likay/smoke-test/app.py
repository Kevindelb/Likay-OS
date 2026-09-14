#!/usr/bin/env python3
# Página de "smoke test" para el kiosco, NO el kiosco nuevo real (ver
# docs/ROADMAP.md, Etapa 1 — ese todavía está por diseñarse). kal-backend.
# service (agent_core.orchestrator:app) quedó roto por el split kal/kal-in
# (vendor/kal ahora es el kernel puro, sin agente) — hasta que exista la
# interfaz genérica para montar un agente, esto es lo único que corre en
# :8000, solo para confirmar en QEMU que el LLM propio de Likay-OS
# (qwen2.5:3b, vía Ollama) arrancó bien, en vez de ver una página de error
# de conexión del navegador y no saber si el problema es el LLM o el
# kiosco.
#
# Solo librería estándar a propósito — esto es descartable, no vale la
# pena arrastrar una dependencia (ni siquiera FastAPI, que kal-in ya usa)
# para algo que se va a borrar en cuanto exista el kiosco de verdad.
import json
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

STATIC_DIR = Path(__file__).parent
OLLAMA_HOST = "http://127.0.0.1:11434"
MODEL_TAG = Path("/etc/likay-os/model.conf").read_text().split('"')[1] if Path(
    "/etc/likay-os/model.conf"
).exists() else "desconocido"


def _ollama_get(path: str):
    try:
        with urllib.request.urlopen(f"{OLLAMA_HOST}{path}", timeout=2) as r:
            return json.load(r)
    except (urllib.error.URLError, OSError, TimeoutError, ValueError):
        return None


def get_status() -> dict:
    tags = _ollama_get("/api/tags")
    ps = _ollama_get("/api/ps")
    present = bool(tags) and any(m.get("name") == MODEL_TAG or m.get("model") == MODEL_TAG for m in tags.get("models", []))
    loaded = bool(ps) and any(m.get("name") == MODEL_TAG or m.get("model") == MODEL_TAG for m in ps.get("models", []))
    return {
        "model_tag": MODEL_TAG,
        "ollama_reachable": tags is not None,
        "model_present": present,
        "model_loaded": loaded,
    }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # silencia el log de acceso por default — ya vamos por journal+console con demasiado ruido de por sí
        pass

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self._serve_file(STATIC_DIR / "index.html", "text/html; charset=utf-8")
        elif self.path == "/style.css":
            self._serve_file(STATIC_DIR / "style.css", "text/css; charset=utf-8")
        elif self.path == "/api/status":
            body = json.dumps(get_status()).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_error(404)

    def _serve_file(self, path: Path, content_type: str):
        try:
            body = path.read_bytes()
        except FileNotFoundError:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", 8000), Handler).serve_forever()
