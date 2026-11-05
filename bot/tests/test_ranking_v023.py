from app.players_ui import ranking_page, ranking_keyboard


def test_ranked_clan_table_pages_and_html():
    players = [
        {"tag": f"#A{i}", "name": f"Игрок <{i}>", "selectionScore": i,
         "townHallLevel": 18, "expLevel": 205+i, "league": "Legend League",
         "eligibility": "candidate"}
        for i in range(22)
    ]
    data = {"allPlayers": players}
    page1 = ranking_page(data, "cwl", 0)
    page3 = ranking_page(data, "cwl", 2)
    assert "ЛВК" in page1
    assert "Игрок &lt;21&gt;" in page1
    assert "Игрок &lt;0&gt;" in page3
    assert "страница 1/3" in page1
    assert "страница 3/3" in page3
    assert "rank:page:1" in str(ranking_keyboard("cwl", 0, 22).inline_keyboard)
