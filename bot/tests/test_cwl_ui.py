from app.ui import format_cwl_message


def test_cwl_view_uses_observed_results_and_warns():
    msg = format_cwl_message({"state": "inWar", "scheduledRounds": 7, "observedRounds": 1,
        "wins": 1, "draws": 0, "losses": 0,
        "rounds": [{"enemy": "Opp", "result": "win", "stars": 36,
                    "enemyStars": 30, "startTime": "20261105T120000Z"}]})
    assert "Opp" in msg
    assert "36 : 30" in msg
    assert "не официальная таблица" in msg
