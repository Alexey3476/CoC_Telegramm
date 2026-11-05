"""Integration regression: one announcement after an observed completed war."""
import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app import bot as bot_module
from app.war_results import WarAnnouncementStore


def game_time(value):
    return value.strftime("%Y%m%dT%H%M%S.000Z")


def ended(enemy: str, our_stars: int, foe_stars: int, *, damage=(90, 90), age_minutes=10):
    finished = datetime.now(timezone.utc) - timedelta(minutes=age_minutes)
    return {
        "state": "warEnded", "startTime": game_time(finished - timedelta(days=1)),
        "endTime": game_time(finished),
        "clan": {"tag": "#OURS", "name": "Troublemakers", "stars": our_stars,
                 "destructionPercentage": damage[0]},
        "opponent": {"tag": "#"+enemy, "name": enemy, "stars": foe_stars,
                     "destructionPercentage": damage[1]},
    }


def test_job_sends_new_results_once_even_after_restart(monkeypatch, tmp_path):
    data = {"wars": [ended("PAST", 30, 20)]}
    sent = []

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

    class FakeBot:
        async def send_message(self, *, chat_id, text, parse_mode, disable_web_page_preview):
            sent.append((chat_id, text, parse_mode))

    async def fake_fetch(client, path):
        assert path == "/war-results"
        return data

    monkeypatch.setattr(bot_module.httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(bot_module, "fetch_json", fake_fetch)
    monkeypatch.setattr(bot_module, "settings", SimpleNamespace(
        war_results_enabled=True, clan_group_id=-1001,
        coc_clan_tag="#OURS", request_timeout_seconds=10,
    ))
    db = str(tmp_path / "bindings.db")
    ctx = SimpleNamespace(
        bot=FakeBot(), application=SimpleNamespace(
            bot_data={"war_outcomes": WarAnnouncementStore(db)}))
    asyncio.run(bot_module.war_result_job(ctx))  # First poll seeds old wars.
    assert sent == []
    data["wars"].extend([
        ended("VICTORY", 35, 30),
        ended("DEFEAT", 28, 30),
        ended("DRAW", 30, 30),
        ended("ANCIENT", 39, 10, age_minutes=60*24),
    ])
    asyncio.run(bot_module.war_result_job(ctx))
    assert len(sent) == 3
    assert all(x[0] == -1001 and x[2] == "HTML" for x in sent)
    assert any("🏆 Победа!" in x[1] for x in sent)
    assert any("⚔️ Поражение" in x[1] for x in sent)
    assert any("🤝 Ничья" in x[1] for x in sent)
    asyncio.run(bot_module.war_result_job(ctx))
    assert len(sent) == 3
    ctx.application.bot_data["war_outcomes"] = WarAnnouncementStore(db)
    asyncio.run(bot_module.war_result_job(ctx))
    assert len(sent) == 3


def test_disabled_or_no_group_does_not_fetch(monkeypatch, tmp_path):
    store = WarAnnouncementStore(str(tmp_path / "db.sqlite"))
    ctx = SimpleNamespace(application=SimpleNamespace(bot_data={"war_outcomes": store}))
    monkeypatch.setattr(bot_module, "settings", SimpleNamespace(
        war_results_enabled=False, clan_group_id=-1001))
    asyncio.run(bot_module.war_result_job(ctx))
    monkeypatch.setattr(bot_module, "settings", SimpleNamespace(
        war_results_enabled=True, clan_group_id=None))
    asyncio.run(bot_module.war_result_job(ctx))
