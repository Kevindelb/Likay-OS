"""
Tests de likay_broker.audit -- no requieren red ni QEMU, corren en
cualquier lado. Adaptado del suite real de vendor/kal/tests/test_audit_log.py
(mismo diseño de cadena hash-linked, portado 2026-09-17).
"""
from __future__ import annotations

import json

import pytest

from likay_broker.audit import AuditLog


@pytest.fixture
def log(tmp_path):
    return AuditLog(path=tmp_path / "audit.log")


def _record(log, method="check_capability", decision="ALLOW", peer_user="agent-dummy-agent"):
    return log.record(peer_user=peer_user, method=method, decision=decision, detail={"k": "v"})


def test_empty_log_verifies_true(log):
    assert log.verify_chain() is True


def test_single_event_verifies_true(log):
    _record(log)
    assert log.verify_chain() is True


def test_chain_of_events_verifies_true(log):
    for i in range(5):
        _record(log, method=f"method{i}")
    assert log.verify_chain() is True


def test_events_are_correctly_linked(log):
    e1 = _record(log, method="primero")
    e2 = _record(log, method="segundo")
    assert e1.prev_hash == "genesis"
    assert e2.prev_hash == e1.event_hash


def test_tampering_with_content_is_detected(log):
    """
    Editar un campo de contenido (decision) de una entrada existente SIN
    recalcular su hash debe romper la verificación -- exactamente el
    escenario que le importa a este log: un agente con acceso de
    escritura local intentando cambiar un DENY pasado por un ALLOW.
    """
    _record(log, decision="DENY")
    assert log.verify_chain() is True

    lines = log.path.read_text(encoding="utf-8").splitlines()
    entry = json.loads(lines[0])
    entry["decision"] = "ALLOW"  # contenido alterado, event_hash sin tocar
    log.path.write_text(json.dumps(entry) + "\n", encoding="utf-8")

    assert log.verify_chain() is False


def test_tampering_with_hash_is_detected(log):
    _record(log)
    lines = log.path.read_text(encoding="utf-8").splitlines()
    entry = json.loads(lines[0])
    entry["event_hash"] = "0" * 64
    log.path.write_text(json.dumps(entry) + "\n", encoding="utf-8")

    assert log.verify_chain() is False


def test_deleting_middle_entry_breaks_chain(log):
    _record(log, method="uno")
    _record(log, method="dos")
    _record(log, method="tres")

    lines = log.path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    remaining = [lines[0], lines[2]]
    log.path.write_text("\n".join(remaining) + "\n", encoding="utf-8")

    assert log.verify_chain() is False


def test_reordering_entries_breaks_chain(log):
    _record(log, method="uno")
    _record(log, method="dos")

    lines = log.path.read_text(encoding="utf-8").splitlines()
    swapped = [lines[1], lines[0]]
    log.path.write_text("\n".join(swapped) + "\n", encoding="utf-8")

    assert log.verify_chain() is False


def test_new_instance_reading_existing_log_still_verifies(log):
    """
    Una instancia nueva de AuditLog apuntando al mismo archivo debe
    seguir agregando eventos correctamente encadenados, leyendo el
    último hash desde disco -- no de un caché en memoria.
    """
    _record(log, method="primero")
    _record(log, method="segundo")

    fresh_instance = AuditLog(path=log.path)
    e3 = fresh_instance.record(peer_user="x", method="tercero", decision="ALLOW")

    original_lines = log.path.read_text(encoding="utf-8").splitlines()
    e2_hash = json.loads(original_lines[1])["event_hash"]
    assert e3.prev_hash == e2_hash
    assert fresh_instance.verify_chain() is True


def test_interleaved_writes_from_two_instances_never_break_chain(log):
    """
    Mismo bug real que kal encontró en uso: dos instancias (simulando
    dos threads del socket_server, ver socket_server.py's
    threading.Thread por conexión) escribiendo al mismo archivo
    intercaladamente no deben romper la cadena -- el fix es leer
    siempre el último hash del disco bajo lock exclusivo, nunca de un
    caché en memoria de proceso.
    """
    instance_a = AuditLog(path=log.path)
    instance_b = AuditLog(path=log.path)

    for i in range(20):
        writer = instance_a if i % 2 == 0 else instance_b
        writer.record(peer_user="x", method=f"evento{i}", decision="ALLOW")

    assert instance_a.verify_chain() is True
    assert instance_b.verify_chain() is True
    assert len(instance_a.path.read_text(encoding="utf-8").strip().splitlines()) == 20


