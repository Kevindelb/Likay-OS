"""Tests de likay_broker.manifest -- sin QEMU, corren en cualquier lado."""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from likay_broker.manifest import (
    ManifestError,
    parse_manifest_file,
    parse_manifest_text,
    validate_requirements_path,
)

VALID_KAL_IN_MANIFEST = textwrap.dedent(
    """\
    schema_version: 2
    agent:
      id: com.likay.kal-in
      name: "kal-in"
      version: "0.1.0"
      vendor: "Likay-OS project"
    capabilities:
      - network.egress
      - filesystem.data_dir
      - llm.local
      - gpu.compute
      - audio.microphone
      - docker.sandbox
    runtime:
      type: python
      port: 8000
      health_check_path: /
      env:
        AGENT_ENV: production
      python:
        entry_point: "agent_core.orchestrator:app"
        command: "uvicorn"
        requirements_file: requirements.txt
    artifact:
      transport: local-bundle
    storage:
      state: persistent
    sandbox:
      filesystem: restricted
      network: host-egress
      devices: none
      memory_max: "4G"
      cpu_quota: "200%"
      tasks_max: 512
    audit:
      event_prefix: agent_kal-in
    """
)

VALID_INSTALLER_MANIFEST = textwrap.dedent(
    """\
    schema_version: 2
    agent:
      id: com.likay.installer
    capabilities: [disk.read, disk.write, partition.manage, bootloader.install]
    sandbox:
      filesystem: restricted
      network: none
      devices: explicit
    """
)

VALID_OPENCLAW_OCI_MANIFEST = textwrap.dedent(
    """\
    schema_version: 2
    agent:
      id: com.openclaw.gateway
      name: "OpenClaw"
      version: "0.1.0"
    capabilities:
      - network.egress
      - filesystem.data_dir
    runtime:
      type: oci
      port: 8000
      health_check_path: /health
      oci:
        image:
          reference: ghcr.io/openclaw/openclaw
          digest: "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    artifact:
      transport: local-oci-archive
    storage:
      state: persistent
      workspace: persistent
      config: persistent
    secrets:
      - id: OPENAI_API_KEY
        required: true
    sandbox:
      filesystem: restricted
      network: host-egress
      devices: none
    """
)


def test_parses_valid_kal_in_manifest() -> None:
    manifest = parse_manifest_text(VALID_KAL_IN_MANIFEST)
    assert manifest.agent_id == "com.likay.kal-in"
    assert manifest.short_id == "kal-in-bfa07e6eba"
    assert "llm.local" in manifest.capabilities
    assert manifest.is_service
    assert manifest.runtime["port"] == 8000
    assert manifest.runtime["type"] == "python"


def test_short_id_is_deterministic_for_the_same_agent_id() -> None:
    """Reinstalar el mismo agente debe derivar siempre el mismo short_id."""
    a = parse_manifest_text(VALID_KAL_IN_MANIFEST)
    b = parse_manifest_text(VALID_KAL_IN_MANIFEST)
    assert a.short_id == b.short_id


def test_short_id_does_not_collide_on_shared_last_component() -> None:
    """
    Hallazgo I-2 (auditoría 2026-09-26): "com.likay.kal-in" y
    "com.evil.kal-in" comparten el último componente ("kal-in") -- antes
    del fix, ambos derivaban el MISMO short_id (y por lo tanto el mismo
    usuario Linux/unidad/storage/grant). Ahora deben ser distintos.
    """
    likay = parse_manifest_text(VALID_KAL_IN_MANIFEST)
    evil = parse_manifest_text(VALID_KAL_IN_MANIFEST.replace("com.likay.kal-in", "com.evil.kal-in"))
    assert likay.short_id != evil.short_id
    # También el caso más sutil: la forma "puntos->guiones" coincide
    # aunque el agent_id real sea distinto -- el hash igual los separa.
    dotted_differently = parse_manifest_text(
        VALID_KAL_IN_MANIFEST.replace("com.likay.kal-in", "com.likay-kal.in")
    )
    assert likay.short_id != dotted_differently.short_id


