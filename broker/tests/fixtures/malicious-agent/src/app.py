"""
Variante del dummy-agent que intenta escapar el sandbox al arrancar --
ver docs/AGENT_INTERFACE.md y la verificación (c) del plan. Cada
intento se hace de verdad (no se simula) y el resultado (éxito/fallo)
se loguea a un archivo DENTRO de su propio data_dir -- el único lugar
donde el sandbox generado (ver mapeo sandbox->systemd en
AGENT_INTERFACE.md sección 4) le permite escribir.

Los 7 intentos están elegidos para mapear a una directiva concreta de
la tabla de esa sección, no genéricos -- así un DENIED real confirma
qué directiva específica está funcionando:

  1. leer /etc/shadow          -> permisos Unix normales + ProtectSystem=strict
  2. escribir en /etc/          -> ProtectSystem=strict (read-only a nivel mount)
  3. abrir /dev/sda              -> PrivateDevices=yes (/dev queda casi vacío)
  4. socket AF_INET/SOCK_RAW    -> sin CAP_NET_RAW, NoNewPrivileges=yes
  5. os.setuid(0)                -> sin CAP_SETUID, NoNewPrivileges=yes
  6. leer /root/.bashrc          -> ProtectHome=yes
  7. bindear puerto <1024        -> sin CAP_NET_BIND_SERVICE, UID no-root

GAP HONESTO, documentado a propósito (no oculto): un octavo intento
obvio de la lista original del usuario -- "abrir un listener en una
interfaz que no sea loopback" con un puerto SIN privilegios -- NO está
cubierto acá porque v1 no lo restringe: sandbox.network: host-egress
da acceso de red normal del host (ver AGENT_INTERFACE.md, por qué se
llama "host-egress" y no "egress"), y nada en la tabla de mapeo actual
impide que el propio código del agente abra un socket adicional en
0.0.0.0 sobre un puerto alto. El único lugar donde se fuerza
loopback-only es el ExecStart= del servicio PRINCIPAL (ver "bind_host"
en AGENT_INTERFACE.md sección 3), no una restricción general del
sandbox. Foto real del alcance de v1, no un intento fallido escondido.
"""
import json
import os
import socket
from pathlib import Path

from fastapi import FastAPI

DATA_DIR = Path(os.environ.get("AGENT_STATE_DIR", "./data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
LOG_PATH = DATA_DIR / "escape_attempts.log"


def _attempt(name: str, fn) -> dict:
    try:
        fn()
        return {"attempt": name, "result": "SUCCEEDED"}
    except (PermissionError, OSError, FileNotFoundError) as exc:
        return {"attempt": name, "result": "DENIED", "error": f"{type(exc).__name__}: {exc}"}
    except Exception as exc:  # noqa: BLE001 -- se quiere capturar CUALQUIER falla, es un test de escape
        return {"attempt": name, "result": "DENIED", "error": f"{type(exc).__name__}: {exc}"}


def _read_shadow() -> None:
    Path("/etc/shadow").read_text()


def _write_etc() -> None:
    Path("/etc/likay-escape-test").write_text("si esto se escribió, el sandbox falló\n")


def _open_raw_device() -> None:
    with open("/dev/sda", "rb"):
        pass


def _create_raw_socket() -> None:
    s = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_ICMP)
    s.close()


def _setuid_root() -> None:
    os.setuid(0)


def _read_outside_data_dir() -> None:
    Path("/root/.bashrc").read_text()


def _bind_privileged_port() -> None:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", 80))
    finally:
        s.close()


def run_all_attempts() -> list[dict]:
    results = [
        _attempt("read_etc_shadow", _read_shadow),
        _attempt("write_etc", _write_etc),
        _attempt("open_raw_device", _open_raw_device),
        _attempt("create_raw_socket", _create_raw_socket),
        _attempt("setuid_root", _setuid_root),
        _attempt("read_outside_data_dir", _read_outside_data_dir),
        _attempt("bind_privileged_port", _bind_privileged_port),
    ]
    LOG_PATH.write_text(json.dumps(results, indent=2) + "\n")
    return results


app = FastAPI()
_startup_results = run_all_attempts()


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/escape-attempts")
def escape_attempts() -> list[dict]:
    """Expuesto también por HTTP para que el test de QEMU no dependa de leer el filesystem del agente."""
    return _startup_results
