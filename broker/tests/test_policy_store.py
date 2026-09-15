"""Tests de likay_broker.policy_store -- sin QEMU, corren en cualquier lado."""
from __future__ import annotations

from pathlib import Path

from likay_broker.policy_store import AgentGrant, PolicyStore


def _grant(agent_id: str = "com.likay.kal-in", linux_user: str = "agent-kal-in") -> AgentGrant:
    return AgentGrant(
        agent_id=agent_id,
        linux_user=linux_user,
        capabilities=["network.egress", "llm.local"],
        installed_at="2026-09-15T12:00:00Z",
    )


def test_load_all_empty_when_file_missing(tmp_path: Path) -> None:
    store = PolicyStore(path=tmp_path / "policy.json")
    assert store.load_all() == []


def test_upsert_then_get_grant(tmp_path: Path) -> None:
    store = PolicyStore(path=tmp_path / "policy.json")
    store.upsert_grant(_grant())

    grant = store.get_grant(linux_user="agent-kal-in")
    assert grant is not None
    assert grant.agent_id == "com.likay.kal-in"
    assert grant.capabilities == ["network.egress", "llm.local"]


def test_get_grant_returns_none_for_unknown_user(tmp_path: Path) -> None:
    store = PolicyStore(path=tmp_path / "policy.json")
    store.upsert_grant(_grant())

    assert store.get_grant(linux_user="agent-something-else") is None


def test_get_grant_never_matches_by_agent_id_alone() -> None:
    """
    Regresión explícita del punto que el usuario marcó como bloqueante:
    la búsqueda para check_capability tiene que ser por linux_user
    (resuelto vía SO_PEERCRED por el caller), nunca por un string
    llamado agent_id que alguien pudiera enviar sin control.
    """
    grant = _grant(agent_id="com.likay.kal-in", linux_user="agent-kal-in")
    # Si alguien buscara por agent_id en vez de linux_user, esto
    # encontraría el grant -- confirmamos que get_grant no acepta ese
    # parámetro en absoluto (TypeError si se intentara).
    import inspect

    from likay_broker.policy_store import PolicyStore as PS

    params = inspect.signature(PS.get_grant).parameters
    assert "agent_id" not in params
    assert "linux_user" in params
    del grant  # solo para dejar explícito qué NO se usa acá


def test_upsert_replaces_existing_grant_for_same_agent(tmp_path: Path) -> None:
    store = PolicyStore(path=tmp_path / "policy.json")
    store.upsert_grant(_grant(linux_user="agent-kal-in"))
    store.upsert_grant(AgentGrant(
        agent_id="com.likay.kal-in",
        linux_user="agent-kal-in",
        capabilities=["gpu.compute"],
        installed_at="2026-09-16T00:00:00Z",
    ))

    all_grants = store.load_all()
    assert len(all_grants) == 1
    assert all_grants[0].capabilities == ["gpu.compute"]


def test_upsert_two_different_agents_both_persist(tmp_path: Path) -> None:
    store = PolicyStore(path=tmp_path / "policy.json")
    store.upsert_grant(_grant(agent_id="com.likay.kal-in", linux_user="agent-kal-in"))
    store.upsert_grant(_grant(agent_id="com.example.dummy", linux_user="agent-dummy"))

    assert len(store.load_all()) == 2
    assert store.get_grant(linux_user="agent-kal-in") is not None
    assert store.get_grant(linux_user="agent-dummy") is not None


def test_remove_grant(tmp_path: Path) -> None:
    store = PolicyStore(path=tmp_path / "policy.json")
    store.upsert_grant(_grant())
    store.remove_grant(agent_id="com.likay.kal-in")

    assert store.load_all() == []


def test_write_is_atomic_no_tmp_file_left_behind(tmp_path: Path) -> None:
    store = PolicyStore(path=tmp_path / "policy.json")
    store.upsert_grant(_grant())

    leftovers = list(tmp_path.glob(".policy-*"))
    assert leftovers == []
    assert (tmp_path / "policy.json").exists()
