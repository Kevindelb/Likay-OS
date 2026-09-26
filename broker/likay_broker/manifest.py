"""
Parseo + validación del manifiesto de un agente (agent.yaml) contra
broker/schema/agent-manifest.schema.json -- ver docs/AGENT_INTERFACE.md.

Este módulo lo usan DOS lados distintos que nunca deben confiar el uno
en el otro (invariante 2 de AGENT_INTERFACE.md): el TUI sin privilegios
(agent-install-launcher, solo para MOSTRAR el manifiesto al usuario) y
el helper privilegiado (agent-install-helper, cuya validación es la
única que cuenta de verdad -- revalida siempre desde cero, nunca
recibe el resultado ya parseado del TUI como si fuera confiable).

El manifiesto es datos, nunca política ejecutable (invariante 3):
parsear un agent.yaml nunca ejecuta código ni interpola nada en un
shell -- yaml.safe_load, no yaml.load ni eval.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import jsonschema
import yaml

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schema" / "agent-manifest.schema.json"

# Estilo reverse-DNS, mismo patrón que el schema -- se repite acá para
# poder dar un mensaje de error específico antes de llegar al genérico
# de jsonschema.
_AGENT_ID_RE = re.compile(r"^[a-z0-9]+(\.[a-z0-9-]+)+$")


class ManifestError(ValueError):
    """El manifiesto no es válido -- nunca se ejecuta nada con él."""


@dataclass(frozen=True)
class AgentManifest:
    """Vista tipada de un manifiesto ya validado contra el schema."""

    raw: dict[str, Any]

    @property
    def agent_id(self) -> str:
        return self.raw["agent"]["id"]

    @property
    def short_id(self) -> str:
        """
        Identificador corto, colisión-resistente, usado para el nombre de
        usuario Linux/unidad systemd/directorio de storage del agente.

        Hallazgo de la auditoría de seguridad (2026-09-26, I-2): antes de
        este fix, short_id era literalmente el ÚLTIMO componente de
        agent.id (p.ej. "com.likay.kal-in" -> "kal-in"). Dos agent.id
        DISTINTOS que comparten ese último componente (p.ej.
        "com.likay.kal-in" y "com.evil.kal-in", o incluso
        "com.likay.kal-in" vs. "com.likay-kal.in", cuya forma
        "puntos->guiones" también coincidiría) derivaban el MISMO usuario
        Linux, la MISMA unidad systemd, el MISMO storage y el MISMO grant
        del Broker -- un bundle malicioso podía suplantar a un agente ya
        instalado con solo elegir el mismo último componente.

        Ahora se deriva de agent_id COMPLETO: un sufijo hash hex de
        sha256(agent_id) hace que dos ids distintos no colisionen en la
        práctica (ni siquiera si su forma sanitizada coincidiera, porque
        el hash es sobre el string original, no sobre la forma
        sanitizada). El prefijo humano-legible (último componente,
        truncado) es solo para que los nombres sigan siendo legibles en
        `ps`/`systemctl` -- la unicidad real la da el hash. Reinstalar el
        MISMO agent_id siempre deriva el mismo short_id (idempotente, no
        rompe el caso de reemplazar/actualizar un agente ya instalado).

        **Re-auditoría de seguridad (2026-09-26, R-4): 10 hex chars (40
        bits) era brute-forceable.** El atacante elige el `agent_id`
        completo libremente (mismo último componente que el agente que
        quiere suplantar) -- encontrar una segunda preimagen en un
        espacio de 40 bits es de ~2^40 evaluaciones de SHA-256, del
        orden de minutos en una sola GPU de gama alta, no un obstáculo
        real. 16 hex chars (64 bits) sube el costo a ~2^64, fuera de
        alcance práctico. El prefijo legible baja a 9 chars (antes 12)
        para que `agent-<prefijo>-<hash>` siga entrando en el límite
        clásico de 32 caracteres de un nombre de usuario Linux:
        `agent-` (6) + 9 + `-` (1) + 16 = 32 exacto.
        """
        digest = hashlib.sha256(self.agent_id.encode("utf-8")).hexdigest()[:16]
        last_component = self.agent_id.rsplit(".", 1)[-1]
        human_prefix = re.sub(r"[^a-z0-9-]", "-", last_component)[:9].strip("-") or "agent"
        return f"{human_prefix}-{digest}"

    @property
    def capabilities(self) -> list[str]:
        return list(self.raw.get("capabilities", []))

    @property
    def runtime(self) -> dict[str, Any]:
        return dict(self.raw.get("runtime", {}))

    @property
    def artifact(self) -> dict[str, Any]:
        return dict(self.raw.get("artifact", {}))

    @property
    def storage(self) -> dict[str, Any]:
        return dict(self.raw.get("storage", {}))

    @property
    def secrets(self) -> list[dict[str, Any]]:
        return list(self.raw.get("secrets", []))

    @property
    def sandbox(self) -> dict[str, Any]:
        return dict(self.raw.get("sandbox", {}))

    @property
    def is_service(self) -> bool:
        """Agente #0 (el instalador) no tiene runtime -- no es un servicio."""
        return bool(self.runtime)


