from datetime import datetime, timezone

from app.selection import MODE_WEIGHTS, SelectionStore, score_and_categorize
from app.war_metrics import _league_index, relative_strength

NOW = datetime(2026, 11, 5, tzinfo=timezone.utc)


def player(tag, th, xp=200, **kw):
    return dict(tag=tag, name=tag, townHallLevel=th, expLevel=xp,
                heroesLevel=400, heroEquipmentScore=150,
                league="Titan League", warPreference="in", role="member",
                **kw)


def test_high_town_hall_wins_in_cwl_even_with_equal_hero_relative_strength():
    players = [player("#A", 18), player("#B", 15)]
    result = score_and_categorize(
        players, MODE_WEIGHTS["cwl"], {}, mode="cwl", size=15, now=NOW)
    by_tag = {p["tag"]: p for p in result["allPlayers"]}
    assert by_tag["#A"]["modeStrength"] > by_tag["#B"]["modeStrength"]
    assert by_tag["#A"]["selectionScore"] > by_tag["#B"]["selectionScore"]


def test_regular_war_preserves_town_hall_mix_for_15_and_25():
    players = [player(f"#A{i}", 18, xp=190+i) for i in range(30)] + [
        player(f"#B{i}", 15, xp=120+i) for i in range(20)]
    for size, high in ((15, 9), (25, 15)):
        data = score_and_categorize(
            players, MODE_WEIGHTS["war"], {}, mode="war", size=size, now=NOW)
        selected = data["categories"]["main"]
        assert len(selected) == size
        assert sum(p["townHallLevel"] == 18 for p in selected) == high


def test_experience_is_weak_tiebreaker_within_same_town_hall():
    players = [player("#A", 18, xp=260), player("#B", 18, xp=220)]
    scores = relative_strength(players)
    assert scores["#A"]["relativeStrength"] > scores["#B"]["relativeStrength"]
    assert scores["#A"]["strengthCoverage"] == 100


def test_existing_custom_cwl_weights_survive_new_defaults(tmp_path):
    path = str(tmp_path / "weights.db")
    store = SelectionStore(path)
    store.set_weight("strength", 50, mode="cwl")
    expected = store.weights("cwl")
    assert SelectionStore(path).weights("cwl") == expected
    assert sum(MODE_WEIGHTS["cwl"].values()) == 100


def test_current_2026_league_order_is_recognized():
    assert _league_index("Skeleton 1") == 1
    assert _league_index("Valkyrie 14") == 14
    assert _league_index("P.E.K.K.A 24") == 24
    assert _league_index("Titan 25") == 25
    assert _league_index("Electro 33") == 33
    assert _league_index("Legend League") == 34
    assert _league_index("Master II") is not None
