from pathlib import Path


ROOT = Path(__file__).parents[2]


def test_avoid_publishing_beerlogger_package_from_another_repo():
    workflow = (ROOT / ".github/workflows/coc-addon.yml").read_text()
    assert "github.repository == 'Beerlogger01/CoC_Telegramm'" in workflow


def test_private_chat_has_one_text_handler():
    source = (ROOT / "bot/app/bot.py").read_text()
    assert source.count("filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE,") == 1


def test_telegram_setting_does_not_leak_bot_token():
    source = (ROOT / "bot/app/bot.py").read_text()
    assert 'await update.message.reply_text(format_settings_report())' not in source