def test_installer_manifest_has_no_runtime() -> None:
    manifest = parse_manifest_text(VALID_INSTALLER_MANIFEST)
    assert manifest.agent_id == "com.likay.installer"
    assert not manifest.is_service


def test_parses_valid_oci_manifest() -> None:
    """
    Schema v2 -- runtime.type: oci es solo contrato todavía (el
    Sandbox Adapter real es Fase C, ver docs/AGENT_INTERFACE.md), pero
    tiene que poder declararse y validarse igual que python.
    """
    manifest = parse_manifest_text(VALID_OPENCLAW_OCI_MANIFEST)
    assert manifest.runtime["type"] == "oci"
    assert manifest.runtime["oci"]["image"]["reference"] == "ghcr.io/openclaw/openclaw"
    assert manifest.artifact["transport"] == "local-oci-archive"
    assert manifest.storage["workspace"] == "persistent"
    assert manifest.secrets == [{"id": "OPENAI_API_KEY", "required": True}]


def test_rejects_oci_runtime_without_oci_object() -> None:
    """runtime.type: oci sin runtime.oci -- el oneOf discriminado del schema debe rechazarlo."""
    bad = VALID_OPENCLAW_OCI_MANIFEST.replace(
        "  oci:\n    image:\n      reference: ghcr.io/openclaw/openclaw\n"
        '      digest: "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"\n',
        "",
    )
    with pytest.raises(ManifestError, match="schema"):
        parse_manifest_text(bad)


def test_rejects_oci_image_without_digest() -> None:
    """Invariante 13 (cadena de suministro): un tag mutable no alcanza, el digest es obligatorio."""
    bad = VALID_OPENCLAW_OCI_MANIFEST.replace(
        '      digest: "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"\n',
        "",
    )
    with pytest.raises(ManifestError, match="schema"):
        parse_manifest_text(bad)


def test_rejects_python_runtime_without_python_object() -> None:
    """runtime.type: python sin runtime.python -- mismo oneOf discriminado que oci."""
    bad = VALID_KAL_IN_MANIFEST.replace(
        "  python:\n"
        '    entry_point: "agent_core.orchestrator:app"\n'
        '    command: "uvicorn"\n'
        "    requirements_file: requirements.txt\n",
        "",
    )
    with pytest.raises(ManifestError, match="schema"):
        parse_manifest_text(bad)


def test_rejects_unknown_runtime_type() -> None:
    """node/native no son valores legales en v2 -- deliberado, ver docs/AGENT_INTERFACE.md."""
    bad = VALID_KAL_IN_MANIFEST.replace("type: python", "type: node")
    with pytest.raises(ManifestError, match="schema"):
        parse_manifest_text(bad)


def test_rejects_invalid_yaml() -> None:
    with pytest.raises(ManifestError, match="YAML inválido"):
        parse_manifest_text("agent: [this is not: valid yaml: at all: :::")


def test_rejects_non_mapping_root() -> None:
    with pytest.raises(ManifestError, match="mapa YAML"):
        parse_manifest_text("- just\n- a\n- list\n")


def test_rejects_bad_agent_id_format() -> None:
    bad = VALID_KAL_IN_MANIFEST.replace("id: com.likay.kal-in", "id: not-reverse-dns")
    with pytest.raises(ManifestError, match="reverse-DNS"):
        parse_manifest_text(bad)


def test_rejects_unknown_capability() -> None:
    bad = VALID_KAL_IN_MANIFEST.replace("- network.egress", "- filesystem.full_disk_access")
    with pytest.raises(ManifestError, match="schema"):
        parse_manifest_text(bad)


