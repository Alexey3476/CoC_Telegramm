from app.ranking_ui import ranking_page, ranking_keyboard


def test_all_players_including_optout_sorted_and_paginated():
    data={"mode":"cwl","allPlayers":[
        {"name":f"Player {i}", "selectionScore":float(i),
         "warPreference":"out" if i == 17 else "in",
         "townHallLevel":18,"expLevel":200,"league":"Electro League 32","role":"member"}
        for i in range(18)]}
    text=ranking_page(data)
    assert "Игроков: 18" in text
    assert "Player 17" in text
    assert "Player 0" not in text
    assert "🔴" in text
    page3=ranking_page(data,2)
    assert "Player 0" in page3
    keyboard=ranking_keyboard(data,1)
    buttons=[b.callback_data for row in keyboard.inline_keyboard for b in row]
    assert "rank:mode:war" in buttons and "rank:page:2" in buttons


def test_names_html_escaped_and_unknown_stats_not_fabricated():
    data={"mode":"war","allPlayers":[{"name":"<Ace & Boss>","selectionScore":50,
                                       "warPreference":"unknown","townHallLevel":17}]}
    msg=ranking_page(data)
    assert "&lt;Ace &amp; Boss&gt;" in msg and "❔" in msg
    assert "0 атак" not in msg
