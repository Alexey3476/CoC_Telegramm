from app.profile_ui import detail_text
from app.ui import lineup_keyboard, lineup_message, format_cwl_message


def test_all_45_war_members_and_all_50_ranks_are_reachable():
    players = [{"tag": f"#{i}", "name": f"Member{i:02}", "selectionScore": 100 - i,
                "townHallLevel": 18, "expLevel": 280, "clanRank": i + 1} for i in range(50)]
    data = {"mode": "war", "lineupSize": 45, "recommendedSize": 45,
            "categories": {"main": players[:45], "bench": players[45:]},
            "clanRanking": players, "recommendedLineup": players}
    assert "Member44" in lineup_message(data, "main", 2)
    assert "Member49" in lineup_message(data, "ranking", 3)
    assert "lineup:ranking:3" in str(lineup_keyboard("ranking", 2, data).inline_keyboard)
    assert "lineup:teamsize:45" in str(lineup_keyboard("size", 0, data).inline_keyboard)
    assert "280" in detail_text({"expLevel": 280})


def test_cwl_ui_labels_partial_star_place_and_ties():
    message = format_cwl_message({"state": "inWar", "scheduledRounds": 7,
        "currentPlace": 2, "totalStars": 80, "standingsComplete": False, "missingWars": 1,
        "standings": [{"name": "Clan <&>", "place": 2, "stars": 80}]})
    assert "Место сейчас по общим звёздам: 2" in message
    assert "предварительно" in message
    assert "Clan &lt;&amp;&gt;" in message
    assert "+ 10 за завершённую победу" in message
