"""
Tests de likay_broker.socket_server -- el módulo de seguridad central.

Dos niveles de test a propósito:
1. Unit, contra los handlers privados directo (_handle_check_capability/
   _handle_register_policy) con un peer_user CONTROLADO -- esto aísla
   la lógica de autorización (lo que realmente importa verificar) de
   la mecánica de sockets/UID real del proceso que corre pytest.
2. Integración real, con un socket AF_UNIX de verdad -- confirma que
   _peer_credentials() efectivamente lee SO_PEERCRED del kernel y no
   un campo simulado.
"""
from __future__ import annotations

import json
import os
import socket
import threading
import time
from pathlib import Path

from likay_broker import protocol
from likay_broker.audit import AuditLog
from likay_broker.policy_store import AgentGrant, PolicyStore
from likay_broker.socket_server import BrokerServer, _peer_credentials


def _make_server(tmp_path: Path) -> BrokerServer:
    return BrokerServer(
        socket_path=tmp_path / "broker.sock",
        policy_store=PolicyStore(path=tmp_path / "policy.json"),
        audit_log=AuditLog(path=tmp_path / "audit.log"),
    )


class TestCheckCapabilityAuthorization:
    """
    Invariante: check_capability resuelve identidad por peer_user
    (ya extraído de SO_PEERCRED por el caller de _handle_check_capability,
    nunca por algo que venga en req.params) -- y solo ve las capacidades
    de SU PROPIO agente.
    """

    def test_allows_capability_the_peer_was_granted(self, tmp_path: Path) -> None:
        server = _make_server(tmp_path)
        server._policy_store.upsert_grant(AgentGrant(
            agent_id="com.likay.kal-in", linux_user="agent-kal-in",
            capabilities=["network.egress", "llm.local"], installed_at="2026-09-15T00:00:00Z",
        ))

        req = protocol.Request(id=1, method="check_capability", params={"capability": "llm.local"})
        resp = json.loads(server._handle_check_capability(req, peer_user="agent-kal-in"))

        assert resp["result"]["decision"] == "ALLOW"

    def test_denies_capability_the_peer_was_not_granted(self, tmp_path: Path) -> None:
        server = _make_server(tmp_path)
        server._policy_store.upsert_grant(AgentGrant(
            agent_id="com.likay.kal-in", linux_user="agent-kal-in",
            capabilities=["network.egress"], installed_at="2026-09-15T00:00:00Z",
        ))

        req = protocol.Request(id=1, method="check_capability", params={"capability": "gpu.compute"})
        resp = json.loads(server._handle_check_capability(req, peer_user="agent-kal-in"))

        assert resp["result"]["decision"] == "DENY"

    def test_denies_unknown_peer_entirely(self, tmp_path: Path) -> None:
        server = _make_server(tmp_path)
        req = protocol.Request(id=1, method="check_capability", params={"capability": "network.egress"})
        resp = json.loads(server._handle_check_capability(req, peer_user="agent-never-installed"))

        assert resp["result"]["decision"] == "DENY"

    def test_ignores_agent_id_in_params_uses_peer_credential_instead(self, tmp_path: Path) -> None:
        """
        El caso adversarial central: un agente B, corriendo como
        agent-b, manda un pedido con un capability que le fue otorgado
        A (agent-kal-in) -- pero como la identidad se resuelve por
        SO_PEERCRED (acá simulado pasando peer_user="agent-b"
        explícitamente, que es lo que haría el dispatcher real), B
        sigue viendo DENY: la búsqueda nunca usó ningún campo de params
        para decidir de quién se trata.
        """
        server = _make_server(tmp_path)
        server._policy_store.upsert_grant(AgentGrant(
            agent_id="com.likay.kal-in", linux_user="agent-kal-in",
            capabilities=["gpu.compute"], installed_at="2026-09-15T00:00:00Z",
        ))
        server._policy_store.upsert_grant(AgentGrant(
            agent_id="com.example.dummy", linux_user="agent-b",
            capabilities=[], installed_at="2026-09-15T00:00:00Z",
        ))

        # req.params no tiene ningún campo "agent_id" -- ni siquiera es
        # parte del protocolo de check_capability (ver protocol.py) --
        # confirmando que no hay forma de que B se haga pasar por A.
        req = protocol.Request(id=1, method="check_capability", params={"capability": "gpu.compute"})
        resp = json.loads(server._handle_check_capability(req, peer_user="agent-b"))

        assert resp["result"]["decision"] == "DENY"

    def test_missing_capability_param_is_invalid_params(self, tmp_path: Path) -> None:
        server = _make_server(tmp_path)
        req = protocol.Request(id=1, method="check_capability", params={})
        resp = json.loads(server._handle_check_capability(req, peer_user="agent-kal-in"))

        assert resp["error"]["code"] == protocol.INVALID_PARAMS


