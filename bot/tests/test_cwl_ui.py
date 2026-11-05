from app.ui import format_cwl_message


def test_cwl_view_uses_observed_results_and_warns():
    msg = format_cwl_message({"state": "inWar", "scheduledRounds": 7, "observedRounds": 1,
        "wins": 1, "draws": 0, "losses": 0,
        "rounds": [{"enemy": "Opp", "result": "win", "stars": 36,
                    "enemyStars": 30, "startTime": "20261105T120000Z"}]})
    assert "Opp" in msg
    assert "36 : 30" in msg
    assert "не официальная таблица" in msg



def test_cwl_full_group_standings_and_seven_rounds():
    c = [{"tag":f"#C{i}","name":f"Clan {i}","place":i,"stars":100-i,
          "winBonusStars":20,"destruction":300.0,"completedWars":3,
          "placeTied":False} for i in range(1,9)]
    data={"state":"inWar","scheduledRounds":7,"observedRounds":3,
          "clanTag":"#C3","wins":2,"draws":0,"losses":1,
          "rounds":[{"round":i,"enemy":f"Enemy {i}",
                    "result":"upcoming","stars":None,"enemyStars":None}
                    for i in range(1,8)],
          "standings":{"scheduledRounds":7,"clans":c,"myPlace":3,
                       "myPlaceTied":False,"fullyObserved":False,
                       "seasonCompleted":False,"expectedWars":28,"observedWars":12}}
    msg=format_cwl_message(data)
    assert "Раундов: 7" in msg
    assert "7. Enemy 7" in msg
    assert "Промежуточное место: <b>3 из 8</b>" in msg
    assert "из 28" in msg
    assert "⭐" in msg and "20" in msg
