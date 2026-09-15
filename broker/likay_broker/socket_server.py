"""
Servidor del Broker -- AF_UNIX, JSONL, daemon persistente (a diferencia
de vendor/kal/kernel/api/socket_server.py, que se levanta por-skill y
se tira al terminar; este corre siempre como likay-agent-broker.service).

La pieza de seguridad central de todo este módulo, invariante 6 de
docs/AGENT_INTERFACE.md: la identidad de quien llama NUNCA se toma de
un campo dentro del JSON -- se resuelve leyendo la credencial real del
proceso conectado al socket vía SO_PEERCRED (getsockopt), y esa UID es
la única fuente de verdad de "quién está preguntando". Un proceso no
puede mentir sobre su propia UID a través de un socket Unix -- eso lo
garantiza el kernel al aceptar la conexión, no una validación de
aplicación que un JSON manipulado pudiera sortear.
"""
from __future__ import annotations

import pwd
import socket
import struct
import threading
import time
from pathlib import Path

from likay_broker import protocol
from likay_broker.audit import AuditLog
from likay_broker.policy_store import AgentGrant, PolicyStore

DEFAULT_SOCKET_PATH = Path("/run/likay-agent-broker/broker.sock")

# Mismo límite y mismo motivo que vendor/kal/kernel/api/socket_server.py
# (ver el comentario ahí, hallazgo de la revisión de seguridad
# 2026-07-09): sin esto, una conexión podría mandar bytes sin salto de
# línea indefinidamente y este proceso (de confianza) los acumularía
# sin límite en memoria.
_MAX_LINE_BYTES = 1_048_576

# Único usuario Linux autorizado a mutar política -- invariante 5.
# Hardcodeado, nunca configurable vía manifiesto ni vía argumento de
# la solicitud (invariante 6): si esto fuera un parámetro, cualquier
# JSON manipulado podría intentar cambiarlo.
_POLICY_WRITER_USER = "likay-agent-install"


def _peer_credentials(conn: socket.socket) -> tuple[int, int, int]:
    """
    (pid, uid, gid) del proceso al otro lado de un socket AF_UNIX, vía
    SO_PEERCRED -- Linux-specific (struct ucred: pid_t, uid_t, gid_t,
    los tres 4 bytes en la ABI de Linux para las arquitecturas que
    soporta esta ISO). Esto es lo que el kernel garantiza, no algo que
    el proceso conectado pueda falsear.
    """
    creds = conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
    pid, uid, gid = struct.unpack("3i", creds)
    return pid, uid, gid


def _username_for_uid(uid: int) -> str | None:
    try:
        return pwd.getpwuid(uid).pw_name
    except KeyError:
        return None