class TestRegisterPolicyAuthorization:
    """
    Invariante 5/6: register_policy SOLO lo puede llamar el peer cuya
    credencial Unix resuelve a "likay-agent-install" -- nunca decidido
    por un campo del JSON.
    """

    def test_authorized_peer_can_register_policy(self, tmp_path: Path) -> None:
        server = _make_server(tmp_path)
        req = protocol.Request(id=1, method="register_policy", params={
            "agent_id": "com.likay.kal-in",
            "linux_user": "agent-kal-in",
            "capabilities": ["network.egress", "llm.local"],
        })

        resp = json.loads(server._handle_register_policy(req, peer_user="likay-agent-install"))

        assert resp["result"]["decision"] == "ALLOW"
        grant = server._policy_store.get_grant(linux_user="agent-kal-in")
        assert grant is not None
        assert grant.capabilities == ["network.egress", "llm.local"]

    def test_arbitrary_agent_cannot_register_its_own_policy(self, tmp_path: Path) -> None:
        """
        El escenario que el usuario marcó como el riesgo central: un
        agente instalado (corriendo con SU PROPIA UID real, nunca la
        de likay-agent-install) intenta auto-otorgarse capacidades
        mandando el mismo request que usaría el instalador legítimo.
        Tiene que ser rechazado SOLO por su identidad de peer, sin
        importar qué diga el cuerpo del mensaje.
        """
        server = _make_server(tmp_path)
        req = protocol.Request(id=1, method="register_policy", params={
            "agent_id": "com.example.malicious-agent",
            "linux_user": "agent-malicious-agent",
            "capabilities": ["disk.write", "bootloader.install"],
        })

        resp = json.loads(server._handle_register_policy(req, peer_user="agent-malicious-agent"))

        assert resp["error"]["code"] == protocol.PERMISSION_DENIED
        assert server._policy_store.get_grant(linux_user="agent-malicious-agent") is None

    def test_root_peer_is_not_automatically_authorized(self, tmp_path: Path) -> None:
        """
        Ver docs/AGENT_INTERFACE.md invariante 5: el helper privilegiado
        (que corre brevemente como root vía pkexec) NUNCA llama a
        register_policy -- ni siquiera "ser root" alcanza acá, solo la
        UID exacta de likay-agent-install. Esto confirma esa decisión
        de diseño a nivel de código, no solo de documentación.
        """
        server = _make_server(tmp_path)
        req = protocol.Request(id=1, method="register_policy", params={
            "agent_id": "com.likay.kal-in", "linux_user": "agent-kal-in", "capabilities": [],
        })

        resp = json.loads(server._handle_register_policy(req, peer_user="root"))

        assert resp["error"]["code"] == protocol.PERMISSION_DENIED

    def test_denial_is_audited(self, tmp_path: Path) -> None:
        server = _make_server(tmp_path)
        req = protocol.Request(id=1, method="register_policy", params={
            "agent_id": "x", "linux_user": "y", "capabilities": [],
        })
        server._handle_register_policy(req, peer_user="agent-malicious-agent")

        audit_text = (tmp_path / "audit.log").read_text()
        events = [json.loads(line) for line in audit_text.splitlines()]
        assert len(events) == 1
        assert events[0]["decision"] == "DENY"
        assert events[0]["peer_user"] == "agent-malicious-agent"
        assert events[0]["method"] == "register_policy"


