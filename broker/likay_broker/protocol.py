"""
Formato de mensaje del Broker: JSON-RPC 2.0 (subconjunto) sobre líneas
newline-delimited -- mismo formato que ya usa
vendor/kal/kernel/api/protocol.py (que a su vez lo tomó de LSP), para
no inventar un esquema propio nuevo. Funciones puras -- sin sockets,
testeables sin un servidor real.

Solo dos métodos existen en v1 -- "check_capability" y
"register_policy" -- con fronteras de autorización DISTINTAS resueltas
por socket_server.py vía SO_PEERCRED, nunca acá. Este módulo no sabe
nada de autorización, solo de formato de mensaje.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

JSONRPC_VERSION = "2.0"

METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32000
PERMISSION_DENIED = -32001

ALLOWED_METHODS = frozenset({"check_capability", "register_policy"})


class ProtocolError(Exception):
    """Un mensaje no se pudo parsear como un pedido JSON-RPC válido."""


@dataclass
class Request:
    id: int | str
    method: str
    params: dict[str, Any] = field(default_factory=dict)


def parse_request(line: str) -> Request:
    try:
        data = json.loads(line)
    except json.JSONDecodeError as e:
        raise ProtocolError(f"línea no es JSON válido: {e}") from e

    if not isinstance(data, dict):
        raise ProtocolError("el mensaje debe ser un objeto JSON")
    if data.get("jsonrpc") != JSONRPC_VERSION:
        raise ProtocolError(f"jsonrpc debe ser '{JSONRPC_VERSION}'")
    if "id" not in data:
        raise ProtocolError("falta 'id'")
    method = data.get("method")
    if not isinstance(method, str) or not method:
        raise ProtocolError("'method' debe ser un string no vacío")
    params = data.get("params", {})
    if not isinstance(params, dict):
        raise ProtocolError("'params' debe ser un objeto")

    return Request(id=data["id"], method=method, params=params)


def success_response(request_id: int | str, result: dict[str, Any]) -> str:
    return json.dumps({"jsonrpc": JSONRPC_VERSION, "id": request_id, "result": result})


def error_response(request_id: int | str | None, code: int, message: str) -> str:
    return json.dumps(
        {"jsonrpc": JSONRPC_VERSION, "id": request_id, "error": {"code": code, "message": message}}
    )