class BrokerServer:
    def __init__(
        self,
        *,
        socket_path: Path = DEFAULT_SOCKET_PATH,
        policy_store: PolicyStore | None = None,
        audit_log: AuditLog | None = None,
    ) -> None:
        self._socket_path = socket_path
        self._policy_store = policy_store or PolicyStore()
        self._audit_log = audit_log or AuditLog()
        self._server_sock: socket.socket | None = None

    def serve_forever(self) -> None:
        # En producción, systemd ya crea este directorio (RuntimeDirectory=
        # en likay-agent-broker.service) con el dueño correcto antes de
        # arrancar -- este mkdir es solo defensivo, para poder correr el
        # servidor fuera de systemd (tests, uso manual) sin fallar acá.
        self._socket_path.parent.mkdir(parents=True, exist_ok=True)
        if self._socket_path.exists():
            self._socket_path.unlink()

        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(str(self._socket_path))
        # 0666 + directorio ya restringido por systemd (RuntimeDirectory)
        # sería una opción, pero se prefiere el grupo: cualquier UID
        # puede conectar (check_capability es para "cualquier peer" por
        # diseño, sección 5), la autorización real pasa siempre por
        # SO_PEERCRED después de aceptar, nunca por permisos del socket.
        self._socket_path.chmod(0o666)
        srv.listen(16)
        self._server_sock = srv

        try:
            while True:
                conn, _ = srv.accept()
                threading.Thread(target=self._handle_connection, args=(conn,), daemon=True).start()
        finally:
            srv.close()
            if self._socket_path.exists():
                self._socket_path.unlink()

    def _handle_connection(self, conn: socket.socket) -> None:
        with conn:
            try:
                pid, uid, gid = _peer_credentials(conn)
            except OSError:
                return  # conexión murió antes de poder leer las credenciales

            peer_user = _username_for_uid(uid) or f"uid:{uid}"

            buf = b""
            try:
                while True:
                    chunk = conn.recv(4096)
                    if not chunk:
                        return
                    buf += chunk
                    if len(buf) > _MAX_LINE_BYTES and b"\n" not in buf:
                        return  # protocol.LineTooLongError-equivalente: cortar en silencio
                    while b"\n" in buf:
                        line, buf = buf.split(b"\n", 1)
                        if not line.strip():
                            continue
                        response = self._dispatch_line(line.decode("utf-8", errors="replace"), peer_user)
                        conn.sendall((response + "\n").encode("utf-8"))
            except (ConnectionResetError, BrokenPipeError, OSError):
                return

    def _dispatch_line(self, line: str, peer_user: str) -> str:
        try:
            req = protocol.parse_request(line)
        except protocol.ProtocolError as exc:
            return protocol.error_response(None, protocol.INVALID_PARAMS, str(exc))

        if req.method == "check_capability":
            return self._handle_check_capability(req, peer_user)
        if req.method == "register_policy":
            return self._handle_register_policy(req, peer_user)

        self._audit_log.record(peer_user=peer_user, method=req.method, decision="DENY",
                                detail={"reason": "unknown_method"})
        return protocol.error_response(req.id, protocol.METHOD_NOT_FOUND, f"método desconocido: {req.method}")

    def _handle_check_capability(self, req: protocol.Request, peer_user: str) -> str:
        """
        Cualquier peer puede llamar -- pero solo puede preguntar por SUS
        PROPIAS capacidades. La identidad la da peer_user (ya resuelto
        vía SO_PEERCRED antes de llegar acá), nunca un agent_id que
        venga en req.params -- si params trae uno, se ignora a propósito.
        """
        capability = req.params.get("capability")
        if not isinstance(capability, str) or not capability:
            return protocol.error_response(req.id, protocol.INVALID_PARAMS, "falta 'capability' (string)")

        grant = self._policy_store.get_grant(linux_user=peer_user)
        allowed = grant is not None and capability in grant.capabilities
        decision = "ALLOW" if allowed else "DENY"

        self._audit_log.record(
            peer_user=peer_user, method="check_capability", decision=decision,
            detail={"capability": capability},
        )
        return protocol.success_response(req.id, {"decision": decision})

    def _handle_register_policy(self, req: protocol.Request, peer_user: str) -> str:
        """
        Frontera de autorización DISTINTA a check_capability (invariante
        5/6): solo se acepta si el peer resuelve exactamente a
        _POLICY_WRITER_USER. Ningún agente instalado, corra con la UID
        que corra, puede llamar esto con éxito -- el rechazo es por
        identidad de kernel (SO_PEERCRED), no por una regla de negocio
        que un JSON manipulado pudiera sortear enviando un "agent_id"
        distinto.
        """
        if peer_user != _POLICY_WRITER_USER:
            self._audit_log.record(
                peer_user=peer_user, method="register_policy", decision="DENY",
                detail={"reason": "peer_not_authorized"},
            )
            return protocol.error_response(
                req.id, protocol.PERMISSION_DENIED,
                "register_policy solo lo puede llamar la identidad de instalación",
            )

        agent_id = req.params.get("agent_id")
        linux_user = req.params.get("linux_user")
        capabilities = req.params.get("capabilities")
        if not isinstance(agent_id, str) or not agent_id:
            return protocol.error_response(req.id, protocol.INVALID_PARAMS, "falta 'agent_id'")
        if not isinstance(linux_user, str) or not linux_user:
            return protocol.error_response(req.id, protocol.INVALID_PARAMS, "falta 'linux_user'")
        if not isinstance(capabilities, list) or not all(isinstance(c, str) for c in capabilities):
            return protocol.error_response(req.id, protocol.INVALID_PARAMS, "'capabilities' debe ser lista de strings")

        grant = AgentGrant(
            agent_id=agent_id,
            linux_user=linux_user,
            capabilities=capabilities,
            installed_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        )
        self._policy_store.upsert_grant(grant)

        self._audit_log.record(
            peer_user=peer_user, method="register_policy", decision="ALLOW",
            detail={"agent_id": agent_id, "linux_user": linux_user, "capabilities": capabilities},
        )
        return protocol.success_response(req.id, {"decision": "ALLOW"})
