from pathlib import Path

import pytest
from app.bindings_storage import Binding, BindingsStorage
from app.ui import safe_tag_name


def test_binding_cannot_be_stolen(tmp_path: Path):
    db = BindingsStorage(str(tmp_path / "bindings.db"))
    db.upsert_binding(Binding(1, -1001, "#VU099JCR", None, "Alice", "2026-11-05"))
    with pytest.raises(ValueError, match="already linked"):
        db.upsert_binding(Binding(2, -1001, "#VU099JCR", None, "Bob", "2026-11-05"))
    assert db.get_user_id_by_tag(-1001, "#VU099JCR") == 1


def test_telegram_tag_16_char_no_emoji():
    assert safe_tag_name("⚔ Lex 🐲") == "Lex"
    assert safe_tag_name("abcdefghijklmnopqr") == "abcdefghijklmnop"
