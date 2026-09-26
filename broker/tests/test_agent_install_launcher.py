"""
Tests de la lógica pura de iso/config/includes.chroot/usr/lib/likay/agent-install-launcher --
solo las funciones que no tocan curses de verdad (nada de stdscr real
acá, eso necesita una tty/QEMU). El archivo no tiene extensión .py
(necesita el shebang del venv del Broker) -- se carga con importlib por
ruta, mismo patrón que test_agent_install_helper.py.
"""
from __future__ import annotations

import importlib.machinery
import importlib.util
from pathlib import Path

LAUNCHER_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "iso" / "config" / "includes.chroot" / "usr" / "lib" / "likay" / "agent-install-launcher"
)


def _load_launcher_module():
    loader = importlib.machinery.SourceFileLoader("agent_install_launcher", str(LAUNCHER_PATH))
    spec = importlib.util.spec_from_file_location("agent_install_launcher", LAUNCHER_PATH, loader=loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def test_format_sandbox_lines_shows_network_and_devices() -> None:
    """
    Hallazgo I-3 (auditoría de seguridad 2026-09-26): la TUI aprobaba
    capacidades una por una pero nunca mostraba el sandbox real -- un
    agente con capabilities: [] podía igual tener sandbox.network:
    host-egress sin que el usuario lo viera antes de instalar.
    """
    launcher = _load_launcher_module()
    lines = launcher._format_sandbox_lines({
        "filesystem": "restricted",
        "network": "host-egress",
        "devices": "explicit",
        "device_allow": ["/dev/dri/renderD128 rw"],
        "memory_max": "2G",
    })

    joined = "\n".join(lines)
    assert "network:    host-egress" in joined
    assert "devices:    explicit" in joined
    assert "/dev/dri/renderD128 rw" in joined
    assert "memory_max: 2G" in joined


def test_format_sandbox_lines_defaults_to_none_when_absent() -> None:
    launcher = _load_launcher_module()
    lines = launcher._format_sandbox_lines({})

    joined = "\n".join(lines)
    assert "network:    none" in joined
    assert "devices:    none" in joined
