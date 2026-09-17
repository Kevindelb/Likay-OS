"""
Verifica que el hook de build que instala el Broker
(iso/config/hooks/0330-install-broker.chroot) efectivamente deja
/var/lib/likay-agent-broker/ y /var/log/likay-agent-broker/ como
propiedad de likay-broker, y que eso coincide con lo que
likay-agent-broker.service espera (User=/ReadWritePaths=) y con los
paths por default que el propio código Python usa
(policy_store.DEFAULT_POLICY_PATH, audit.DEFAULT_AUDIT_LOG_PATH).

No corre como root (no puede -- CI corre sin privilegios) y no toca el
filesystem real /var/lib/likay-agent-broker de la máquina que ejecuta
los tests: es una prueba de CONSISTENCIA entre los tres artefactos de
build/deploy, no una aserción sobre ownership real en disco -- eso lo
garantiza systemd (User=) en el sistema instalado, nunca verificable
desde acá.
"""
from __future__ import annotations

from pathlib import Path

from likay_broker.audit import DEFAULT_AUDIT_LOG_PATH
from likay_broker.policy_store import DEFAULT_POLICY_PATH

REPO_ROOT = Path(__file__).resolve().parents[2]
INSTALL_HOOK = REPO_ROOT / "iso/config/hooks/0330-install-broker.chroot"
SERVICE_UNIT = REPO_ROOT / "iso/config/includes.chroot/etc/systemd/system/likay-agent-broker.service"

BROKER_USER = "likay-broker"


def test_install_hook_chowns_state_and_log_dirs_to_broker_user() -> None:
    text = INSTALL_HOOK.read_text()
    assert str(DEFAULT_POLICY_PATH.parent) in text
    assert str(DEFAULT_AUDIT_LOG_PATH.parent) in text
    assert f"chown -R {BROKER_USER}:{BROKER_USER}" in text


def test_service_unit_runs_as_broker_user() -> None:
    text = SERVICE_UNIT.read_text()
    assert f"User={BROKER_USER}" in text
    assert f"Group={BROKER_USER}" in text


def test_service_unit_readwrite_paths_match_default_state_and_log_dirs() -> None:
    text = SERVICE_UNIT.read_text()
    read_write_line = next(line for line in text.splitlines() if line.startswith("ReadWritePaths="))
    declared_paths = read_write_line.removeprefix("ReadWritePaths=").split()

    assert str(DEFAULT_POLICY_PATH.parent) in declared_paths
    assert str(DEFAULT_AUDIT_LOG_PATH.parent) in declared_paths
