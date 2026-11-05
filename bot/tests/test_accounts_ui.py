from app.accounts_ui import accounts_text, accounts_keyboard, delete_confirmation
from app.bindings_storage import Binding


def b(tag, main=False):
    return Binding(10, -100, tag, None, "Tester", "2026-11-05", is_primary=main)


def test_accounts_text_shows_primary_and_both_different_optins():
    msg = accounts_text([b("#AAA", True), b("#BBB")], {"#AAA": "in", "#BBB": "out"})
    assert "⭐ основной" in msg
    assert "КВ" in msg and "ЛВК" in msg
    assert "#BBB" in msg


def test_delete_uses_two_step_confirmation():
    key = accounts_keyboard([b("#AAA")])
    assert key.inline_keyboard[0][2].callback_data == "acct:delete:#AAA"
    confirm = delete_confirmation("#AAA")
    assert confirm.inline_keyboard[0][0].callback_data == "acct:confirm:#AAA"
    assert delete_confirmation("#AAA", admin=True).inline_keyboard[0][0].callback_data == "admin:confirm:#AAA"
