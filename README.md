# Battlesnake NJIT 2026

A competitive [Battlesnake](https://play.battlesnake.com/) bot built for **Standard mode** (4 snakes, 11×11 board, 500ms move timeout).

## Architecture

**FastAPI (Python) + C++ search engine (via ctypes)**

- **Python server** (`server.py`) — handles HTTP endpoints, parses the Battlesnake JSON API, and calls into the C++ engine
- **C++ engine** (`cpp/engine.h`) — header-only engine containing the board representation, search algorithm, and evaluation function, compiled into a shared library (`libsnake.so`)

### How It Works

1. Battlesnake platform sends board state as JSON to `POST /move`
2. Python parses JSON into a `CBoard` ctypes struct
3. C++ engine runs **iterative deepening paranoid minimax** with alpha-beta pruning under a ~420ms time budget
4. Engine returns best direction → Python responds with `{"move": "up"|"down"|"left"|"right"}`

### Engine Internals

| Component | Description |
|---|---|
| **Bitboard** | 128-bit (two `uint64_t`) representation of the 11×11 = 121 cell board |
| **Flood fill** | Bitboard-based BFS via bit shifts — O(board diameter) |
| **Evaluation** | Weighted heuristic: space (flood fill), length advantage, food proximity, edge/corner penalties, aggression, kill bonus |
| **Search** | Paranoid minimax + alpha-beta. Iterative deepening (depth 1, 2, 3…) until timeout. Falls back to flood-fill-best if depth 1 doesn't complete |
| **C API** | `get_best_move(CBoard*)` — single entry point called from Python via ctypes |

### Coordinate System

- `(0,0)` = bottom-left, `(10,10)` = top-right
- Bit index = `y * 11 + x`
- UP = y+1, DOWN = y-1, LEFT = x-1, RIGHT = x+1

## Prerequisites

- **Python 3.8+** with `fastapi` and `uvicorn`
- **g++ 7+** with C++17 support
- **Battlesnake CLI** (optional, for local testing) — [install guide](https://github.com/BattlesnakeOfficial/rules/tree/main/cli)

## Setup & Run

```bash
# 1. Install Python dependencies
pip install fastapi uvicorn

# 2. Compile the C++ engine (MUST re-run after any .h/.cpp change)
bash build.sh

# 3. Start the server (port 8000)
python server.py
```

## Local Testing

Solo game (just your snake):
```bash
battlesnake play -W 11 -H 11 --name me --url http://localhost:8000
```

Full 4-snake game with browser visualization:
```bash
battlesnake play -W 11 -H 11 --browser \
  --name me --url http://localhost:8000 \
  --name b1 --url http://localhost:8000 \
  --name b2 --url http://localhost:8000 \
  --name b3 --url http://localhost:8000
```

Run engine smoke tests:
```bash
python test_engine.py
```

## Known Problems & Key Issues

### 1. Opponent Modeling is Simplistic — HIGH IMPACT

Opponents are assumed to pick their flood-fill-best move at each search node. The engine does **not** consider worst-case opponent plays. This means it can be blindsided by aggressive opponents who cut off space intentionally.

**Fix:** Enumerate top 2-3 opponent moves and minimize over them (true paranoid minimax). Trades branching factor (~3× per opponent) for much better tactical accuracy.

## Recently Resolved Issues

### 2. Voronoi Territory in Evaluation
We implemented a simultaneous BFS from all snake heads. The evaluation now measures true board control by calculating cells that we can reach *first*, rather than merely counting reachable cells.

### 3. No Tail-Chasing Fallback — MEDIUM IMPACT

When there's no safe food path and health is fine, the snake has no default safe behavior. Chasing your own tail is always safe (the tail moves away each turn).

**Fix:** Add A* pathfinding from head to own tail as an eval feature / fallback strategy.

### 4. No Transposition Table — MEDIUM IMPACT

Positions reached via different move orders are re-searched from scratch, wasting time.

**Fix:** Add Zobrist hashing + a fixed-size transposition table (2^20 entries) to cache search results. Expected ~1.5× deeper search within the same time budget.

### 5. Food Spawn Not Simulated — LOW IMPACT

The simulator doesn't spawn new food after consumption. Slightly distorts long lookahead but irrelevant at depth 3-5.

### 6. Move Ordering is Basic — LOW IMPACT

Moves are currently ordered only by flood fill score. Better ordering (PV-move from previous iteration, killer heuristic, history heuristic) would improve alpha-beta cutoffs.

## Troubleshooting

| Symptom | Cause & Fix |
|---|---|
| `libsnake.so not found` | Run `bash build.sh` to compile the engine |
| Snake always goes down | JSON parsing is mapping coordinates wrong — print `data["you"]["body"]` in `server.py` to debug |
| Snake times out (>500ms) | Reduce `timeout_ms` safety margin in `server.py` (currently 80ms). Check for excessive flood fills in eval |
| Compilation errors | Ensure g++ supports C++17: `g++ --version` should be 7+ |
| Wrong move direction | Coordinate mismatch — verify DX/DY arrays in `engine.h` match: UP=y+1, DOWN=y-1 |

## Important Dev Notes

- **All C++ lives in `engine.h`** (header-only). `engine.cpp` just `#include`s it.
- Use `inline` on all functions in the header to avoid linker errors.
- **Always rebuild** after C++ changes: `bash build.sh`
- The `CBoard`/`CSnake` structs in `engine.h` **must exactly match** the ctypes definitions in `server.py` (field order, types, array sizes). Change one → change both.
- Bitboard operations must mask with `FULL_MASK` (121 bits) and edge masks to prevent bit wraparound.
