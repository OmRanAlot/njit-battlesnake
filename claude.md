# CLAUDE.md — Battlesnake C++ Engine Project

## What This Is

A competitive Battlesnake bot for **Standard mode** (4 snakes, 11×11 board, 500ms timeout).
Architecture: **FastAPI (Python) + C++ search engine (via ctypes)**.

## Project Structure

```
battlesnake/
├── server.py          # FastAPI server — HTTP endpoints, JSON parsing, calls C++
├── build.sh           # Compiles C++ → libsnake.so
├── libsnake.so        # Compiled shared library (rebuild with: bash build.sh)
├── test_engine.py     # Smoke tests for the C++ engine
├── cpp/
│   ├── engine.h       # ALL C++ code: board state, flood fill, eval, minimax, C API
│   └── engine.cpp     # Just #includes engine.h
└── CLAUDE.md          # This file
```

## Build & Run

```bash
bash build.sh                # compile C++ engine (MUST run after any .h/.cpp changes)
python server.py             # start server on port 8000
battlesnake play -W 11 -H 11 --name me --url http://localhost:8000  # test solo
```

For 4-snake testing:
```bash
battlesnake play -W 11 -H 11 --browser \
  --name me --url http://localhost:8000 \
  --name b1 --url http://localhost:8000 \
  --name b2 --url http://localhost:8000 \
  --name b3 --url http://localhost:8000
```

## Critical Rules — READ BEFORE EDITING

### Battlesnake API

- Server must respond to: `GET /` (metadata), `POST /start`, `POST /move`, `POST /end`
- `/move` receives full board state as JSON, must return `{"move": "up"|"down"|"left"|"right"}`
- **500ms timeout** — if you miss it, the engine repeats your last move (possibly fatal)
- Budget ~80ms for network+JSON overhead, so C++ gets ~420ms max

### Battlesnake Game Rules (Standard Mode)

- 11×11 board, 4 snakes, snakes start at length 3 with 100 health
- Health drains 1/turn, resets to 100 when eating food, eating grows body by 1 next turn
- **Turn resolution order** (this order is MANDATORY):
  1. All snakes move simultaneously (shift body forward, new head)
  2. Health reduced by 1
  3. Food consumed (health=100, snake grows NEXT turn)
  4. Dead snakes eliminated: out of bounds → starvation (health≤0) → body collision → head-to-head
- **Head-to-head**: longer snake wins. Equal length = both die.
- **Tail behavior**: normally passable (moves away). After eating, tail stays for 1 extra turn (body grows).
- **Body collision**: head hitting ANY body segment (own or opponent) except heads = death

### C++ Engine Architecture

Everything is in `cpp/engine.h`. Key components:

- **Bitboard** — 128-bit (two uint64_t) representation of the 11×11=121 cell board
- **flood_fill()** — bitboard-based BFS, expands all 4 directions via bit shifts. O(board diameter).
- **evaluate()** — heuristic scorer with these weighted features:
  - Space advantage (flood fill area, weight 0.12) — MOST IMPORTANT
  - Trapped penalty (-500 when space < body length)
  - Length advantage (weight 7.0)
  - Food proximity (weight 0.2, activates when health < 50)
  - Edge penalty (-4.0 for walls, -1.5 for near-wall)
  - Corner penalty (-5.0)
  - Aggression (3.0 — chase smaller snakes, flee larger)
  - Kill bonus (20.0 per eliminated opponent)
- **minimax()** — paranoid minimax with alpha-beta pruning. We maximize; opponents assumed to pick their flood-fill-best move (not fully adversarial — see improvement list).
- **find_best_move()** — iterative deepening wrapper. Searches depth 1, 2, 3... until timeout. Falls back to flood-fill-best move if depth 1 doesn't complete.
- **C API** — `get_best_move(CBoard*)` is the entry point called from Python via ctypes.

### Python Server (server.py)

- FastAPI with 4 endpoints
- Parses Battlesnake JSON into CBoard ctypes struct
- Tracks `ate_last_turn` by comparing body lengths between turns
- Calls `engine.get_best_move()` and returns direction string

### Coord System

- (0,0) is bottom-left, (10,10) is top-right
- Bit index = y * 11 + x
- UP = y+1, DOWN = y-1, LEFT = x-1, RIGHT = x+1

## Known Limitations & Improvement Priorities

Ordered by impact. Do these in order:

### 1. Opponent modeling is simplistic (HIGH IMPACT)
Currently opponents pick their flood-fill-best move at each search node. This means the search doesn't consider worst-case opponent plays. Fix: enumerate top 2-3 opponent moves and minimize over them (true paranoid minimax). This multiplies branching factor by ~3 per opponent but makes the search much more tactically accurate.

### 2. No Voronoi territory in eval (MEDIUM IMPACT)
Flood fill counts reachable squares but ignores who gets there first. Add simultaneous BFS from all heads — cells you reach first are "yours." This is a much better measure of board control than raw flood fill.

### 3. No tail-chasing fallback (MEDIUM IMPACT)
When no safe food path exists and health is okay, the snake should default to chasing its own tail (always a safe destination since tail moves away). Add A* from head to tail as an eval feature.

### 4. No transposition table (MEDIUM IMPACT)
Positions reached via different move orders get re-searched. Add Zobrist hashing + a fixed-size TT (2^20 entries) to cache results. Enables ~1.5× deeper search.

### 5. Food spawn not simulated (LOW IMPACT)
The simulator doesn't spawn new food after consumption. This slightly distorts long lookahead but doesn't matter much at depth 3-5.

### 6. Move ordering could be better (LOW IMPACT)
Currently ordered by flood fill score. Could add: PV-move from previous iteration, killer heuristic, history heuristic.

## Testing

```bash
python test_engine.py    # run smoke tests
```

Tests cover: wall avoidance, self-collision avoidance, space maximization, food-seeking when hungry, 4-snake scenarios, and timeout compliance.

To add a test, create a board state with `make_snake()` and `test()` helper functions in test_engine.py.

## Common Issues

- **"libsnake.so not found"** — run `bash build.sh`
- **Snake always goes down** — check that JSON parsing correctly maps body coordinates. Print `data["you"]["body"]` in server.py to verify.
- **Snake times out** — reduce `timeout_ms` safety margin in server.py (currently 80ms). Check if C++ is doing excessive flood fills in eval.
- **Compilation errors** — ensure g++ supports C++17: `g++ --version` should be 7+
- **Wrong move direction** — coordinate system: UP=y+1, DOWN=y-1. Battlesnake API uses this convention. Double-check DX/DY arrays in engine.h match.

## Style Notes

- All C++ is in engine.h (header-only for simplicity). engine.cpp just includes it.
- Use `inline` for all functions in the header to avoid multiple definition errors.
- Bitboard ops must mask with FULL_MASK (121 bits) and edge masks to prevent wraparound.
- Always rebuild after C++ changes: `bash build.sh`
- The `CBoard`/`CSnake` structs in engine.h MUST match the ctypes definitions in server.py exactly (field order, types, array sizes). If you change one, change both.