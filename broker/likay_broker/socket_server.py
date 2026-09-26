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
        max_requests_per_connection: int = 100,
        idle_timeout: float = 30.0,
        max_connections: int = 128,
    ) -> None:
        self._socket_path = socket_path
        self._policy_store = policy_store or PolicyStore()
        self._audit_log = audit_log or AuditLog()
        self._server_sock: socket.socket | None = None
        # Hardening portado de vendor/kal/kernel/api/socket_server.py
        # (hallazgo de revisión de seguridad, 2026-09-17): sin esto, una
        # conexión podía quedar abierta indefinidamente sin mandar nada
        # (ociosa, un thread acaparado para siempre) o mandar un volumen
        # ilimitado de requests en una sola conexión de larga vida --
        # ninguna de las dos cosas fallaba antes, solo no tenían techo.
        # Alcance DISTINTO al de kal a propósito: kal acota
        # max_requests sobre la VIDA ENTERA de un socket efímero
        # (se tira al terminar una ejecución de skill); acá el servidor
        # es un daemon persistente (likay-agent-broker.service), así que
        # el límite natural es POR CONEXIÓN -- un cliente que necesite
        # más simplemente reconecta, no queda bloqueado para siempre.
        self._max_requests_per_connection = max_requests_per_connection
        self._idle_timeout = idle_timeout
        # Hallazgo de la auditoría 2026-09-26: cada conexión aceptada
        # arrancaba un hilo nuevo sin ningún tope -- cualquier usuario
        # local (incluido un agente instalado, el socket es 0666 a
        # propósito) podía abrir conexiones hasta agotar memoria/PIDs del
        # Broker, que no tiene límites de cgroup. Este semáforo acota las
        # conexiones vivas; el que sobra se cierra de inmediato en vez de
        # encolar un hilo más (falla rápido y acotado, nunca crece).
        self._conn_slots = threading.BoundedSemaphore(max_connections)
        self._max_connections = max_connections

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
                if not self._conn_slots.acquire(blocking=False):
                    # Sin cupo: cerrar de inmediato. Nunca se encola un
                    # hilo más allá del tope -- ver _conn_slots en __init__.
                    conn.close()
                    continue
                threading.Thread(target=self._handle_connection, args=(conn,), daemon=True).start()
        finally:
            srv.close()
            if self._socket_path.exists():
                self._socket_path.unlink()

    def _handle_connection(self, conn: socket.socket) -> None:
        """Libera el cupo de conexión pase lo que pase (ver _conn_slots)."""
        try:
            self._handle_connection_locked(conn)
        finally:
            self._conn_slots.release()

    def _handle_connection_locked(self, conn: socket.socket) -> None:
        with conn:
            try:
                pid, uid, gid = _peer_credentials(conn)
            except OSError:
                return  # conexión murió antes de poder leer las credenciales

            peer_user = _username_for_uid(uid) or f"uid:{uid}"

            # idle_timeout se reinicia en cada llamada bloqueante (recv):
            # dispara si esta conexión concreta pasa ese tiempo sin mandar
            # NADA, no acota la vida total de una conexión activa.
            # socket.timeout es un alias de TimeoutError (subclase de
            # OSError) en Python moderno, así que lo captura el except de
            # abajo sin necesitar una rama nueva -- misma "cortar en
            # silencio" que ya usaban los demás errores transitorios.
            conn.settimeout(self._idle_timeout)

            buf = b""
            requests_handled = 0
            try:
                while requests_handled < self._max_requests_per_connection:
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
                        requests_handled += 1
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
        if req.method == "unregister_policy":
            return self._handle_unregister_policy(req, peer_user)

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

    def _handle_unregister_policy(self, req: protocol.Request, peer_user: str) -> str:
        """
        Hallazgo real (2026-09-17): PolicyStore.remove_grant() existía
        desde el diseño original del Broker pero nunca tenía caller --
        v1 solo soporta un agente activo a la vez (ver
        docs/AGENT_INTERFACE.md sección 9), y activate_agent (helper)
        desactiva el agente viejo al instalar uno nuevo, pero nunca
        limpiaba su grant en el Broker ni su usuario Linux -- quedaban
        huérfanos para siempre. Misma frontera de autorización que
        register_policy, mismo motivo exacto (invariante 5/6): solo
        _POLICY_WRITER_USER puede mutar política, nunca un agent_id que
        venga en el JSON.

        Recibe linux_user, no agent_id -- es lo único que el caller
        (agent-install-helper, ver op_activate_agent) tiene a mano en
        ese momento (deriva el nombre de usuario del short_id de la
        unidad systemd que acaba de deshabilitar, nunca vuelve a leer
        el manifiesto viejo). agent_id para el remove_grant() real se
        resuelve acá, vía el propio grant ya guardado.
        """
        if peer_user != _POLICY_WRITER_USER:
            self._audit_log.record(
                peer_user=peer_user, method="unregister_policy", decision="DENY",
                detail={"reason": "peer_not_authorized"},
            )
            return protocol.error_response(
                req.id, protocol.PERMISSION_DENIED,
                "unregister_policy solo lo puede llamar la identidad de instalación",
            )

        linux_user = req.params.get("linux_user")
        if not isinstance(linux_user, str) or not linux_user:
            return protocol.error_response(req.id, protocol.INVALID_PARAMS, "falta 'linux_user'")

        grant = self._policy_store.get_grant(linux_user=linux_user)
        removed = grant is not None
        if grant is not None:
            self._policy_store.remove_grant(agent_id=grant.agent_id)

        self._audit_log.record(
            peer_user=peer_user, method="unregister_policy", decision="ALLOW",
            detail={"linux_user": linux_user, "removed": removed},
        )
        return protocol.success_response(req.id, {"decision": "ALLOW", "removed": removed})
