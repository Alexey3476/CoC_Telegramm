from app.binding_ui import available_roster, sorted_roster


def test_picker_never_shows_bound_players_including_own_alts():
    clan = [
        {"name": "Lex", "tag": "#OLD"},
        {"name": "Twin Lex", "tag": "#TWIN"},
        {"name": "Free Player", "tag": "#FREE"},
        {"name": "Another", "tag": "#TAKEN"},
    ]
    linked = {"#OLD", "#TWIN", "#TAKEN"}
    result = sorted_roster(available_roster(clan, linked), "Lex")
    assert [p["tag"] for p in result] == ["#FREE"]


def test_picker_no_available_players_returns_empty():
    assert available_roster([{"tag": "#ONE", "name": "A"}], {"#ONE"}) == []
    assert available_roster([{"name": "No tag"}], set()) == []
