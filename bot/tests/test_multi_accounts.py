import sqlite3
from app.bindings_storage import Binding, BindingsStorage


def b(user, tag):
    return Binding(user, -1005, tag, None, "Tester", "2026-11-05T00:00:00+00:00")


def test_multiple_accounts_and_primary_fallback(tmp_path):
    db = BindingsStorage(str(tmp_path / "bindings.db"))
    db.upsert_binding(b(1, "#AAA"))
    db.upsert_binding(b(1, "#BBB"))
    assert [x.coc_player_tag for x in db.get_bindings_for_user(-1005, 1)] == ["#AAA", "#BBB"]
    assert db.get_binding(-1005, 1).is_primary
    assert db.set_primary(-1005, 1, "#BBB")
    assert db.get_binding(-1005, 1).coc_player_tag == "#BBB"
    assert db.delete_player_binding(-1005, "#BBB", requester_id=1)
    assert db.get_binding(-1005, 1).coc_player_tag == "#AAA"
    assert db.get_binding(-1005, 1).is_primary


def test_player_tag_unique_across_telegram_users(tmp_path):
    db = BindingsStorage(str(tmp_path / "bindings.db"))
    db.upsert_binding(b(1, "#AAA"))
    try:
        db.upsert_binding(b(2, "#AAA"))
        assert False, "must not reassign an existing tag"
    except ValueError:
        pass
    assert db.get_user_id_by_tag(-1005, "#AAA") == 1


def test_only_owners_can_delete_and_change_signup(tmp_path):
    db = BindingsStorage(str(tmp_path / "bindings.db"))
    db.upsert_binding(b(1, "#AAA"))
    try:
        db.delete_player_binding(-1005, "#AAA", requester_id=2)
        assert False, "must not delete someone else's account"
    except PermissionError:
        pass
    assert not db.set_cwl_opt_in(-1005, 2, "#AAA", "out")
    assert db.set_cwl_opt_in(-1005, 1, "#AAA", "in")
    assert db.get_binding(-1005, 1).cwl_opt_in == "in"
    assert db.delete_player_binding(-1005, "#AAA", requester_id=2, administrator=True)


def test_migrate_020_preserve_bindings_and_cooldowns(tmp_path):
    path = str(tmp_path / "legacy.db")
    with sqlite3.connect(path) as conn:
        conn.execute("""CREATE TABLE bindings (
            telegram_user_id INTEGER, group_id INTEGER, coc_player_tag TEXT,
            telegram_username TEXT, telegram_full_name TEXT, created_at TEXT,
            UNIQUE(group_id,telegram_user_id))""")
        conn.execute("INSERT INTO bindings VALUES (1,-1005,'#AAA',NULL,'Tester','2026-10-01')")
        conn.execute("""CREATE TABLE reminder_cooldowns(
            group_id INTEGER, telegram_user_id INTEGER, last_reminded_at TEXT,
            PRIMARY KEY(group_id,telegram_user_id))""")
        conn.execute("INSERT INTO reminder_cooldowns VALUES (-1005,1,'2026-10-15T00:00:00+00:00')")
    db = BindingsStorage(path)
    assert db.get_binding(-1005, 1).coc_player_tag == "#AAA"
    assert db.get_binding(-1005, 1).is_primary
    assert len(db.get_cooldowns(-1005, [1])) == 1
    db.upsert_binding(b(1, "#BBB"))
    assert len(db.get_bindings_for_user(-1005, 1)) == 2


def test_partial_deletion_preserves_other_accounts(tmp_path):
    db = BindingsStorage(str(tmp_path / "bindings.db"))
    for tag in ("#AAA", "#BBB", "#CCC"):
        db.upsert_binding(b(7, tag))
    assert db.delete_player_binding(-1005, "#BBB", requester_id=7)
    assert {x.coc_player_tag for x in db.get_bindings_for_user(-1005, 7)} == {"#AAA", "#CCC"}
