import json
import os
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


def test_launcher_reads_supervisor_options_with_restrictive_permissions(tmp_path: Path):
    path = tmp_path / "options.json"
    path.write_text(json.dumps({
        "telegram_bot_token": "dummy-tg",
        "coc_token": "dummy-coc",
        "coc_clan_tag": "#2PRGP0L22",
    }))
    os.chmod(path, 0o600)

    result = build_env(path)

    assert result["TELEGRAM_BOT_TOKEN"] == "dummy-tg"
    assert result["COC_TOKEN"] == "dummy-coc"
    assert result["WAR_HISTORY_DB_PATH"] == "/data/war_history.db"


def test_addon_runs_as_root_for_supervisor_managed_data():
    dockerfile = Path(__file__).parents[2] / "deploy" / "Dockerfile.addon"
    contents = dockerfile.read_text(encoding="utf-8")

    assert "USER coc" not in contents
