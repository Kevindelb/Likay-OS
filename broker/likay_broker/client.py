"""
Cliente mínimo del socket del Broker -- lo usa agent-install-launcher
(la TUI, corriendo como likay-agent-install, sin pkexec) para llamar
register_policy directo, sin pasar por el helper privilegiado (ver
docs/AGENT_INTERFACE.md sección 5: la autorización de register_policy
la decide el Broker por credencial Unix del socket, no hace falta
root para esa llamada en absoluto).
"""
from __future__ import annotations

import itertools
import json
import socket
from pathlib import Path
from typing import Any

from likay_broker.socket_server import DEFAULT_SOCKET_PATH

_id_counter = itertools.count(1)


class BrokerClientError(RuntimeError):
    pass


def _call(method: str, params: dict[str, Any], *, socket_path: Path = DEFAULT_SOCKET_PATH) -> dict[str, Any]:
    req_id = next(_id_counter)
    payload = json.dumps({"jsonrpc": "2.0", "id": req_id, "method": method, "params": params})

    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.connect(str(socket_path))
        sock.sendall((payload + "\n").encode("utf-8"))

        buf = b""
        while b"\n" not in buf:
            chunk = sock.recv(4096)
            if not chunk:
                raise BrokerClientError("el Broker cerró la conexión sin responder")
            buf += chunk

    line, _, _ = buf.partition(b"\n")
    response = json.loads(line.decode("utf-8"))

    if "error" in response:
        raise BrokerClientError(response["error"]["message"])
    return response["result"]


def register_policy(
    *, agent_id: str, linux_user: str, capabilities: list[str], socket_path: Path = DEFAULT_SOCKET_PATH,
) -> None:
    result = _call(
        "register_policy",
        {"agent_id": agent_id, "linux_user": linux_user, "capabilities": capabilities},
        socket_path=socket_path,
    )
    if result.get("decision") != "ALLOW":
        raise BrokerClientError(f"register_policy no autorizado: {result}")


def unregister_policy(*, linux_user: str, socket_path: Path = DEFAULT_SOCKET_PATH) -> bool:
    """
    Hallazgo real (2026-09-17): remove_grant() del PolicyStore existía
    sin ningún caller -- ver el docstring largo de
    _handle_unregister_policy en socket_server.py. Llamada por la TUI
    (agent-install-launcher) con su propia credencial Unix, igual que
    register_policy -- nunca por el helper, que no necesita tocar el
    Broker para nada. Devuelve si de verdad había un grant para borrar
    (False es normal la primera vez que se instala un agente, cuando
    activate_agent no desactivó ningún agente anterior).
    """
    result = _call("unregister_policy", {"linux_user": linux_user}, socket_path=socket_path)
    if result.get("decision") != "ALLOW":
        raise BrokerClientError(f"unregister_policy no autorizado: {result}")
    return bool(result.get("removed"))


def check_capability(*, capability: str, socket_path: Path = DEFAULT_SOCKET_PATH) -> bool:
    result = _call("check_capability", {"capability": capability}, socket_path=socket_path)
    return result.get("decision") == "ALLOW"
