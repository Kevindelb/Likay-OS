"""Tests de likay_broker.manifest -- sin QEMU, corren en cualquier lado."""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from likay_broker.manifest import ManifestError, parse_manifest_text, validate_requirements_path

VALID_KAL_IN_MANIFEST = textwrap.dedent(
    """\
    schema_version: 1
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
    lifecycle:
      runtime: python-venv
      entry_point: "agent_core.orchestrator:app"
      command: "uvicorn"
      requirements_file: requirements.txt
      port: 8000
      health_check_path: /
      env:
        AGENT_ENV: production
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
    schema_version: 1
    agent:
      id: com.likay.installer
    capabilities: [disk.read, disk.write, partition.manage, bootloader.install]
    sandbox:
      filesystem: restricted
      network: none
      devices: explicit
    """
)


def test_parses_valid_kal_in_manifest() -> None:
    manifest = parse_manifest_text(VALID_KAL_IN_MANIFEST)
    assert manifest.agent_id == "com.likay.kal-in"
    assert manifest.short_id == "kal-in"
    assert "llm.local" in manifest.capabilities
    assert manifest.is_service
    assert manifest.lifecycle["port"] == 8000


def test_installer_manifest_has_no_lifecycle() -> None:
    manifest = parse_manifest_text(VALID_INSTALLER_MANIFEST)
    assert manifest.agent_id == "com.likay.installer"
    assert not manifest.is_service


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
    """Invariante 10 de AGENT_INTERFACE.md: filesystem: full no es legal en v1."""
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
