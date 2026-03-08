"""
Stress Test Runner for BattleSnake
===================================
Spawns snake servers, runs batch games via battlesnake CLI,
and reports win rates, avg game length, and death stats.

Usage:
    python stress_test.py                     # Run all matchups, 20 games each
    python stress_test.py --games 50          # 50 games per matchup
    python stress_test.py --mode 1v1          # Only 1v1 matchups
    python stress_test.py --mode ffa          # Only 4-snake FFA
    python stress_test.py --mode gauntlet     # Your snake vs all tough opponents
    python stress_test.py --opponents random astar  # Specific opponents only
"""

import argparse
import json
import os
import random
import signal
import subprocess
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).parent
BATTLESNAKE_EXE = PROJECT_ROOT / "battlesnake.exe"
MAIN_SNAKE_CMD = [sys.executable, str(PROJECT_ROOT / "server.py")]
MAIN_SNAKE_PORT = 8000

OPPONENTS = {
    "random":       {"cmd": [sys.executable, str(PROJECT_ROOT / "test_opps" / "random_snake.py")],       "port": 8002},
    "astar":        {"cmd": [sys.executable, str(PROJECT_ROOT / "test_opps" / "astar_snake.py")],        "port": 8003},
    "aggressive":   {"cmd": [sys.executable, str(PROJECT_ROOT / "test_opps" / "aggressive_snake.py")],   "port": 8004},
    "space_denial": {"cmd": [sys.executable, str(PROJECT_ROOT / "test_opps" / "space_denial_snake.py")], "port": 8005},
    "trap":         {"cmd": [sys.executable, str(PROJECT_ROOT / "test_opps" / "trap_snake.py")],         "port": 8006},
    "minimax":      {"cmd": [sys.executable, str(PROJECT_ROOT / "test_opps" / "minimax_snake.py")],      "port": 8007},
}

OUTPUT_FILE = PROJECT_ROOT / "_game_output.json"


# ---------------------------------------------------------------------------
# Server management
# ---------------------------------------------------------------------------

def wait_for_server(port, timeout=10):
    """Wait until a server responds on the given port."""
    import urllib.request
    start = time.time()
    while time.time() - start < timeout:
        try:
            urllib.request.urlopen(f"http://localhost:{port}/", timeout=2)
            return True
        except Exception:
            time.sleep(0.3)
    return False


def start_server(cmd, port):
    """Start a snake server as a subprocess."""
    full_cmd = cmd + [str(port)]
    proc = subprocess.Popen(
        full_cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0,
    )
    if not wait_for_server(port):
        proc.kill()
        raise RuntimeError(f"Server on port {port} failed to start")
    return proc


def kill_proc(proc):
    """Kill a subprocess."""
    try:
        if sys.platform == "win32":
            proc.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            proc.terminate()
        proc.wait(timeout=3)
    except Exception:
        proc.kill()


# ---------------------------------------------------------------------------
# Game execution
# ---------------------------------------------------------------------------

def run_game(snake_configs, seed=None):
    """
    Run a single battlesnake game.
    snake_configs: list of {"name": str, "url": str}
    Returns: {"winner": name or None, "turns": int, "alive": [names]}
    """
    cmd = [str(BATTLESNAKE_EXE), "play", "-W", "11", "-H", "11"]

    for sc in snake_configs:
        cmd += ["--name", sc["name"], "--url", sc["url"]]

    if seed is not None:
        cmd += ["--seed", str(seed)]

    cmd += ["--output", str(OUTPUT_FILE)]

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=120,
    )

    # Parse the output JSON file
    turns = 0
    alive_names = []
    winner = None

    if OUTPUT_FILE.exists():
        try:
            with open(OUTPUT_FILE) as f:
                # The output file contains one JSON object per line (NDJSON)
                last_frame = None
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            last_frame = json.loads(line)
                        except json.JSONDecodeError:
                            continue

                if last_frame:
                    # Extract turn count
                    if "Turn" in last_frame:
                        turns = last_frame["Turn"]
                    elif "turn" in last_frame:
                        turns = last_frame["turn"]

                    # Find alive snakes in final frame
                    board_data = last_frame.get("Board", last_frame.get("board", {}))
                    snakes_data = board_data.get("Snakes", board_data.get("snakes", []))

                    for s in snakes_data:
                        # In the battlesnake CLI output, dead snakes have
                        # EliminatedCause set or empty body
                        elim = s.get("EliminatedCause", s.get("eliminatedCause", ""))
                        body = s.get("Body", s.get("body", []))
                        name = s.get("Name", s.get("name", ""))
                        if not elim and len(body) > 0:
                            alive_names.append(name)

                    if len(alive_names) == 1:
                        winner = alive_names[0]

        except Exception as e:
            print(f"  Warning: failed to parse game output: {e}")
        finally:
            try:
                OUTPUT_FILE.unlink()
            except Exception:
                pass

    # Fallback: parse CLI stdout/stderr for winner
    if winner is None and turns == 0:
        output = result.stdout + result.stderr
        for line in output.split("\n"):
            if "wins" in line.lower() or "winner" in line.lower():
                # Try to extract winner name
                for sc in snake_configs:
                    if sc["name"].lower() in line.lower():
                        winner = sc["name"]
                        break

    return {"winner": winner, "turns": turns, "alive": alive_names}