def test_rejects_filesystem_full_not_a_legal_value() -> None:
    """Invariante 10 de AGENT_INTERFACE.md: filesystem: full no es legal en v2."""
    bad = VALID_KAL_IN_MANIFEST.replace("filesystem: restricted", "filesystem: full")
    with pytest.raises(ManifestError, match="schema"):
        parse_manifest_text(bad)


def test_rejects_bind_host_field_manifest_has_no_authority() -> None:
    """bind_host no es un campo legal -- additionalProperties: false lo rechaza."""
    bad = VALID_KAL_IN_MANIFEST.replace(
        "  port: 8000\n", "  port: 8000\n  bind_host: 0.0.0.0\n"
    )
    with pytest.raises(ManifestError, match="schema"):
        parse_manifest_text(bad)


def test_rejects_requirements_files_plural_list() -> None:
    """El campo es requirements_file (singular) -- una lista no es válida."""
    bad = VALID_KAL_IN_MANIFEST.replace(
        "requirements_file: requirements.txt",
        "requirements_files: [requirements-core.txt, requirements-dev.txt]",
    )
    with pytest.raises(ManifestError, match="schema"):
        parse_manifest_text(bad)


def test_rejects_env_value_with_newline_unit_injection() -> None:
    """
    Hallazgo real (2026-09-17): env no tenía ninguna restricción de
    contenido, y _systemd_unit_text interpola sus valores crudos como
    Environment={k}={v} en la unidad generada. Un valor con '\\n'
    inyecta una línea propia DESPUÉS de User={linux_user} -- la última
    asignación gana, escalando el servicio del agente a root.
    """
    bad = VALID_KAL_IN_MANIFEST.replace(
        "    AGENT_ENV: production\n",
        '    AGENT_ENV: production\n    EVIL: "x\\nUser=root\\n"\n',
    )
    with pytest.raises(ManifestError, match="schema"):
        parse_manifest_text(bad)


def test_rejects_env_key_lowercase() -> None:
    """Las claves de env tampoco tenían restricción -- ver el hallazgo de arriba."""
    bad = VALID_KAL_IN_MANIFEST.replace("    AGENT_ENV: production\n", "    agent_env: production\n")
    with pytest.raises(ManifestError, match="schema"):
        parse_manifest_text(bad)


def test_rejects_command_with_path_traversal() -> None:
    """
    Hallazgo real (2026-09-17): command sin restricción permitía escapar
    del venv (exec_start = f"{venv}/bin/{command} ..."). Un valor como
    '../../../../usr/bin/sh' ejecuta un binario del host como el
    usuario del agente en vez de algo dentro de <venv>/bin/.
    """
    bad = VALID_KAL_IN_MANIFEST.replace(
        'command: "uvicorn"', 'command: "../../../../usr/bin/sh"'
    )
    with pytest.raises(ManifestError, match="schema"):
        parse_manifest_text(bad)


def test_accepts_device_allow_with_legitimate_space() -> None:
    """
    La sintaxis real de systemd's DeviceAllow= es '<device> <permisos>'
    (p.ej. '/dev/sda5 rwm') -- el espacio en el medio es legítimo, el
    fix de abajo NO debe romper esto (solo prohíbe CR/LF, no todo
    whitespace).
    """
    ok = VALID_INSTALLER_MANIFEST.replace(
        "devices: explicit\n", 'devices: explicit\n  device_allow: ["/dev/sda5 rwm"]\n'
    )
    manifest = parse_manifest_text(ok)
    assert manifest.raw["sandbox"]["device_allow"] == ["/dev/sda5 rwm"]