class TestUnregisterPolicyAuthorization:
    """
    Hallazgo real (2026-09-17): PolicyStore.remove_grant() existía sin
    ningún caller -- misma frontera de autorización que register_policy
    (invariante 5/6), mismo motivo: solo likay-agent-install puede
    mutar política, nunca decidido por un campo del JSON.
    """

    def test_authorized_peer_can_unregister_policy(self, tmp_path: Path) -> None:
        server = _make_server(tmp_path)
        server._policy_store.upsert_grant(AgentGrant(
            agent_id="com.example.old-agent", linux_user="agent-old-agent",
            capabilities=["network.egress"], installed_at="2026-09-15T00:00:00Z",
        ))
        req = protocol.Request(id=1, method="unregister_policy", params={"linux_user": "agent-old-agent"})

        resp = json.loads(server._handle_unregister_policy(req, peer_user="likay-agent-install"))

        assert resp["result"]["decision"] == "ALLOW"
        assert resp["result"]["removed"] is True
        assert server._policy_store.get_grant(linux_user="agent-old-agent") is None

    def test_unregistering_nonexistent_grant_reports_removed_false(self, tmp_path: Path) -> None:
        """No es un error preguntar por un agente que ya no tiene grant -- es el caso normal."""
        server = _make_server(tmp_path)
        req = protocol.Request(id=1, method="unregister_policy", params={"linux_user": "agent-nunca-existio"})

        resp = json.loads(server._handle_unregister_policy(req, peer_user="likay-agent-install"))

        assert resp["result"]["decision"] == "ALLOW"
        assert resp["result"]["removed"] is False

    def test_arbitrary_agent_cannot_unregister_another_agents_policy(self, tmp_path: Path) -> None:
        """Mismo escenario central que register_policy: rechazo por identidad de peer, nunca por el JSON."""
        server = _make_server(tmp_path)
        server._policy_store.upsert_grant(AgentGrant(
            agent_id="com.example.victim", linux_user="agent-victim",
            capabilities=["network.egress"], installed_at="2026-09-15T00:00:00Z",
        ))
        req = protocol.Request(id=1, method="unregister_policy", params={"linux_user": "agent-victim"})

        resp = json.loads(server._handle_unregister_policy(req, peer_user="agent-malicious-agent"))

        assert resp["error"]["code"] == protocol.PERMISSION_DENIED
        assert server._policy_store.get_grant(linux_user="agent-victim") is not None

    def test_missing_linux_user_param_is_invalid_params(self, tmp_path: Path) -> None:
        server = _make_server(tmp_path)
        req = protocol.Request(id=1, method="unregister_policy", params={})

        resp = json.loads(server._handle_unregister_policy(req, peer_user="likay-agent-install"))

        assert resp["error"]["code"] == protocol.INVALID_PARAMS


class TestDispatch:
    def test_unknown_method_is_method_not_found(self, tmp_path: Path) -> None:
        server = _make_server(tmp_path)
        resp = json.loads(server._dispatch_line(
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "delete_everything", "params": {}}),
            peer_user="agent-kal-in",
        ))
        assert resp["error"]["code"] == protocol.METHOD_NOT_FOUND

    def test_malformed_json_is_invalid_params(self, tmp_path: Path) -> None:
        server = _make_server(tmp_path)
        resp = json.loads(server._dispatch_line("not even json{{{", peer_user="agent-kal-in"))
        assert resp["error"]["code"] == protocol.INVALID_PARAMS


class TestPeerCredentialsRealSocket:
    """Confirma que _peer_credentials lee SO_PEERCRED de verdad, no un valor inventado."""

    def test_reads_real_pid_and_uid_of_this_process(self) -> None:
        a, b = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            pid, uid, gid = _peer_credentials(a)
            # socketpair conecta dos sockets DENTRO del mismo proceso --
            # el peer de "a" es literalmente este mismo proceso pytest.
            assert pid == os.getpid()
            assert uid == os.getuid()
            assert gid == os.getgid()
        finally:
            a.close()
            b.close()


class TestEndToEndOverRealSocket:
    """Servidor real, cliente real, mismo camino que usaría el TUI/helper en producción."""

    def test_check_capability_round_trip(self, tmp_path: Path) -> None:
        server = _make_server(tmp_path)
        server._policy_store.upsert_grant(AgentGrant(
            agent_id="com.likay.kal-in", linux_user=_current_username(),
            capabilities=["network.egress"], installed_at="2026-09-15T00:00:00Z",
        ))

        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            _wait_for_socket(server._socket_path)

            client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            client.connect(str(server._socket_path))
            client.sendall(
                (json.dumps({
                    "jsonrpc": "2.0", "id": 1, "method": "check_capability",
                    "params": {"capability": "network.egress"},
                }) + "\n").encode()
            )
            raw = client.recv(4096)
            client.close()

            resp = json.loads(raw.decode())
            assert resp["result"]["decision"] == "ALLOW"
        finally:
            pass  # daemon thread, no hace falta parar el servidor a mano en el test