# ---------------------------------------------------------------------------
# Matchup runners
# ---------------------------------------------------------------------------

def run_1v1_matchups(n_games, opponent_names):
    """Run 1v1 matches: your snake vs each opponent."""
    print("\n" + "=" * 60)
    print(f"  1v1 MATCHUPS ({n_games} games each)")
    print("=" * 60)

    results = {}

    for opp_name in opponent_names:
        if opp_name not in OPPONENTS:
            print(f"  Unknown opponent: {opp_name}, skipping")
            continue

        opp = OPPONENTS[opp_name]
        print(f"\n  vs {opp_name} (port {opp['port']})...")

        # Start opponent server
        opp_proc = start_server(opp["cmd"], opp["port"])

        wins, losses, draws = 0, 0, 0
        total_turns = 0

        try:
            for g in range(n_games):
                seed = random.randint(1, 2**31)
                configs = [
                    {"name": "you", "url": f"http://localhost:{MAIN_SNAKE_PORT}"},
                    {"name": opp_name, "url": f"http://localhost:{opp['port']}"},
                ]

                try:
                    result = run_game(configs, seed=seed)
                except subprocess.TimeoutExpired:
                    print(f"    Game {g+1} timed out")
                    continue

                total_turns += result["turns"]

                if result["winner"] == "you":
                    wins += 1
                elif result["winner"] == opp_name:
                    losses += 1
                else:
                    draws += 1

                if (g + 1) % 5 == 0:
                    print(f"    Game {g+1}/{n_games} — W:{wins} L:{losses} D:{draws}")

        finally:
            kill_proc(opp_proc)

        total = wins + losses + draws
        avg_turns = total_turns / max(total, 1)
        win_rate = wins / max(total, 1)

        results[opp_name] = {
            "wins": wins, "losses": losses, "draws": draws,
            "total": total, "win_rate": win_rate, "avg_turns": avg_turns,
        }

        print(f"  Result: {wins}/{total} wins ({win_rate:.1%}) "
              f"avg {avg_turns:.0f} turns")

    return results


