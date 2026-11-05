from app.coc_client import orient_war_for_clan


def test_our_clan_is_normalized_from_opponent_in_cwl():
    original = {"state": "inWar",
        "clan": {"tag": "#ENEMY", "name": "Enemy", "members": [{"name": "Enemy Player"}]},
        "opponent": {"tag": "#OURS", "name": "Us", "members": [{"name": "Lex"}]}}
    normal = orient_war_for_clan(original, "#OURS")
    assert normal["clan"]["name"] == "Us"
    assert normal["clan"]["members"][0]["name"] == "Lex"
    assert normal["opponent"]["name"] == "Enemy"


def test_regular_war_keeps_original_order():
    original = {"clan": {"tag": "#OURS"}, "opponent": {"tag": "#ENEMY"}}
    assert orient_war_for_clan(original, "#OURS") == original
