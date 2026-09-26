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

        Ahora se deriva de agent_id COMPLETO: un sufijo hash de 10 chars
        hex de sha256(agent_id) hace que dos ids distintos no colisionen
        en la práctica (ni siquiera si su forma sanitizada coincidiera,
        porque el hash es sobre el string original, no sobre la forma
        sanitizada). El prefijo humano-legible (último componente,
        truncado) es solo para que los nombres sigan siendo legibles en
        `ps`/`systemctl` -- la unicidad real la da el hash. Reinstalar el
        MISMO agent_id siempre deriva el mismo short_id (idempotente, no
        rompe el caso de reemplazar/actualizar un agente ya instalado).
        """
        digest = hashlib.sha256(self.agent_id.encode("utf-8")).hexdigest()[:10]
        last_component = self.agent_id.rsplit(".", 1)[-1]
        human_prefix = re.sub(r"[^a-z0-9-]", "-", last_component)[:12].strip("-") or "agent"
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

    return AgentManifest(raw=raw)


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
    if requirements_file.startswith("/") or requirements_file.startswith("~"):
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
