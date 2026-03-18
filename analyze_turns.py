"""Analyze human vs bot decisions across all fetched game turn files."""
import json, sys
sys.path.insert(0, '.')
from bot import find_best_play

game_ids = ['d46ef801', '0fc2404b', 'f01e2a65', '0cefb10e']
totals = {'turns': 0, 'hplay': 0, 'hdraw': 0, 'bplay': 0, 'hp_bd': 0, 'hd_bp': 0}

for gid in game_ids:
    try:
        turns = json.load(open(f'/tmp/turns_{gid}.json'))['turns']
    except Exception as e:
        print(f'{gid}: error {e}')
        continue

    r = {'turns': 0, 'hplay': 0, 'hdraw': 0, 'bplay': 0, 'hp_bd': 0, 'hd_bp': 0}
    for t in turns:
        player = t['player_name']
        hand = t['hands'].get(player)
        if not hand:
            continue
        bp = find_best_play(hand, t['table'], version='v2')
        bot_plays = bp is not None
        human_plays = t['action'] == 'play'

        r['turns'] += 1
        if human_plays: r['hplay'] += 1
        else: r['hdraw'] += 1
        if bot_plays: r['bplay'] += 1
        if human_plays and not bot_plays: r['hp_bd'] += 1
        if not human_plays and bot_plays: r['hd_bp'] += 1

    pct = lambda n: f"{100*n//r['turns']}%" if r['turns'] else '?'
    print(f"{gid}: turns={r['turns']} hplay={r['hplay']}({pct(r['hplay'])}) hdraw={r['hdraw']}({pct(r['hdraw'])}) bplay={r['bplay']}({pct(r['bplay'])}) hp_bd={r['hp_bd']} hd_bp={r['hd_bp']}")
    for k in totals:
        totals[k] += r[k]

print()
t = totals
pct = lambda n: f"{100*n//t['turns']}%" if t['turns'] else '?'
print(f"TOTAL: turns={t['turns']} hplay={t['hplay']}({pct(t['hplay'])}) hdraw={t['hdraw']}({pct(t['hdraw'])}) bplay={t['bplay']}({pct(t['bplay'])}) hp_bd={t['hp_bd']} hd_bp={t['hd_bp']}")
print()
print(f"Human played, bot draws (bot too conservative): {t['hp_bd']} ({100*t['hp_bd']//t['hplay']}% of human plays)")
print(f"Human drew,   bot plays (human missed move):    {t['hd_bp']} ({100*t['hd_bp']//t['hdraw']}% of human draws)")
