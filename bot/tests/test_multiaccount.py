import sqlite3
from pathlib import Path

import pytest

from app.bindings_storage import Binding, BindingsStorage


def bind(user: int, tag: str) -> Binding:
    return Binding(user, -1001, tag, None, "Player", "2026-11-05")


def test_alt_accounts_and_primary_switch(tmp_path):
    repo = BindingsStorage(str(tmp_path / "bind.db"))
    repo.upsert_binding(bind(1, "#AAA"))
    repo.upsert_binding(bind(1, "#BBB"))
    assert repo.get_binding(-1001, 1).coc_player_tag == "#AAA"
    assert [x.coc_player_tag for x in repo.get_user_accounts(-1001, 1)] == ["#AAA","#BBB"]
    assert repo.set_primary_account(-1001, 1, "#BBB")
    assert repo.get_binding(-1001, 1).coc_player_tag == "#BBB"
    assert repo.get_user_id_by_tag(-1001, "#AAA") == 1
    assert len(repo.get_bindings_for_tags(-1001, ["#AAA","#BBB"])) == 2


def test_alt_cannot_be_stolen_and_unlink_requires_ownership(tmp_path):
    repo = BindingsStorage(str(tmp_path / "bind.db"))
    repo.upsert_binding(bind(1, "#AAA"))
    with pytest.raises(ValueError, match="already linked"):
        repo.upsert_binding(bind(2, "#AAA"))
    assert not repo.unlink_account(-1001, "#AAA", owner_id=2)
    assert repo.get_user_id_by_tag(-1001, "#AAA") == 1
    assert repo.unlink_account(-1001, "#AAA", owner_id=1)
    assert repo.get_user_id_by_tag(-1001, "#AAA") is None


def test_delete_primary_promotes_alt_and_all_delete(tmp_path):
    repo = BindingsStorage(str(tmp_path / "bind.db"))
    repo.upsert_binding(bind(1,"#AAA"))
    repo.upsert_binding(bind(1,"#BBB"))
    assert repo.unlink_account(-1001,"#AAA",owner_id=1)
    assert repo.get_binding(-1001,1).coc_player_tag == "#BBB"
    assert repo.delete_binding(-1001,1)
    assert repo.get_user_accounts(-1001,1) == []


def test_migration_of_existing_binding_preserves_primary(tmp_path):
    path = str(tmp_path / "legacy.db")
    repo = BindingsStorage(path)
    with sqlite3.connect(path) as c:
        c.execute("DELETE FROM linked_accounts")
    restarted = BindingsStorage(path)
    assert restarted.get_user_accounts(-1001,1) == []
    restarted.upsert_binding(bind(1,"#AAA"))
    with sqlite3.connect(path) as c:
        c.execute("DELETE FROM linked_accounts")
    restarted = BindingsStorage(path)
    assert [x.coc_player_tag for x in restarted.get_user_accounts(-1001,1)] == ["#AAA"]