def _load_schema() -> dict[str, Any]:
    with open(SCHEMA_PATH, encoding="utf-8") as f:
        return json.load(f)


def parse_manifest_text(text: str) -> AgentManifest:
    """
    Parsea + valida el contenido crudo de un agent.yaml.

    yaml.safe_load nunca ejecuta código (a diferencia de yaml.load con
    un Loader inseguro) -- el manifiesto es datos, invariante 3.
    """
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ManifestError(f"YAML inválido: {exc}") from exc

    if not isinstance(raw, dict):
        raise ManifestError("El manifiesto debe ser un mapa YAML en el nivel raíz.")

    agent_id = raw.get("agent", {}).get("id") if isinstance(raw.get("agent"), dict) else None
    if isinstance(agent_id, str) and not _AGENT_ID_RE.match(agent_id):
        raise ManifestError(
            f"agent.id {agent_id!r} no tiene forma reverse-DNS "
            "(p.ej. com.vendor.nombre)."
        )

    schema = _load_schema()
    try:
        jsonschema.validate(instance=raw, schema=schema)
    except jsonschema.ValidationError as exc:
        raise ManifestError(f"Manifiesto no cumple el schema: {exc.message}") from exc

    _validate_sandbox_capability_coherence(raw)

    return AgentManifest(raw=raw)


# Capacidades cuya aprobación explícita el usuario ve en la TUI (ver
# agent-install-launcher) implica acceso a dispositivos -- usadas para
# la validación de coherencia de abajo. Del taxonomy completo (ver
# docs/AGENT_INTERFACE.md), estas son las que corresponden a HARDWARE
# concreto vía /dev (incluye disk.read/disk.write -- Agente #0, el
# instalador, es el único caso real de sandbox.devices: explicit hoy, y
# apunta a un nodo de disco, no a GPU/audio/cámara); partition.manage/
# bootloader.install/docker.sandbox/llm.local/filesystem.* no son
# "dispositivos" en este sentido.
_DEVICE_RELATED_CAPABILITIES = frozenset({
    "disk.read", "disk.write", "gpu.compute", "audio.microphone", "audio.speaker", "camera",
})


def _validate_sandbox_capability_coherence(raw: dict[str, Any]) -> None:
    """
    Hallazgo I-3 (auditoría de seguridad 2026-09-26): la TUI le pide al
    usuario aprobar `capabilities:` una por una, pero lo que gobierna el
    sandbox real es `sandbox:` -- un manifiesto podía declarar
    `capabilities: []` (nada aprobado) y aun así `sandbox.network:
    host-egress` (acceso normal a la red del host, sin aprobación
    explícita de network.egress) o `sandbox.devices: explicit` con
    `device_allow` apuntando a hardware real sin ninguna capability de
    dispositivo declarada. El schema por sí solo no puede expresar esta
    relación cruzada entre dos secciones -- se valida acá, en el mismo
    punto por el que pasan TANTO la TUI (para mostrar) COMO el helper
    (para instalar), así que ningún manifiesto incoherente llega a
    generar una unidad real sin que el usuario haya aprobado la
    capacidad que el sandbox realmente otorga.

    Esto es datos, no ejecución (invariante 3): solo compara campos ya
    parseados entre sí, nunca interpreta ni ejecuta nada del manifiesto.
    """
    capabilities = set(raw.get("capabilities", []))
    sandbox = raw.get("sandbox", {}) or {}

    if sandbox.get("network") == "host-egress" and "network.egress" not in capabilities:
        raise ManifestError(
            "sandbox.network: host-egress otorga acceso a la red del host, pero "
            "capabilities no incluye network.egress -- el usuario nunca aprobaría "
            "algo que ni siquiera ve declarado. Declará network.egress en "
            "capabilities, o bajá sandbox.network a 'none'."
        )

    if (
        sandbox.get("devices") == "explicit"
        and sandbox.get("device_allow")
        and not (capabilities & _DEVICE_RELATED_CAPABILITIES)
    ):
        raise ManifestError(
            "sandbox.devices: explicit con device_allow no vacío otorga acceso "
            "a dispositivos del host, pero capabilities no declara ninguna "
            f"capacidad de dispositivo ({', '.join(sorted(_DEVICE_RELATED_CAPABILITIES))}) "
            "-- el usuario nunca aprobaría algo que ni siquiera ve declarado."
        )


