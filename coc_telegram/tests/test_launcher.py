import json
from pathlib import Path
from coc_telegram.launcher import build_env


def test_build_env_defaults(tmp_path: Path):
    path = tmp_path / "options.json"
    path.write_text(json.dumps({
        "telegram_bot_token": "dummy-tg",
        "coc_token": "dummy-coc",
        "coc_clan_tag": "#2PRGP0L22",
        "enforce_clan_membership": True,
        "clan_group_id": "",
    }))
    result = build_env(path)
    assert result["TELEGRAM_BOT_TOKEN"] == "dummy-tg"
    assert result["COC_TOKEN"] == "dummy-coc"
    assert result["ENFORCE_CLAN_MEMBERSHIP"] == "true"
    assert "CLAN_GROUP_ID" not in result
    assert result["BACKEND_URL"] == "http://127.0.0.1:8000"
