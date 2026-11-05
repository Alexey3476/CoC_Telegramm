import sqlite3

from app.selection import MODE_WEIGHTS, SelectionStore, score_and_categorize


def test_untouched_old_cwl_weights_migrate_once(tmp_path):
    path = str(tmp_path / "selection.sqlite")
    SelectionStore(path)
    with sqlite3.connect(path) as db:
        db.executemany("UPDATE mode_weights SET value=? WHERE mode='cwl' AND metric=?",
                       [(20,"strength"),(35,"discipline"),(40,"quality"),(5,"role")])
        db.execute("DELETE FROM selection_migrations WHERE name='cwl_th_focused_022'")
    updated = SelectionStore(path)
    assert updated.weights("cwl") == MODE_WEIGHTS["cwl"]


def test_custom_weights_survive_upgrade(tmp_path):
    path = str(tmp_path / "selection.sqlite")
    store = SelectionStore(path)
    store.set_weight("role", 17, mode="cwl")
    previous = store.weights("cwl")
    with sqlite3.connect(path) as db:
        db.execute("DELETE FROM selection_migrations WHERE name='cwl_th_focused_022'")
    assert SelectionStore(path).weights("cwl") == previous


def test_high_th_prioritized_more_in_cwl_than_balanced_war():
    members = [
        {"tag":"#18","name":"Big","townHallLevel":18,
         "heroesLevel":200,"heroEquipmentScore":90,"expLevel":200,
         "league":"Electro League 28","warPreference":"in","role":"member"},
        {"tag":"#15","name":"Small","townHallLevel":15,
         "heroesLevel":200,"heroEquipmentScore":90,"expLevel":200,
         "league":"Electro League 28","warPreference":"in","role":"member"},
    ]
    war = score_and_categorize(members, MODE_WEIGHTS["war"], {}, mode="war")
    cwl = score_and_categorize(members, MODE_WEIGHTS["cwl"], {}, mode="cwl")
    scores_war = {p["tag"]:p["selectionScore"] for p in war["recommendedLineup"]}
    scores_cwl = {p["tag"]:p["selectionScore"] for p in cwl["recommendedLineup"]}
    assert abs(scores_war["#18"] - scores_war["#15"]) < 1
    assert scores_cwl["#18"] > scores_cwl["#15"] + 15
