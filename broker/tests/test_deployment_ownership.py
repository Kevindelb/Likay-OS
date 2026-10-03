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


def test_install_hook_keeps_broker_code_root_owned() -> None:
    """
    Auditoría de seguridad 2026-09-26: /opt/likay-broker es el árbol que
    ejecuta el helper de instalación COMO ROOT (su shebang apunta al venv
    del Broker) y la TUI como likay-agent-install (que tiene pkexec sin
    contraseña). Si queda del usuario sin privilegios likay-broker,
    cualquier escritura lograda como ese usuario se convierte en
    ejecución como root. Debe quedar root:root y no group-writable; el
    chown a likay-broker se limita a su home y a los directorios de
    estado/log declarados en ReadWritePaths=.
    """
    text = INSTALL_HOOK.read_text()
    assert "chown -R root:root /opt/likay-broker" in text
    assert "chmod -R go-w /opt/likay-broker" in text
    # la forma vieja (código y venv del usuario sin privilegios) no debe volver
    assert f"chown -R {BROKER_USER}:{BROKER_USER} /opt/likay-broker " not in text


def test_install_hook_enables_audit_chain_verification_timer() -> None:
    """
    Auditoría 2026-09-26: verify_chain()/diagnose_chain() no tenían ningún
    caller en el sistema instalado. El timer es el que las ejerce.
    """
    text = INSTALL_HOOK.read_text()
    assert "systemctl enable likay-agent-broker-verify.timer" in text


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