def effective_sandbox(sandbox: dict[str, Any], approved_capabilities: set[str]) -> dict[str, Any]:
    """
    Hallazgo R-1 (re-auditoría de seguridad 2026-09-26, sobre I-3):
    _validate_sandbox_capability_coherence (arriba) solo garantiza que
    el MANIFIESTO sea coherente consigo mismo -- nunca conectaba la
    aprobación/denegación REAL del usuario en la TUI con la unidad
    systemd/Quadlet generada. `op_generate_unit()` no recibía la lista
    aprobada en absoluto: denegar `network.egress` en la TUI no le
    sacaba `sandbox.network: host-egress` a la unidad generada -- la
    denegación era cosmética, el agente seguía recibiendo exactamente
    lo que el manifiesto pedía, aprobado o no.

    Esta función deriva el sandbox EFECTIVO -- el que de verdad hay que
    generar -- rebajando lo declarado a lo que `approved_capabilities`
    realmente contiene. Nunca AMPLÍA lo declarado (un manifiesto que
    pide `network: none` sigue con `network: none` aunque se apruebe
    `network.egress` -- aprobar una capacidad nunca es una promesa de
    otorgar más de lo que el manifiesto ya pedía, invariante 3).

    Misma granularidad que la validación de coherencia: `device_allow`
    es una lista plana sin capacidad por entrada, así que "alguna
    capacidad de dispositivo aprobada" habilita la lista COMPLETA, no
    entrada por entrada -- limitación ya aceptada ahí, no nueva acá.
    """
    effective = dict(sandbox)

    if effective.get("network") == "host-egress" and "network.egress" not in approved_capabilities:
        effective["network"] = "none"

    if effective.get("devices") == "explicit" and not (approved_capabilities & _DEVICE_RELATED_CAPABILITIES):
        effective["devices"] = "none"
        effective.pop("device_allow", None)

    return effective


def parse_manifest_file(path: Path) -> AgentManifest:
    """
    Lee y valida un agent.yaml desde disco.

    Rechaza explícitamente el manifiesto si es un symlink. La versión
    anterior documentaba esta protección ("no sigue el archivo si es un
    symlink que escapa de su propio directorio") pero no la implementaba:
    `path.resolve()` SÍ sigue symlinks, así que el docstring prometía algo
    que el código no hacía (auditoría de seguridad 2026-09-26). Un
    manifiesto legítimo es siempre un archivo regular dentro del staging
    root-owned, así que el rechazo es fail-closed y no rompe ningún caso
    real.
    """
    if path.is_symlink():
        raise ManifestError(
            f"El manifiesto {path} es un symlink -- un bundle de terceros no se "
            "considera confiable, y seguirlo permitiría leer otro archivo del sistema."
        )
    if not path.is_file():
        raise ManifestError(f"No existe el manifiesto en {path}")
    return parse_manifest_text(path.read_text(encoding="utf-8"))


def validate_requirements_path(bundle_src_dir: Path, requirements_file: str) -> Path:
    """
    Valida que requirements_file (de runtime.python del manifiesto) resuelva
    a un archivo DENTRO de bundle_src_dir -- nunca una ruta absoluta,
    nunca "..", nunca un symlink que escape del bundle.

    Esto es lo que hace cumplir la restricción documentada en
    AGENT_INTERFACE.md sección 3 ("requirements_file... el helper
    rechaza rutas absolutas, '..', o symlinks que escapen del bundle")
    -- el schema por sí solo (regex "not contains ..") ayuda pero no
    alcanza contra symlinks, por eso se revalida acá con paths reales.
    """
    if requirements_file.startswith(("/", "~")):
        raise ManifestError(f"requirements_file no puede ser una ruta absoluta: {requirements_file!r}")

    candidate = (bundle_src_dir / requirements_file).resolve()
    src_resolved = bundle_src_dir.resolve()

    try:
        candidate.relative_to(src_resolved)
    except ValueError:
        raise ManifestError(
            f"requirements_file {requirements_file!r} resuelve fuera de src/ "
            f"({candidate} no está bajo {src_resolved}) -- posible symlink de escape."
        ) from None

    if not candidate.is_file():
        raise ManifestError(f"requirements_file {requirements_file!r} no existe en el bundle.")

    return candidate
