from datetime import datetime, timezone

from app.ui import (
    format_war_message, format_raid_message, game_time, remaining_until,
    lineup_message, safe_tag_name, normalize_name,
)


def test_berlin_winter_summer_times():
    assert game_time("20261105T121728.000Z") == "05.11.2026, 13:17"
    assert game_time("20260705T121728.000Z") == "05.07.2026, 14:17"
    assert game_time("unknown") == "Нет данных"


def test_countdown_and_war_score():
    now = datetime(2026, 11, 5, 12, 0, tzinfo=timezone.utc)
    assert remaining_until("20261105T141500.000Z", now) == "2 ч 15 мин"
    msg = format_war_message({
        "state": "inWar", "teamSize": 2, "attacksPerMember": 2,
        "clan": {"name": "Troublemakers", "stars": 5, "destructionPercentage": 88.15,
                 "members": [{"attacks": [{"stars": 3}]}]},
        "opponent": {"name": "Enemy", "stars": 4, "destructionPercentage": 80},
        "endTime": "20261105T141500.000Z",
    })
    assert "5 : 4" in msg
    assert "осталось 3" in msg


def test_raid_history():
    msg = format_raid_message({"currentRaid": {
        "state": "ended", "capitalTotalLoot": 12500,
        "startTime": "20261030T070000.000Z", "endTime": "20261102T070000.000Z",
    }})
    assert "Последний рейд завершён" in msg
    assert "12500" in msg


def test_tag_cleaning_and_name_match():
    assert safe_tag_name("⚔ Lex 🐲") == "Lex"
    assert len(safe_tag_name("a" * 100)) == 16
    assert normalize_name(" L-e_X ") == "lex"


def test_lineup_explains_missing_data_and_has_backup():
    data = {"clanName": "Test", "recommendedSize": 1, "observedWarCount": 3,
            "recommendedLineup": [
                {"name": "Lex", "townHallLevel": 18, "warReadiness": 95, "warPreference": "in"},
                {"name": "Other", "townHallLevel": 16, "warReadiness": 80, "warPreference": "out"},
            ]}
    assert "без истории" in lineup_message(data)
    assert "Lex" in lineup_message(data)
    assert "Other" in lineup_message(data, "bench")
    assert "80% сила самой TH" in lineup_message(data, "about")



def test_war_shows_unspent_attacks_without_leaking_markup():
    msg = format_war_message({
        "state": "inWar", "teamSize": 2, "attacksPerMember": 1,
        "clan": {"name": "Our", "stars": 3, "destructionPercentage": 50,
                 "members": [{"name": "A&B", "attacks": []},
                             {"name": "Lex", "attacks": [{"stars": 3}]}]},
        "opponent": {"name": "Enemy", "stars": 1, "destructionPercentage": 20},
    })
    assert "A&amp;B" in msg
    assert "Lex · 1 атак" not in msg
    assert "осталось 1" in msg
