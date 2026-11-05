from app.players_ui import roster_page, roster_keyboard, hall_text, donation_text


def test_roster_names_escaped_and_clickable():
    roster = [{"name": f"Name_{i}<&>", "tag": f"#{i}", "townHallLevel": 16,
               "role": "admin", "donations": i} for i in range(17)]
    assert "Name_0&lt;&amp;&gt;" in roster_page(roster)
    assert "Страница 2/3" in roster_page(roster,1)
    keys = str(roster_keyboard(roster,1).inline_keyboard)
    assert "players:view:8" in keys and "players:page:2" in keys


def test_donation_and_hall_do_not_fabricate_games():
    members = [{"name":"A<&>","donations":7},{"name":"B","donations":100}]
    s = donation_text(members)
    assert s.index("B") < s.index("A&lt;&amp;&gt;")
    assert "текущий сезон" in s
    display = hall_text({"donations":[{"name":"Lex","score":100}]})
    assert "Игры кланов" in display and "не передаются" in display