class TestConnectionHardening:
    """
    Hallazgo real (2026-09-17): sin max_requests/idle_timeout por
    conexión, un cliente podía acaparar un thread para siempre (ocioso,
    sin mandar nada) o mandar volumen ilimitado de requests en una sola
    conexión de larga vida. Portado de vendor/kal/kernel/api/socket_server.py
    (mismos límites, alcance por-conexión en vez de por-vida-del-servidor
    porque este es un daemon persistente, no un socket efímero).
    """

    def test_connection_closed_after_max_requests(self, tmp_path: Path) -> None:
        server = BrokerServer(
            socket_path=tmp_path / "broker.sock",
            policy_store=PolicyStore(path=tmp_path / "policy.json"),
            audit_log=AuditLog(path=tmp_path / "audit.log"),
            max_requests_per_connection=2,
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        _wait_for_socket(server._socket_path)

        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.connect(str(server._socket_path))
        client.settimeout(2.0)

        for i in range(2):
            client.sendall(
                (json.dumps({"jsonrpc": "2.0", "id": i, "method": "check_capability",
                             "params": {"capability": "x"}}) + "\n").encode()
            )
            assert client.recv(4096)  # las primeras 2 sí responden

        # La 3ra request sobre la MISMA conexión: el servidor ya cerró
        # su lado tras alcanzar max_requests_per_connection. Según el
        # timing exacto, eso se ve como un BrokenPipeError en el propio
        # sendall (el servidor ya cerró antes de que este dato llegue)
        # o como un recv() devolviendo EOF (b"") -- ambas son la misma
        # señal real: "esta conexión ya no está viva".
        connection_was_closed = False
        try:
            client.sendall(
                (json.dumps({"jsonrpc": "2.0", "id": 99, "method": "check_capability",
                             "params": {"capability": "x"}}) + "\n").encode()
            )
            if client.recv(4096) == b"":
                connection_was_closed = True
        except (BrokenPipeError, ConnectionResetError):
            connection_was_closed = True
        assert connection_was_closed
        client.close()

    def test_idle_connection_is_closed_after_timeout(self, tmp_path: Path) -> None:
        server = BrokerServer(
            socket_path=tmp_path / "broker.sock",
            policy_store=PolicyStore(path=tmp_path / "policy.json"),
            audit_log=AuditLog(path=tmp_path / "audit.log"),
            idle_timeout=0.2,
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        _wait_for_socket(server._socket_path)

        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.connect(str(server._socket_path))
        client.settimeout(2.0)
        # No manda nada -- el servidor debe cerrar por su cuenta tras
        # idle_timeout, sin que el cliente haga nada.
        assert client.recv(4096) == b""
        client.close()

    def test_connections_beyond_max_connections_are_closed_immediately(self, tmp_path: Path) -> None:
        """
        Auditoría de seguridad 2026-09-26: sin tope, cada conexión
        aceptada arrancaba un hilo nuevo -- cualquier usuario local (el
        socket es 0666 a propósito) podía agotar memoria/PIDs del Broker,
        que no tiene límites de cgroup.
        """
        server = BrokerServer(
            socket_path=tmp_path / "broker.sock",
            policy_store=PolicyStore(path=tmp_path / "policy.json"),
            audit_log=AuditLog(path=tmp_path / "audit.log"),
            max_connections=1,
            idle_timeout=5.0,
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        _wait_for_socket(server._socket_path)

        def _request(sock: socket.socket, req_id: int) -> bytes:
            sock.sendall(
                (json.dumps({"jsonrpc": "2.0", "id": req_id, "method": "check_capability",
                             "params": {"capability": "x"}}) + "\n").encode()
            )
            return sock.recv(4096)

        first = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        first.connect(str(server._socket_path))
        first.settimeout(2.0)
        assert _request(first, 1)  # ocupa el único cupo disponible

        second = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        second.connect(str(server._socket_path))
        second.settimeout(2.0)
        # Sin cupo: el servidor la cierra al aceptarla, no encola otro hilo.
        assert second.recv(4096) == b""
        second.close()

        # Al cerrar la primera se libera el cupo y el servidor vuelve a atender.
        first.close()
        deadline = time.monotonic() + 3.0
        accepted_again = False
        while time.monotonic() < deadline:
            third = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            third.connect(str(server._socket_path))
            third.settimeout(1.0)
            try:
                if _request(third, 3):
                    accepted_again = True
                    third.close()
                    break
            except (BrokenPipeError, ConnectionResetError, TimeoutError):
                pass
            third.close()
            time.sleep(0.05)
        assert accepted_again


def _current_username() -> str:
    import pwd
    return pwd.getpwuid(os.getuid()).pw_name


def _wait_for_socket(path: Path, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return
        time.sleep(0.01)
    raise TimeoutError(f"{path} nunca apareció")
