"""Compare human turn decisions vs what the bot would do on the same game states."""
import json, os, urllib.request

for line in open('.env'):
    line = line.strip()
    if '=' in line and not line.startswith('#'):
        k, v = line.split('=', 1)
        os.environ[k] = v

ADMIN_KEY = os.environ['ADMIN_KEY']
BASE = 'https://mishmish-game.fly.dev'
game_ids = ['d46ef801', '0fc2404b', 'cb2ea02c', 'f01e2a65', '0cefb10e']

from bot import find_best_play

results = []
for gid in game_ids:
    req = urllib.request.Request(f'{BASE}/history/games/{gid}/turns', headers={'x-admin-key': ADMIN_KEY})
    turns = json.loads(urllib.request.urlopen(req).read())['turns']
    for t in turns:
        action = t['action']
        player = t['player_name']
        hand = t['hands'].get(player)
        if hand is None:
            continue
        table = t['table']
        bot_play = find_best_play(hand, table, version='v2')
        results.append({
            'game': gid, 'player': player,
            'hand_size': len(hand), 'table_melds': len(table),
            'human_action': action, 'bot_would_play': bot_play is not None,
        })

total = len(results)
human_play = sum(1 for r in results if r['human_action'] == 'play')
human_draw = sum(1 for r in results if r['human_action'] == 'draw')
bot_plays  = sum(1 for r in results if r['bot_would_play'])
agree      = sum(1 for r in results if (r['human_action']=='play') == r['bot_would_play'])
hp_bd = sum(1 for r in results if r['human_action']=='play' and not r['bot_would_play'])
hd_bp = sum(1 for r in results if r['human_action']=='draw' and r['bot_would_play'])

print(f'Turns analyzed : {total}')
print(f'Human  played  : {human_play} ({100*human_play//total}%)')
print(f'Human  drew    : {human_draw} ({100*human_draw//total}%)')
print(f'Bot would play : {bot_plays} ({100*bot_plays//total}%)')
print(f'Agreement      : {agree}/{total} ({100*agree//total}%)')
print()
print(f'Human played, bot draws (too conservative): {hp_bd}')
print(f'Human drew, bot plays (missed move):        {hd_bp}')

if hp_bd > 0:
    print('\nExamples of human playing when bot would draw:')
    for r in [r for r in results if r['human_action']=='play' and not r['bot_would_play']][:5]:
        print(f'  {r["player"]} hand={r["hand_size"]} table_melds={r["table_melds"]}')
