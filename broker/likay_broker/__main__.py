"""
Entry point de likay-agent-broker.service -- ver
iso/config/includes.chroot/etc/systemd/system/likay-agent-broker.service.

Además del daemon, expone el subcomando `verify-audit`, que es lo que
ejecuta likay-agent-broker-verify.service (timer diario) para verificar
la cadena hash-linked del log de auditoría -- ver _verify_audit().
"""
from __future__ import annotations

import logging
import sys

from likay_broker.audit import AuditLog
from likay_broker.socket_server import DEFAULT_SOCKET_PATH, BrokerServer


def _verify_audit() -> int:
    """
    Subcomando `verify-audit`: recorre la cadena hash-linked del log de
    auditoría y devuelve 0 si está íntegra, 1 si no.

    Hallazgo de la auditoría de seguridad (2026-09-26): `verify_chain()` /
    `diagnose_chain()` existen desde el diseño original pero NINGÚN
    componente del sistema instalado las llamaba -- los únicos callers
    estaban en los tests, así que la propiedad de "manipulación evidente"
    que promete docs/AGENT_INTERFACE.md sección 10 quedaba dormida en la
    práctica. Este subcomando es el caller que faltaba.
    """
    diagnosis = AuditLog().diagnose_chain()
    print(diagnosis.summary())
    for chain_break in diagnosis.breaks:
        print(
            f"  entrada #{chain_break.index}: method={chain_break.method} "
            f"decision={chain_break.decision} chain_ok={chain_break.chain_ok} "
            f"hash_ok={chain_break.hash_ok}",
            file=sys.stderr,
        )
    return 0 if diagnosis.is_valid else 1


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["verify-audit"]:
        return _verify_audit()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s likay-agent-broker %(levelname)s %(message)s",
        stream=sys.stdout,
    )
    logging.info("arrancando -- socket en %s", DEFAULT_SOCKET_PATH)
    BrokerServer().serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