def test_diagnose_chain_on_empty_log_is_valid(log):
    diagnosis = log.diagnose_chain()
    assert diagnosis.is_valid is True
    assert diagnosis.total_entries == 0
    assert diagnosis.breaks == []


def test_diagnose_chain_classifies_content_tampering(log):
    _record(log, decision="DENY")

    lines = log.path.read_text(encoding="utf-8").splitlines()
    entry = json.loads(lines[0])
    entry["decision"] = "ALLOW"
    log.path.write_text(json.dumps(entry) + "\n", encoding="utf-8")

    diagnosis = log.diagnose_chain()

    assert diagnosis.is_valid is False
    assert len(diagnosis.breaks) == 1
    assert diagnosis.breaks[0].hash_ok is False
    assert "manipulación" in diagnosis.summary()


def test_diagnose_chain_classifies_race_condition_style_break(log):
    _record(log, method="uno")
    _record(log, method="dos")

    lines = log.path.read_text(encoding="utf-8").splitlines()
    swapped = [lines[1], lines[0]]
    log.path.write_text("\n".join(swapped) + "\n", encoding="utf-8")

    diagnosis = log.diagnose_chain()

    assert diagnosis.is_valid is False
    assert any(b.hash_ok is True and b.chain_ok is False for b in diagnosis.breaks)
    assert "condición de carrera" in diagnosis.summary()
    assert "manipulación real" not in diagnosis.summary()


def test_tail_returns_recent_entries_most_recent_first(log):
    _record(log, method="uno")
    _record(log, method="dos")
    _record(log, method="tres")

    entries = log.tail(2)

    assert [e["method"] for e in entries] == ["tres", "dos"]


def test_tail_on_missing_file_returns_empty_list(tmp_path):
    log = AuditLog(path=tmp_path / "does-not-exist.log")
    assert log.tail() == []


def test_log_file_is_not_world_readable(log):
    """
    Auditoría de seguridad 2026-09-26: sin chmod explícito, audit.log se
    creaba con el umask por defecto de systemd (0022) y quedaba 0644 --
    legible por cualquier usuario local, incluido un agente instalado.
    """
    import os
    import stat

    _record(log)

    mode = stat.S_IMODE(os.stat(log.path).st_mode)
    assert mode == 0o640, f"esperado 0640, obtenido {oct(mode)}"


def test_module_cli_verify_audit_returns_zero_on_intact_chain(log, monkeypatch):
    """
    El subcomando `verify-audit` es el caller que faltaba de
    verify_chain()/diagnose_chain() (auditoría 2026-09-26): ningún
    componente del sistema instalado las invocaba.
    """
    from likay_broker import __main__ as broker_main

    _record(log)
    monkeypatch.setattr(broker_main, "AuditLog", lambda: log)

    assert broker_main.main(["verify-audit"]) == 0


def test_module_cli_verify_audit_returns_nonzero_on_broken_chain(log, monkeypatch, capsys):
    from likay_broker import __main__ as broker_main

    _record(log, method="uno")
    _record(log, method="dos")
    # manipulación: se reescribe el contenido de la primera entrada sin
    # recalcular la cadena (mismo escenario que test_tampering_with_content_is_detected)
    lines = log.path.read_text(encoding="utf-8").splitlines()
    first = json.loads(lines[0])
    first["decision"] = "ALLOW" if first["decision"] != "ALLOW" else "DENY"
    lines[0] = json.dumps(first, sort_keys=True)
    log.path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    monkeypatch.setattr(broker_main, "AuditLog", lambda: log)

    assert broker_main.main(["verify-audit"]) == 1
    assert "rota" in capsys.readouterr().out
