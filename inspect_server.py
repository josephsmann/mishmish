# /// script
# requires-python = ">=3.13"
# dependencies = [
#     "httpx==0.28.1",
#     "marimo>=0.20.3",
#     "polars==1.38.1",
# ]
# ///

import marimo

__generated_with = "0.20.3"
app = marimo.App(width="medium")


@app.cell
def _():
    import marimo as mo
    import httpx
    import polars as pl

    return httpx, mo, pl


@app.cell
def _():
    BASE_URL = "https://mishmish-game.fly.dev"
    HEADERS = {"X-Admin-Key": "REDACTED"}
    return BASE_URL, HEADERS


@app.cell(hide_code=True)
def _(mo):
    get_selected, set_selected = mo.state(None)  # {"game_id": str, "source": "live"|"history"}
    return get_selected, set_selected


@app.cell(hide_code=True)
def _(mo):
    refresh = mo.ui.refresh(options=["5s", "10s", "30s"], default_interval="5s")
    refresh
    return (refresh,)


@app.cell(hide_code=True)
def _(BASE_URL, HEADERS, httpx, refresh):
    refresh
    _r = httpx.get(f"{BASE_URL}/admin/games", headers=HEADERS, timeout=10)
    live_games = _r.json().get("games", []) if _r.is_success else []
    return (live_games,)


@app.cell(hide_code=True)
def _(BASE_URL, httpx, refresh):
    refresh
    _r = httpx.get(f"{BASE_URL}/history/games", params={"limit": 50}, timeout=10)
    history_games = _r.json().get("games", []) if _r.is_success else []
    return (history_games,)


@app.cell(hide_code=True)
def _(live_games, mo, pl):
    if live_games:
        _df = pl.DataFrame({
            "game_id": [g["game_id"] for g in live_games],
            "status":  [g["status"] for g in live_games],
            "players": [", ".join(g["players"]) for g in live_games],
        })
        live_table = mo.ui.table(_df, selection="single")
    else:
        live_table = mo.md("_No active games_")
    return (live_table,)


@app.cell(hide_code=True)
def _(history_games, mo, pl):
    if history_games:
        _df = pl.DataFrame({
            "game_id":    [g["game_id"] for g in history_games],
            "ended_at":   [(g.get("ended_at") or "")[:19] for g in history_games],
            "winner":     [g.get("winner_name") or "—" for g in history_games],
            "end_status": [g.get("end_status") or "" for g in history_games],
            "players":    [
                ", ".join(p.get("name", "") if isinstance(p, dict) else str(p)
                          for p in g.get("players", []))
                for g in history_games
            ],
        })
        history_table = mo.ui.table(_df, selection="single")
    else:
        history_table = mo.md("_No game history_")
    return (history_table,)


@app.cell
def _(history_table, live_table, mo):
    mo.ui.tabs({
        "🟢 Live games": live_table,
        "📜 History":    history_table,
    })
    return


@app.cell(hide_code=True)
def _(history_games, history_table, live_games, live_table, set_selected):
    if hasattr(live_table, "value") and live_table.value is not None and len(live_table.value) > 0:
        _gid = live_table.value["game_id"][0]
        _g = next((g for g in live_games if g["game_id"] == _gid), None)
        if _g:
            set_selected({"game_id": _gid, "source": "live", "meta": _g})
    elif hasattr(history_table, "value") and history_table.value is not None and len(history_table.value) > 0:
        _gid = history_table.value["game_id"][0]
        _g = next((g for g in history_games if g["game_id"] == _gid), None)
        if _g:
            set_selected({"game_id": _gid, "source": "history", "meta": _g})
    return


@app.cell(hide_code=True)
def _(BASE_URL, HEADERS, get_selected, httpx):
    _sel = get_selected()
    game_detail = None
    if _sel is not None:
        if _sel["source"] == "live":
            _r = httpx.get(f"{BASE_URL}/admin/games/{_sel['game_id']}", headers=HEADERS, timeout=10)
        else:
            _r = httpx.get(f"{BASE_URL}/history/games/{_sel['game_id']}", timeout=10)
        if _r.is_success:
            game_detail = _r.json().get("game")
    return (game_detail,)


@app.cell(hide_code=True)
def _(game_detail, get_selected, mo):
    _sel = get_selected()
    mo.stop(_sel is None, mo.md("_Select a game above to inspect it._"))

    _g = game_detail or _sel["meta"]
    _gid = _g["game_id"]
    _status = _g.get("status") or _g.get("end_status") or "—"
    _winner = _g.get("winner_name") or _g.get("winner") or "—"
    _players = _g.get("players", [])
    _names = [p.get("name", "") if isinstance(p, dict) else str(p) for p in _players]

    mo.md(f"""
    ## Game `{_gid[:8]}…`

    | Field | Value |
    | --- | --- |
    | Status | **{_status}** |
    | Winner | {_winner} |
    | Players | {", ".join(_names)} |
    | Started | {(_g.get("started_at") or "—")[:19]} |
    | Ended | {(_g.get("ended_at") or "—")[:19]} |
    """)
    return


