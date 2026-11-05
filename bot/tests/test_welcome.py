from pathlib import Path


def test_welcome_message_uses_html_without_repeated_pinning():
    code = (Path(__file__).parents[1] / "app" / "bot.py").read_text()
    assert 'f"🏷️ <b>Тег:</b> {player_tag}' in code
    assert "pin_chat_message(" not in code
    assert "unpin_chat_message(" not in code


def test_start_uses_real_bot_username_not_placeholder():
    code = (Path(__file__).parents[1] / "app" / "bot.py").read_text()
    assert "@bot_username" not in code
    assert "@{context.bot.username}" in code
