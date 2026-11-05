from app.binding_ui import sorted_roster, roster_keyboard


def test_suggest_nick_but_verify_ownership_separately():
    roster = [{"name": "Other", "tag": "#Q8Y", "townHallLevel": 12},
              {"name": "Lex", "tag": "#VU099JCR", "townHallLevel": 18}]
    ordered = sorted_roster(roster, "Lex", "someone")
    assert ordered[0]["tag"] == "#VU099JCR"
    keys = roster_keyboard(ordered)
    assert keys.inline_keyboard[0][0].callback_data == "pick:player:0"
    assert keys.inline_keyboard[-2][0].callback_data == "pick:manual:0"


def test_roster_pagination():
    roster = [{"name": f"Test {n}", "tag": str(n)} for n in range(25)]
    first = roster_keyboard(roster, 0)
    second = roster_keyboard(roster, 1)
    assert first.inline_keyboard[0][0].callback_data == "pick:player:0"
    assert second.inline_keyboard[0][0].callback_data == "pick:player:8"
