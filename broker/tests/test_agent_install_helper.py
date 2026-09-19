"""
Tests de la lógica pura de generación de unidades systemd en
iso/config/includes.chroot/usr/lib/likay/agent-install-helper --
específicamente _systemd_unit_text(), la traducción sandbox:/runtime:
del manifiesto a directivas systemd reales (ver la tabla de mapeo en
docs/AGENT_INTERFACE.md sección Sandbox). Es la parte con más superficie
para un bug real (una directiva mal puesta = un agente con más o menos
sandbox del que el manifiesto declaró), así que se testea aislada del
resto del helper (que además necesita mounts/root reales, fuera de
alcance de un test unitario).

El archivo del helper no tiene extensión .py (necesita el shebang
apuntando al venv del Broker para correr de verdad vía pkexec) -- se
carga acá con importlib por ruta.
"""
from __future__ import annotations

import importlib.machinery
import importlib.util
import sys
from pathlib import Path

import pytest

from likay_broker.manifest import AgentManifest

HELPER_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "iso" / "config" / "includes.chroot" / "usr" / "lib" / "likay" / "agent-install-helper"
)


def _load_helper_module():
    # El archivo no tiene extensión .py (a propósito -- necesita el
    # shebang del venv del Broker para correr vía pkexec) --
    # spec_from_file_location no reconoce el loader solo, hay que
    # pasarle un SourceFileLoader explícito.
    loader = importlib.machinery.SourceFileLoader("agent_install_helper", str(HELPER_PATH))
    spec = importlib.util.spec_from_file_location("agent_install_helper", HELPER_PATH, loader=loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules["agent_install_helper"] = module
    loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def helper():
    return _load_helper_module()


_DEFAULT_RUNTIME = {
    "type": "python",
    "port": 8000,
    "python": {"command": "uvicorn", "entry_point": "app:app", "requirements_file": "requirements.txt"},
}


def _manifest(sandbox: dict, runtime: dict | None = None) -> AgentManifest:
    return AgentManifest(raw={
        "schema_version": 2,
        "agent": {"id": "com.example.test-agent"},
        "capabilities": [],
        "runtime": runtime or _DEFAULT_RUNTIME,
        "sandbox": sandbox,
    })


class TestSandboxToSystemdMapping:
    def test_filesystem_restricted_gets_read_write_storage_dirs(self, helper) -> None:
        """
        Storage taxonomy (schema v2): filesystem: restricted expone las
        cuatro carpetas de _agent_paths (config/state/workspace/secrets),
        no un único "data" genérico como en v1.
        """
        manifest = _manifest({"filesystem": "restricted", "network": "none", "devices": "none"})
        unit = helper._systemd_unit_text(manifest, "agent-test-agent")

        assert "ProtectSystem=strict" in unit
        assert "ProtectHome=yes" in unit
        for name in ("config", "state", "workspace", "secrets"):
            assert f"ReadWritePaths=/mnt/likay-agent/test-agent/{name}" in unit

    def test_filesystem_none_has_no_read_write_paths(self, helper) -> None:
        manifest = _manifest({"filesystem": "none", "network": "none", "devices": "none"})
        unit = helper._systemd_unit_text(manifest, "agent-test-agent")

        assert "ReadWritePaths=" not in unit

    def test_filesystem_full_is_rejected(self, helper) -> None:
        manifest = _manifest({"filesystem": "full", "network": "none", "devices": "none"})
        with pytest.raises(helper.HelperError, match="no es un valor legal"):
            helper._systemd_unit_text(manifest, "agent-test-agent")

    def test_network_none_gets_private_network(self, helper) -> None:
        manifest = _manifest({"filesystem": "none", "network": "none", "devices": "none"})
        unit = helper._systemd_unit_text(manifest, "agent-test-agent")

        assert "PrivateNetwork=yes" in unit

    def test_network_host_egress_has_no_private_network(self, helper) -> None:
        manifest = _manifest({"filesystem": "none", "network": "host-egress", "devices": "none"})
        unit = helper._systemd_unit_text(manifest, "agent-test-agent")

        assert "PrivateNetwork=yes" not in unit

    def test_devices_none_gets_private_devices(self, helper) -> None:
        manifest = _manifest({"filesystem": "none", "network": "none", "devices": "none"})
        unit = helper._systemd_unit_text(manifest, "agent-test-agent")

        assert "PrivateDevices=yes" in unit
        assert "DeviceAllow=" not in unit

    def test_devices_explicit_lists_device_allow_entries(self, helper) -> None:
        manifest = _manifest({
            "filesystem": "none", "network": "none", "devices": "explicit",
            "device_allow": ["/dev/dri/renderD128 rw"],
        })
        unit = helper._systemd_unit_text(manifest, "agent-test-agent")

        assert "PrivateDevices=no" in unit
        assert "DevicePolicy=closed" in unit
        assert "DeviceAllow=/dev/dri/renderD128 rw" in unit

    def test_baseline_directives_always_present(self, helper) -> None:
        manifest = _manifest({"filesystem": "none", "network": "none", "devices": "none"})
        unit = helper._systemd_unit_text(manifest, "agent-test-agent")

        for directive in helper._SANDBOX_BASE_DIRECTIVES:
            assert directive in unit

    def test_resource_limits_translated_when_present(self, helper) -> None:
        manifest = _manifest({
            "filesystem": "none", "network": "none", "devices": "none",
            "memory_max": "4G", "cpu_quota": "200%", "tasks_max": 512,
        })
        unit = helper._systemd_unit_text(manifest, "agent-test-agent")

        assert "MemoryMax=4G" in unit
        assert "CPUQuota=200%" in unit
        assert "TasksMax=512" in unit


class TestExecStartAlwaysLoopback:
    """bind_host no existe en el manifiesto -- el generador SIEMPRE fuerza --host 127.0.0.1."""

    def test_execstart_forces_loopback_regardless_of_manifest(self, helper) -> None:
        manifest = _manifest(
            {"filesystem": "none", "network": "host-egress", "devices": "none"},
            runtime={
                "type": "python", "port": 9999,
                "python": {"command": "uvicorn", "entry_point": "app:app", "requirements_file": "requirements.txt"},
            },
        )
        unit = helper._systemd_unit_text(manifest, "agent-test-agent")

        exec_line = next(line for line in unit.splitlines() if line.startswith("ExecStart="))
        assert "--host 127.0.0.1" in exec_line
        assert "--port 9999" in exec_line
        assert "0.0.0.0" not in exec_line

    def test_manifest_cannot_inject_bind_host_because_field_does_not_exist(self, helper) -> None:
        """
        No hay forma de probar 'un manifiesto con bind_host: 0.0.0.0 es
        ignorado' directo, porque ese campo ni siquiera pasa el schema
        (additionalProperties: false, ver test_manifest.py) -- este test
        confirma la otra mitad: que AgentManifest.runtime nunca expone
        un campo bind_host aunque alguien lo agregara a mano al dict raw
        (bypaseando el schema), el generador de unidad ni lo mira.
        """
        manifest = _manifest(
            {"filesystem": "none", "network": "host-egress", "devices": "none"},
            runtime={
                "type": "python", "port": 8000, "bind_host": "0.0.0.0",  # bypass directo del dict, sin pasar por el schema
                "python": {"command": "uvicorn", "entry_point": "app:app", "requirements_file": "requirements.txt"},
            },
        )
        unit = helper._systemd_unit_text(manifest, "agent-test-agent")

        exec_line = next(line for line in unit.splitlines() if line.startswith("ExecStart="))
        assert "0.0.0.0" not in exec_line
        assert "--host 127.0.0.1" in exec_line


class TestEnvironment:
    def test_storage_env_vars_always_set(self, helper) -> None:
        """
        AGENT_CONFIG_DIR/AGENT_STATE_DIR/AGENT_WORKSPACE_DIR/AGENT_SECRETS_DIR
        reemplazan el AGENT_DATA_DIR único de schema v1 -- ver storage
        taxonomy en docs/AGENT_INTERFACE.md.
        """
        manifest = _manifest({"filesystem": "restricted", "network": "none", "devices": "none"})
        unit = helper._systemd_unit_text(manifest, "agent-test-agent")

        assert "Environment=AGENT_CONFIG_DIR=/mnt/likay-agent/test-agent/config" in unit
        assert "Environment=AGENT_STATE_DIR=/mnt/likay-agent/test-agent/state" in unit
        assert "Environment=AGENT_WORKSPACE_DIR=/mnt/likay-agent/test-agent/workspace" in unit
        assert "Environment=AGENT_SECRETS_DIR=/mnt/likay-agent/test-agent/secrets" in unit

    def test_manifest_env_vars_are_included(self, helper) -> None:
        manifest = _manifest(
            {"filesystem": "none", "network": "none", "devices": "none"},
            runtime={
                "type": "python", "port": 8000, "env": {"AGENT_ENV": "production"},
                "python": {"command": "uvicorn", "entry_point": "app:app", "requirements_file": "requirements.txt"},
            },
        )
        unit = helper._systemd_unit_text(manifest, "agent-test-agent")

        assert "Environment=AGENT_ENV=production" in unit


class TestRequireImplementedRuntime:
    """
    Fase A define el contrato para runtime.type == "oci", pero el
    Sandbox Adapter real (Podman/Quadlet) es Fase C -- ver
    docs/AGENT_INTERFACE.md. _require_implemented_runtime es la guarda
    que hace fallar explícito create_agent/install_bundle/generate_unit
    ante un manifiesto oci válido, en vez de un traceback confuso
    intentando leer runtime.python inexistente.
    """

    def test_python_runtime_is_implemented(self, helper) -> None:
        manifest = _manifest({"filesystem": "none", "network": "none", "devices": "none"})
        assert helper._require_implemented_runtime(manifest) == "python"

    def test_oci_runtime_raises_not_implemented(self, helper) -> None:
        manifest = _manifest(
            {"filesystem": "none", "network": "none", "devices": "none"},
            runtime={"type": "oci", "oci": {"image": {"reference": "ghcr.io/x/y", "digest": "sha256:" + "0" * 64}}},
        )
        with pytest.raises(helper.HelperError, match="todavía no está implementado"):
            helper._require_implemented_runtime(manifest)
