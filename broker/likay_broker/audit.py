"""
Log de auditoría del Broker -- /var/log/likay-agent-broker/audit.log.

Toda decisión del Broker (ALLOW o DENY, para check_capability O
register_policy) se loguea siempre, sin excepción -- ver
docs/AGENT_INTERFACE.md sección 6. Append-only JSONL: una línea por
evento, nunca se reescribe ni se borra desde este módulo.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Literal

DEFAULT_AUDIT_LOG_PATH = Path("/var/log/likay-agent-broker/audit.log")

Decision = Literal["ALLOW", "DENY"]


class AuditLog:
    def __init__(self, path: Path = DEFAULT_AUDIT_LOG_PATH) -> None:
        self._path = path

    def record(
        self,
        *,
        peer_user: str,
        method: str,
        decision: Decision,
        detail: dict[str, Any] | None = None,
    ) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        event = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "peer_user": peer_user,
            "method": method,
            "decision": decision,
            "detail": detail or {},
        }
        # Append, no reescribe: si dos conexiones loguean a la vez, el
        # peor caso es que se intercalen líneas completas (escritura
        # de una sola línea con \n es atómica en Linux para archivos
        # abiertos en modo append, POSIX O_APPEND), nunca corrupción
        # parcial de una línea.
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, sort_keys=True) + "\n")