def run_ffa(n_games, opponent_names):
    """Run 4-snake free-for-all: you + 3 opponents."""
    # Pick up to 3 opponents
    opps = [n for n in opponent_names if n in OPPONENTS][:3]
    if len(opps) < 1:
        print("  Not enough opponents for FFA")
        return {}

    print("\n" + "=" * 60)
    print(f"  FFA: you vs {', '.join(opps)} ({n_games} games)")
    print("=" * 60)

    # Start opponent servers
    opp_procs = []
    for opp_name in opps:
        opp = OPPONENTS[opp_name]
        opp_procs.append((opp_name, start_server(opp["cmd"], opp["port"])))

    first_place, survived, eliminated = 0, 0, 0
    total_turns = 0

    try:
        for g in range(n_games):
            seed = random.randint(1, 2**31)
            configs = [{"name": "you", "url": f"http://localhost:{MAIN_SNAKE_PORT}"}]
            for opp_name in opps:
                opp = OPPONENTS[opp_name]
                configs.append({"name": opp_name, "url": f"http://localhost:{opp['port']}"})

            try:
                result = run_game(configs, seed=seed)
            except subprocess.TimeoutExpired:
                print(f"    Game {g+1} timed out")
                continue

            total_turns += result["turns"]

            if result["winner"] == "you":
                first_place += 1
            elif "you" in result["alive"]:
                survived += 1
            else:
                eliminated += 1

            if (g + 1) % 5 == 0:
                total = first_place + survived + eliminated
                print(f"    Game {g+1}/{n_games} — "
                      f"1st:{first_place} Alive:{survived} Dead:{eliminated}")

    finally:
        for _, proc in opp_procs:
            kill_proc(proc)

    total = first_place + survived + eliminated
    avg_turns = total_turns / max(total, 1)

    print(f"\n  Results over {total} FFA games:")
    print(f"    1st place:  {first_place}/{total} ({first_place/max(total,1):.1%})")
    print(f"    Survived:   {survived}/{total} ({survived/max(total,1):.1%})")
    print(f"    Eliminated: {eliminated}/{total} ({eliminated/max(total,1):.1%})")
    print(f"    Avg game:   {avg_turns:.0f} turns")

    return {
        "first_place": first_place, "survived": survived,
        "eliminated": eliminated, "total": total, "avg_turns": avg_turns,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="BattleSnake Stress Tester")
    parser.add_argument("--games", type=int, default=20, help="Games per matchup (default 20)")
    parser.add_argument("--mode", choices=["1v1", "ffa", "gauntlet", "all"], default="all",
                        help="Test mode (default: all)")
    parser.add_argument("--opponents", nargs="+",
                        default=list(OPPONENTS.keys()),
                        help="Which opponents to use")
    args = parser.parse_args()

    if not BATTLESNAKE_EXE.exists():
        print(f"ERROR: battlesnake.exe not found at {BATTLESNAKE_EXE}")
        sys.exit(1)

    print("=" * 60)
    print("  BATTLESNAKE STRESS TEST")
    print(f"  Games per matchup: {args.games}")
    print(f"  Mode: {args.mode}")
    print(f"  Opponents: {', '.join(args.opponents)}")
    print("=" * 60)

    # Start main snake server
    print("\nStarting your snake on port 8000...")
    main_proc = start_server(MAIN_SNAKE_CMD, MAIN_SNAKE_PORT)

    try:
        all_results = {}

        if args.mode in ("1v1", "all"):
            all_results["1v1"] = run_1v1_matchups(args.games, args.opponents)

        if args.mode in ("ffa", "all"):
            # Use the 3 toughest opponents for FFA
            ffa_opps = [o for o in ["aggressive", "space_denial", "trap", "minimax"]
                        if o in args.opponents][:3]
            if ffa_opps:
                all_results["ffa"] = run_ffa(args.games, ffa_opps)

        if args.mode == "gauntlet":
            gauntlet_opps = [o for o in ["aggressive", "space_denial", "trap", "minimax"]
                            if o in args.opponents]
            all_results["gauntlet_1v1"] = run_1v1_matchups(args.games, gauntlet_opps)
            if len(gauntlet_opps) >= 3:
                all_results["gauntlet_ffa"] = run_ffa(args.games, gauntlet_opps[:3])

        # Summary
        print("\n" + "=" * 60)
        print("  FINAL SUMMARY")
        print("=" * 60)

        if "1v1" in all_results:
            print("\n  1v1 Results:")
            for opp, r in sorted(all_results["1v1"].items(),
                                  key=lambda x: x[1]["win_rate"], reverse=True):
                print(f"    vs {opp:15s}: {r['wins']}/{r['total']} wins "
                      f"({r['win_rate']:.1%})  avg {r['avg_turns']:.0f} turns")

        if "ffa" in all_results:
            r = all_results["ffa"]
            t = r["total"]
            print(f"\n  FFA Results ({t} games):")
            print(f"    1st place:  {r['first_place']}/{t} ({r['first_place']/max(t,1):.1%})")
            print(f"    Survived:   {r['survived']}/{t} ({r['survived']/max(t,1):.1%})")
            print(f"    Eliminated: {r['eliminated']}/{t} ({r['eliminated']/max(t,1):.1%})")

        print("\n" + "=" * 60)

    finally:
        kill_proc(main_proc)
        # Clean up any stray output files
        if OUTPUT_FILE.exists():
            try:
                OUTPUT_FILE.unlink()
            except Exception:
                pass


if __name__ == "__main__":
    main()
