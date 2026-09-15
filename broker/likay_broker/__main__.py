"""
Entry point de likay-agent-broker.service -- ver
iso/config/includes.chroot/etc/systemd/system/likay-agent-broker.service.
"""
from __future__ import annotations

import logging
import sys

from likay_broker.socket_server import DEFAULT_SOCKET_PATH, BrokerServer


def main() -> int:
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
