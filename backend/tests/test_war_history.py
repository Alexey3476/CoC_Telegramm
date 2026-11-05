from pathlib import Path
from app.war_history import WarHistory, summarize_wars


def test_records_only_completed_wars(tmp_path: Path):
    history = WarHistory(str(tmp_path / "history.db"))
    war = {
        "state": "inWar",
        "startTime": "20261105T100000.000Z",
        "attacksPerMember": 2,
        "clan": {
            "tag": "#AAA",
            "members": [
                {"tag": "#P1", "townhallLevel": 16, "attacks": [
                    {"stars": 3, "defenderTag": "#E1"}]},
                {"tag": "#P2", "townhallLevel": 16, "attacks": [
                    {"stars": 3, "defenderTag": "#E2"},
                    {"stars": 2, "defenderTag": "#E2"}]},
            ],
        },
        "opponent": {
            "tag": "#BBB",
            "members": [
                {"tag": "#E1", "townhallLevel": 14},
                {"tag": "#E2", "townhallLevel": 16},
            ],
        },
    }
    assert history.save(war)
    assert history.completed() == []
    war["state"] = "warEnded"
    assert history.save(war)
    record = summarize_wars(history.completed(), "#AAA")
    assert record["#P1"]["missedAttacks"] == 1
    assert record["#P1"]["reliabilityPct"] == 50.0
    assert record["#P1"]["threeStarsDownhill"] == 1
    assert record["#P2"]["missedAttacks"] == 0
    assert record["#P2"]["threeStarsEqualOrHigher"] == 1
    assert record["#P2"]["warReadiness"] > record["#P1"]["warReadiness"]


def test_unknown_stays_unknown():
    assert summarize_wars([], "#AAA") == {}
