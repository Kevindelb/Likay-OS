"""
Log de auditoría del Broker -- /var/log/likay-agent-broker/audit.log.

Toda decisión del Broker (ALLOW o DENY, para check_capability O
register_policy) se loguea siempre, sin excepción -- ver
docs/AGENT_INTERFACE.md sección 6. Append-only JSONL: una línea por
evento, nunca se reescribe ni se borra desde este módulo.

Cadena hash-linked (portado de vendor/kal/audit/audit_log.py, 2026-09-17
-- ver docs/AGENT_INTERFACE.md sección 6 y la memoria del proyecto:
"Audit log del Broker sin cadena verificable, pese a lo que promete el
README raíz"): cada entrada incluye el hash SHA-256 de la anterior, así
una edición retroactiva del archivo (por ejemplo, un agente malicioso
con acceso de escritura local intentando borrar su propio rastro) rompe
la cadena de forma detectable -- no es criptográficamente inviolable
(para eso haría falta firma externa / almacenamiento WORM real), pero
sí hace la manipulación evidente en vez de silenciosa. `kal` ya había
encontrado y arreglado en uso real el bug obvio de esta clase de diseño:
cachear el "último hash" en memoria del proceso rompe la cadena en
cuanto dos escritores (p.ej. el propio broker + un script de
verificación aparte) escriben intercalado -- acá se porta el mismo fix,
no solo el hash-chaining: leer SIEMPRE el último hash del disco (nunca
de un caché), bajo un lock exclusivo de archivo (fcntl.flock, POSIX)
que cubre todo el ciclo leer-último-hash + escribir.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

DEFAULT_AUDIT_LOG_PATH = Path("/var/log/likay-agent-broker/audit.log")

Decision = Literal["ALLOW", "DENY"]


@dataclass
class AuditEvent:
    peer_user: str
    method: str
    decision: Decision
    detail: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    prev_hash: str = ""
    event_hash: str = ""

    def compute_hash(self) -> str:
        payload = json.dumps(
            {
                "peer_user": self.peer_user,
                "method": self.method,
                "decision": self.decision,
                "detail": self.detail,
                "timestamp": self.timestamp,
                "prev_hash": self.prev_hash,
            },
            sort_keys=True,
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()


@dataclass
class ChainBreak:
    index: int
    method: str
    decision: str
    chain_ok: bool  # prev_hash coincide con el event_hash real de la entrada anterior
    hash_ok: bool    # event_hash coincide con el contenido de la propia entrada


@dataclass
class ChainDiagnosis:
    is_valid: bool
    total_entries: int
    breaks: list[ChainBreak] = field(default_factory=list)

    def summary(self) -> str:
        if self.is_valid:
            return f"Cadena de auditoría íntegra ({self.total_entries} entradas)."

        content_tampered = [b for b in self.breaks if not b.hash_ok]
        chain_only = [b for b in self.breaks if b.hash_ok and not b.chain_ok]
        parts = [f"Cadena rota en {len(self.breaks)} de {self.total_entries} entradas."]
        if content_tampered:
            parts.append(
                f"{len(content_tampered)} con event_hash que NO coincide con su propio "
                "contenido (fuerte indicio de manipulación real del archivo)."
            )
        if chain_only:
            parts.append(
                f"{len(chain_only)} con prev_hash que no coincide pero event_hash propio "
                "íntegro (típico de una condición de carrera entre escritores concurrentes "
                "al mismo archivo, no manipulación)."
            )
        return " ".join(parts)


class AuditLog:
    def __init__(self, path: Path = DEFAULT_AUDIT_LOG_PATH) -> None:
        self.path = path

    @staticmethod
    def _read_last_hash(f) -> str:
        """Asume que `f` ya está posicionado al inicio y bajo lock exclusivo."""
        content = f.read()
        if not content.strip():
            return "genesis"
        last_entry = json.loads(content.strip().splitlines()[-1])
        return last_entry["event_hash"]

    def record(
        self,
        *,
        peer_user: str,
        method: str,
        decision: Decision,
        detail: dict[str, Any] | None = None,
    ) -> AuditEvent:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        event = AuditEvent(peer_user=peer_user, method=method, decision=decision, detail=detail or {})

        # "a+": crea el archivo si no existe; en POSIX, cada write() de un
        # descriptor abierto en modo append va SIEMPRE al final real del
        # archivo (O_APPEND), sin importar dónde haya quedado el cursor
        # tras el seek(0) de lectura de abajo. El lock exclusivo cubre
        # todo el ciclo leer-último-hash + escribir -- sin él, dos
        # conexiones concurrentes (cada una en su propio thread, ver
        # socket_server.py) podrían leer el mismo "último hash" y
        # bifurcar la cadena.
        with open(self.path, "a+", encoding="utf-8") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                f.seek(0)
                event.prev_hash = self._read_last_hash(f)
                event.event_hash = event.compute_hash()
                f.write(json.dumps(asdict(event), sort_keys=True) + "\n")
                f.flush()
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)
        return event

    def tail(self, n: int = 50) -> list[dict]:
        """Últimas `n` entradas (más reciente primero). No valida la cadena."""
        if not self.path.exists():
            return []
        lines = self.path.read_text(encoding="utf-8").strip().splitlines()
        recent = lines[-n:] if n > 0 else lines
        return [json.loads(line) for line in reversed(recent)]

    def verify_chain(self) -> bool:
        return self.diagnose_chain().is_valid

    def diagnose_chain(self) -> ChainDiagnosis:
        if not self.path.exists():
            return ChainDiagnosis(is_valid=True, total_entries=0)

        lines = self.path.read_text(encoding="utf-8").strip().splitlines()
        prev = "genesis"
        breaks: list[ChainBreak] = []

        for i, line in enumerate(lines):
            entry = json.loads(line)

            chain_ok = entry["prev_hash"] == prev
            recomputed = AuditEvent(
                peer_user=entry["peer_user"],
                method=entry["method"],
                decision=entry["decision"],
                detail=entry["detail"],
                timestamp=entry["timestamp"],
                prev_hash=entry["prev_hash"],
            ).compute_hash()
            hash_ok = recomputed == entry["event_hash"]

            if not chain_ok or not hash_ok:
                breaks.append(
                    ChainBreak(
                        index=i, method=entry["method"], decision=entry["decision"],
                        chain_ok=chain_ok, hash_ok=hash_ok,
                    )
                )

            # Avanza con el hash RECLAMADO por la entrada (no el recomputado):
            # si esta entrada fue tampereada, la siguiente debe seguir
            # evaluándose contra lo que el archivo dice que es su hash,
            # para poder seguir detectando rupturas de encadenamiento
            # posteriores de forma independiente de esta.
            prev = entry["event_hash"]

        return ChainDiagnosis(is_valid=not breaks, total_entries=len(lines), breaks=breaks)
