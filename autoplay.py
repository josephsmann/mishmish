"""
Hill-climbing bot parameter search via self-play.

Usage:
    uv run python autoplay.py              # run until Ctrl+C
    uv run python autoplay.py --rounds 5   # run N rounds then stop (for testing)

Output:
    - Terminal: live progress per round
    - autoplay_log.jsonl: one JSON line per round
"""

import argparse
import dataclasses
import json
import random
import time
from copy import copy

from bot import BotConfig
from bot_sim import simulate_game


def mutate(config: BotConfig) -> BotConfig:
    """Return a new BotConfig with exactly one parameter mutated."""
    new = copy(config)
    param = random.choice(["lam", "hand_cutoff"])
    if param == "lam":
        new.lam = float(max(0.0, min(2.0, new.lam + random.gauss(0, 0.1))))
    else:
        new.hand_cutoff = int(max(6, min(20, new.hand_cutoff + random.choice([-2, -1, 1, 2]))))
    return new


def run_matchup(champion: BotConfig, challenger: BotConfig, n_games: int = 50):
    """
    Play n_games between champion and challenger.
    Half the games have champion as player A (goes first),
    half have challenger as player A.

    Returns (champion_wins, challenger_wins, draws).
    """
    champion_wins = 0
    challenger_wins = 0
    draws = 0
    half = n_games // 2

    for i in range(n_games):
        if i < half:
            # Champion is player A (goes first)
            result = simulate_game(champion, challenger)
            if result == "a":
                champion_wins += 1
            elif result == "b":
                challenger_wins += 1
            else:
                draws += 1
        else:
            # Challenger is player A (goes first)
            result = simulate_game(challenger, champion)
            if result == "a":
                challenger_wins += 1
            elif result == "b":
                champion_wins += 1
            else:
                draws += 1

    return champion_wins, challenger_wins, draws


def format_config(config: BotConfig) -> str:
    return f"lam={config.lam:.2f} cutoff={config.hand_cutoff}"


def main():
    parser = argparse.ArgumentParser(description="Hill-climbing bot parameter search")
    parser.add_argument(
        "--rounds",
        type=int,
        default=0,
        help="Number of rounds to run (0 = run forever)",
    )
    args = parser.parse_args()

    champion = BotConfig(lam=0.5, hand_cutoff=10)
    log_path = "autoplay_log.jsonl"
    t_start = time.time()
    round_num = 0

    print(f"Starting hill-climbing search. Initial champion: {format_config(champion)}")
    print(f"Log: {log_path}\n")

    try:
        while True:
            if args.rounds > 0 and round_num >= args.rounds:
                break

            round_num += 1
            pre_round_champion = copy(champion)
            challenger = mutate(champion)

            print(f"Round {round_num} | Champion: {format_config(pre_round_champion)} | Challenger: {format_config(challenger)}")

            champ_wins, chal_wins, draws = run_matchup(champion, challenger)
            promoted = chal_wins >= 28  # >55% of 50 games

            pct = f"{chal_wins / 50 * 100:.0f}%"
            promo_marker = " ← NEW CHAMPION" if promoted else ""
            print(f"  Games: 50 | Champion wins: {champ_wins} | Challenger wins: {chal_wins} ({pct}){promo_marker}")

            if promoted:
                champion = challenger

            elapsed = time.time() - t_start
            elapsed_str = f"{int(elapsed // 60)}m{int(elapsed % 60)}s"
            print(f"  Best so far: {format_config(champion)} | Rounds run: {round_num} | Elapsed: {elapsed_str}\n")

            log_entry = {
                "round": round_num,
                "champion": dataclasses.asdict(pre_round_champion),
                "challenger": dataclasses.asdict(challenger),
                "champion_wins": champ_wins,
                "challenger_wins": chal_wins,
                "draws": draws,
                "promoted": promoted,
                "elapsed_s": int(elapsed),
            }
            with open(log_path, "a") as f:
                f.write(json.dumps(log_entry) + "\n")

    except KeyboardInterrupt:
        elapsed = time.time() - t_start
        print(f"\nStopped after {round_num} rounds ({elapsed:.1f}s).")
        print(f"Final champion: {format_config(champion)}")


if __name__ == "__main__":
    main()