def test_rejects_device_allow_with_newline_unit_injection() -> None:
    """
    Hallazgo real (2026-09-17): mismo vector que env (ver ese test) por
    otro campo -- sandbox.device_allow no tenía ninguna restricción, y
    _systemd_unit_text interpola DeviceAllow={entry} crudo, DESPUÉS de
    User={linux_user} en la plantilla. Más silencioso todavía que el de
    env: la TUI nunca muestra el sandbox del manifiesto, solo
    id/puerto/cantidad de capacidades.
    """
    bad = VALID_INSTALLER_MANIFEST.replace(
        "devices: explicit\n",
        'devices: explicit\n  device_allow: ["char-x\\nUser=root"]\n',
    )
    with pytest.raises(ManifestError, match="schema"):
        parse_manifest_text(bad)


def test_rejects_entry_point_with_whitespace() -> None:
    """
    Hallazgo real (2026-09-17): entry_point sin restricción permitía
    inyectar flags extra después del --host 127.0.0.1 forzado en
    ExecStart (el último flag gana en uvicorn) -- p.ej.
    "app --host 0.0.0.0" expone el agente a la LAN pese a
    sandbox.network: host-egress, contradiciendo la garantía de
    bind_host de docs/AGENT_INTERFACE.md.
    """
    bad = VALID_KAL_IN_MANIFEST.replace(
        'entry_point: "agent_core.orchestrator:app"',
        'entry_point: "agent_core.orchestrator:app --host 0.0.0.0"',
    )
    with pytest.raises(ManifestError, match="schema"):
        parse_manifest_text(bad)


class TestValidateRequirementsPath:
    def test_accepts_file_inside_bundle(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        src.mkdir()
        (src / "requirements.txt").write_text("fastapi\n")

        resolved = validate_requirements_path(src, "requirements.txt")
        assert resolved == (src / "requirements.txt").resolve()

    def test_rejects_absolute_path(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        src.mkdir()
        with pytest.raises(ManifestError, match="absoluta"):
            validate_requirements_path(src, "/etc/passwd")

    def test_rejects_path_traversal(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        src.mkdir()
        (tmp_path / "outside.txt").write_text("evil\n")
        with pytest.raises(ManifestError, match="fuera de src"):
            validate_requirements_path(src, "../outside.txt")

    def test_rejects_symlink_escaping_bundle(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        src.mkdir()
        outside = tmp_path / "outside.txt"
        outside.write_text("evil\n")
        (src / "requirements.txt").symlink_to(outside)

        with pytest.raises(ManifestError, match="fuera de src"):
            validate_requirements_path(src, "requirements.txt")

    def test_rejects_missing_file(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        src.mkdir()
        with pytest.raises(ManifestError, match="no existe"):
            validate_requirements_path(src, "requirements.txt")


class TestParseManifestFile:
    """
    Auditoría de seguridad 2026-09-26: el docstring de parse_manifest_file
    prometía "no sigue el archivo si es un symlink que escapa", pero el
    código usaba path.resolve() (que SÍ sigue symlinks) -- promesa sin
    implementación. Un manifiesto legítimo es siempre un archivo regular
    dentro del staging root-owned.
    """

    def test_accepts_regular_file(self, tmp_path: Path) -> None:
        path = tmp_path / "agent.yaml"
        path.write_text(VALID_KAL_IN_MANIFEST)

        assert parse_manifest_file(path).agent_id == "com.likay.kal-in"

    def test_rejects_symlinked_manifest(self, tmp_path: Path) -> None:
        real = tmp_path / "real.yaml"
        real.write_text(VALID_KAL_IN_MANIFEST)
        link = tmp_path / "agent.yaml"
        link.symlink_to(real)

        with pytest.raises(ManifestError, match="symlink"):
            parse_manifest_file(link)

    def test_rejects_symlink_even_if_target_is_valid(self, tmp_path: Path) -> None:
        """Seguir el enlace permitiría apuntar a cualquier archivo del sistema."""
        outside = tmp_path / "outside.yaml"
        outside.write_text(VALID_KAL_IN_MANIFEST)
        link = tmp_path / "agent.yaml"
        link.symlink_to(outside)

        with pytest.raises(ManifestError, match="symlink"):
            parse_manifest_file(link)
