from app.selection_ui import lineup_keyboard, lineup_message


def test_weights_and_categories_render():
    data = {"clanName": "Troublemakers", "recommendedSize": 15,
            "selectionMode": "war", "reservedSlots": 14,
            "weightTable": {"strength": 35, "attendance": 30,
                            "attack": 25, "preference": 10},
            "recommendedLineup": [],
            "categories": {"lineup": [{"name": "Lex", "townHallLevel": 18,
                                      "selectionScore": 97, "selectionPreference": "in",
                                      "history": {"wars": 5}}]}}
    assert "35%" in lineup_message(data, "weights")
    assert "Lex" in lineup_message(data, "main")
    keys = lineup_keyboard(data=data)
    callback_data = [button.callback_data for row in keys.inline_keyboard for button in row]
    assert "lineup:cwl:0" in callback_data
    assert "lineup:kick:0" in callback_data
    assert "lineup:bonus:0" in callback_data
