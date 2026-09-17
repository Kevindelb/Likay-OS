"""Tests de likay_broker.client contra un BrokerServer real (mismo patrón que TestEndToEndOverRealSocket)."""
from __future__ import annotations

import os
import pwd
import threading
import time
from pathlib import Path

import pytest

from likay_broker.audit import AuditLog
from likay_broker.client import BrokerClientError, check_capability, register_policy, unregister_policy
from likay_broker.policy_store import AgentGrant, PolicyStore
from likay_broker.socket_server import BrokerServer


def _current_username() -> str:
    return pwd.getpwuid(os.getuid()).pw_name


def _start_server(tmp_path: Path) -> BrokerServer:
    server = BrokerServer(
        socket_path=tmp_path / "broker.sock",
        policy_store=PolicyStore(path=tmp_path / "policy.json"),
        audit_log=AuditLog(path=tmp_path / "audit.log"),
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline and not server._socket_path.exists():
        time.sleep(0.01)
    return server


def test_check_capability_via_client(tmp_path: Path) -> None:
    server = _start_server(tmp_path)
    server._policy_store.upsert_grant(AgentGrant(
        agent_id="com.example.test", linux_user=_current_username(),
        capabilities=["network.egress"], installed_at="2026-09-15T00:00:00Z",
    ))

    assert check_capability(capability="network.egress", socket_path=server._socket_path) is True
    assert check_capability(capability="gpu.compute", socket_path=server._socket_path) is False


def test_register_policy_via_client_as_authorized_peer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    En el test, el peer real es _current_username() (quien corre
    pytest), no likay-agent-install -- para probar el camino
    autorizado sin necesitar esa UID real, se apunta
    _POLICY_WRITER_USER al usuario actual. La lógica de autorización en
    sí (SO_PEERCRED, nunca un campo JSON) ya está cubierta a fondo en
    test_socket_server.py -- esto solo confirma que el CLIENTE arma el
    mensaje correcto y sabe leer una respuesta ALLOW real.
    """
    import likay_broker.socket_server as ss
    monkeypatch.setattr(ss, "_POLICY_WRITER_USER", _current_username())

    server = _start_server(tmp_path)
    register_policy(
        agent_id="com.example.test", linux_user="agent-test",
        capabilities=["network.egress"], socket_path=server._socket_path,
    )

    grant = server._policy_store.get_grant(linux_user="agent-test")
    assert grant is not None
    assert grant.capabilities == ["network.egress"]


def test_register_policy_via_client_as_unauthorized_peer_raises(tmp_path: Path) -> None:
    server = _start_server(tmp_path)
    with pytest.raises(BrokerClientError):
        register_policy(
            agent_id="com.example.test", linux_user="agent-test",
            capabilities=["disk.write"], socket_path=server._socket_path,
        )


def test_unregister_policy_via_client_as_authorized_peer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import likay_broker.socket_server as ss
    monkeypatch.setattr(ss, "_POLICY_WRITER_USER", _current_username())

    server = _start_server(tmp_path)
    server._policy_store.upsert_grant(AgentGrant(
        agent_id="com.example.old", linux_user="agent-old",
        capabilities=["network.egress"], installed_at="2026-09-15T00:00:00Z",
    ))

    removed = unregister_policy(linux_user="agent-old", socket_path=server._socket_path)

    assert removed is True
    assert server._policy_store.get_grant(linux_user="agent-old") is None


def test_unregister_policy_via_client_as_unauthorized_peer_raises(tmp_path: Path) -> None:
    server = _start_server(tmp_path)
    with pytest.raises(BrokerClientError):
        unregister_policy(linux_user="agent-old", socket_path=server._socket_path)
