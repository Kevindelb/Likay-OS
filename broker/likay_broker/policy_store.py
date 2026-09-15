"""
Almacén de política del Broker -- /var/lib/likay-agent-broker/policy.json.

v1 es deliberadamente simple (ver docs/AGENT_INTERFACE.md, sección 5):
una lista plana de grants, escrita una sola vez por agente en el
momento de instalar, sin flujo de escalación en runtime. Este módulo
NO decide quién puede llamar a las operaciones que lo tocan -- eso es
responsabilidad del socket_server (SO_PEERCRED), nunca de este código.
Este módulo asume que ya se decidió que la llamada es legítima.
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_POLICY_PATH = Path("/var/lib/likay-agent-broker/policy.json")


@dataclass(frozen=True)
class AgentGrant:
    agent_id: str
    linux_user: str
    capabilities: list[str]
    installed_at: str  # ISO 8601, decidido por el caller (helper/TUI)


class PolicyStore:
    """
    Lectura/escritura de policy.json. Escritura atómica (write-tmp +
    rename) para no dejar el archivo a medio escribir si el proceso
    muere en el medio -- el Broker lee este archivo en cada
    check_capability, así que un archivo corrupto tumbaría TODAS las
    consultas, no solo la última escritura.
    """

    def __init__(self, path: Path = DEFAULT_POLICY_PATH) -> None:
        self._path = path

    def _load_raw(self) -> list[dict[str, Any]]:
        if not self._path.exists():
            return []
        with open(self._path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            raise ValueError(f"{self._path} corrupto: se esperaba una lista JSON")
        return data

    def load_all(self) -> list[AgentGrant]:
        return [AgentGrant(**entry) for entry in self._load_raw()]

    def get_grant(self, *, linux_user: str) -> AgentGrant | None:
        """
        Búsqueda por usuario Linux, NUNCA por agent_id que venga de la
        solicitud -- check_capability resuelve primero la UID del peer
        vía SO_PEERCRED a un nombre de usuario, y recién con ESE nombre
        (nunca con un string que el propio proceso mandó) se busca acá.
        """
        for grant in self.load_all():
            if grant.linux_user == linux_user:
                return grant
        return None

    def upsert_grant(self, grant: AgentGrant) -> None:
        """
        Reemplaza el grant existente para ese agent_id (reinstalar un
        agente pisa su grant anterior) o lo agrega si es nuevo.
        """
        entries = self._load_raw()
        entries = [e for e in entries if e.get("agent_id") != grant.agent_id]
        entries.append(asdict(grant))
        self._write_atomic(entries)

    def remove_grant(self, *, agent_id: str) -> None:
        entries = self._load_raw()
        entries = [e for e in entries if e.get("agent_id") != agent_id]
        self._write_atomic(entries)

    def _write_atomic(self, entries: list[dict[str, Any]]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            dir=self._path.parent, prefix=".policy-", suffix=".json.tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(entries, f, indent=2, sort_keys=True)
                f.write("\n")
            os.chmod(tmp_name, 0o640)
            os.rename(tmp_name, self._path)
        except BaseException:
            os.unlink(tmp_name)
            raise