@app.cell
def _(game_detail, mo):
    mo.stop(game_detail is None)

    SUIT_SYMBOL = {"H": "♥", "D": "♦", "C": "♣", "S": "♠"}
    SUIT_COLOR  = {"H": "#c0392b", "D": "#c0392b", "C": "#2c3e50", "S": "#2c3e50"}

    def card_html(card):
        sym = SUIT_SYMBOL[card["suit"]]
        col = SUIT_COLOR[card["suit"]]
        return (
            f'<span style="display:inline-block;border:1px solid #aaa;border-radius:4px;'
            f'padding:2px 5px;margin:2px;font-size:1em;background:#fff;color:{col};'
            f'font-family:monospace;min-width:2em;text-align:center;">'
            f'{card["rank"]}{sym}</span>'
        )

    # Live games use "table"/"hand"; history games use "final_table"/"final_hand"
    _melds = game_detail.get("final_table") or game_detail.get("table") or []
    _players = game_detail.get("players", [])

    _parts = ["<h3>Table</h3>"]
    if _melds:
        for _m in _melds:
            _parts.append("".join(card_html(c) for c in _m) + "<br>")
    else:
        _parts.append("<em>No cards on table</em>")

    _parts.append("<h3>Players</h3>")
    for _p in _players:
        _hand = _p.get("final_hand") or _p.get("hand") or []
        _hand_html = "".join(card_html(c) for c in _hand) if _hand else "<em>empty</em>"
        _parts.append(f"<b>{_p.get('name','?')}</b> — {len(_hand)} cards: {_hand_html}<br>")

    mo.Html("".join(_parts))
    return


@app.cell
def _(BASE_URL, get_selected, httpx):
    _sel = get_selected()
    game_turns = []
    if _sel is not None:
        _r = httpx.get(f"{BASE_URL}/history/games/{_sel['game_id']}/turns", timeout=10)
        if _r.is_success:
            game_turns = _r.json().get("turns", [])
    return (game_turns,)


@app.cell
def _(game_turns, mo):
    mo.stop(not game_turns, mo.md("_No turn history recorded for this game._"))

    SUIT_SYMBOL = {"H": "♥", "D": "♦", "C": "♣", "S": "♠"}
    SUIT_COLOR  = {"H": "#c0392b", "D": "#c0392b", "C": "#2c3e50", "S": "#2c3e50"}

    def _card_html(card):
        sym = SUIT_SYMBOL[card["suit"]]
        col = SUIT_COLOR[card["suit"]]
        return (
            f'<span style="display:inline-block;border:1px solid #aaa;border-radius:4px;'
            f'padding:2px 5px;margin:2px;font-size:0.85em;background:#fff;color:{col};'
            f'font-family:monospace;min-width:1.8em;text-align:center;">'
            f'{card["rank"]}{sym}</span>'
        )

    def _hand_html(cards):
        return "".join(_card_html(c) for c in cards) if cards else "<em style='color:#888'>—</em>"

    def _table_html(melds):
        if not melds:
            return "<em style='color:#888'>—</em>"
        return " | ".join("".join(_card_html(c) for c in m) for m in melds)

    _player_names = sorted({t["player_name"] for t in game_turns})

    _rows = []
    for _t in game_turns:
        _action_badge = (
            '<span style="background:#4caf50;color:#fff;border-radius:3px;padding:1px 5px;font-size:0.8em">play</span>'
            if _t["action"] == "play" else
            '<span style="background:#2196f3;color:#fff;border-radius:3px;padding:1px 5px;font-size:0.8em">draw</span>'
        )
        _player_cells = "".join(
            f'<td style="padding:4px 8px;border-bottom:1px solid #333;vertical-align:top">{_hand_html(_t["hands"].get(n, []))}</td>'
            for n in _player_names
        )
        _rows.append(
            f'<tr>'
            f'<td style="padding:4px 8px;border-bottom:1px solid #333;color:#aaa;white-space:nowrap">{_t["turn_number"]}</td>'
            f'<td style="padding:4px 8px;border-bottom:1px solid #333">{_t["player_name"]} {_action_badge}</td>'
            f'{_player_cells}'
            f'<td style="padding:4px 8px;border-bottom:1px solid #333;vertical-align:top">{_table_html(_t["table"])}</td>'
            f'</tr>'
        )

    _header_cells = "".join(
        f'<th style="padding:4px 8px;text-align:left;border-bottom:2px solid #555">{n}</th>'
        for n in _player_names
    )
    _html = f"""
    <div style="overflow-x:auto">
    <table style="border-collapse:collapse;font-size:0.9em;width:100%">
      <thead>
        <tr>
          <th style="padding:4px 8px;text-align:left;border-bottom:2px solid #555">#</th>
          <th style="padding:4px 8px;text-align:left;border-bottom:2px solid #555">Action</th>
          {_header_cells}
          <th style="padding:4px 8px;text-align:left;border-bottom:2px solid #555">Table</th>
        </tr>
      </thead>
      <tbody>{"".join(_rows)}</tbody>
    </table>
    </div>
    """
    mo.Html(_html)
    return


if __name__ == "__main__":
    app.run()
