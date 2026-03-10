# Battlesnake NJIT 2026

A competitive AI bot for [Battlesnake](https://play.battlesnake.com/) — a real-time multiplayer game where snakes compete for food and survival on an 11×11 board. Built for **Standard mode** (4 snakes, 500ms move deadline).

The bot is designed to play at a high level using a custom game-tree search engine written in C++, called from a Python web server via `ctypes`.

---

## How It Works

Every turn, the Battlesnake platform sends a JSON snapshot of the board to the server. The bot must respond with a move (`up`, `down`, `left`, or `right`) within **500ms** — including network round-trip time. Missing the deadline means repeating the last move, which can be fatal.

```
Battlesnake Platform
       │  POST /move (JSON board state)
       ▼
  Python (FastAPI)
  ├─ Parse JSON into C struct
  ├─ Track game state (who ate last turn, etc.)
  └─ Call C++ engine via ctypes
       │
       ▼
  C++ Engine (~420ms budget)
  ├─ Build bitboard representation
  ├─ Run iterative deepening minimax
  └─ Return best direction (0–3)
       │
       ▼
  {"move": "right"}  →  Battlesnake Platform
```

---

## Architecture

**Python server** (`server.py`) handles the HTTP layer using FastAPI. It parses the Battlesnake JSON into a flat C struct (`CBoard`) and calls into the compiled C++ engine via `ctypes`. It also tracks inter-turn state (e.g., whether a snake ate last turn, which changes tail behavior).

**C++ engine** (`cpp/engine.h`) contains the full game intelligence — board representation, simulation, evaluation, and search. It's compiled into a shared library (`libsnake.so` / `libsnake.dll`) and loaded at startup.

---

## Engine Deep Dive

### Bitboard Representation

The 11×11 board (121 cells) is encoded as a 128-bit value using two `uint64_t` integers. This lets the engine perform operations on the entire board in a handful of CPU instructions — checking collisions, expanding frontiers, and masking regions are all single bitwise ops.

```
Bit index = y * 11 + x
(0,0) = bottom-left  |  (10,10) = top-right
```

### Flood Fill

Board reachability is computed via a bitboard-based BFS — expanding all four directions simultaneously using bit shifts and masks. This runs in O(board diameter) time with no heap allocation, making it fast enough to call many times per search.

### Voronoi Territory Evaluation

The evaluator runs a simultaneous multi-source BFS from all snake heads to compute **Voronoi territory** — the set of cells each snake would reach first assuming optimal movement. This gives a much more accurate measure of board control than simply counting reachable squares.

### Paranoid Minimax with Alpha-Beta Pruning

The search uses **paranoid minimax**: our snake maximizes its score while all opponents are treated as a coordinated adversary minimizing it. Alpha-beta pruning cuts branches that can't affect the final decision, enabling deeper search within the time budget.

**Iterative deepening** runs the search at depth 1, 2, 3… and saves the best move from the last completed depth. If time runs out mid-search, the previous best move is used as a safe fallback.

### Evaluation Heuristic

Each board state is scored using a weighted combination of features:

| Feature | Weight | Notes |
|---|---|---|
| Voronoi territory (flood fill area) | 0.12 | Primary measure of board control |
| Trapped penalty | −500 | Triggered when space < body length |
| Length advantage | 7.0 | Longer snake = safer head-to-head |
| Food proximity | 0.2 | Active only when health < 50 |
| Edge proximity | −4.0 / −1.5 | Penalizes walls and near-wall positions |
| Corner penalty | −5.0 | Corners are especially dangerous |
| Aggression | 3.0 | Chase smaller snakes, evade larger ones |
| Kill bonus | 20.0 | Per eliminated opponent |

---

## Tech Stack

| Layer | Technology |
|---|---|
| Web server | Python 3, FastAPI, Uvicorn |
| Game engine | C++17, compiled as a shared library |
| Interop | Python `ctypes` — zero-copy struct passing |
| Build | `g++ -O2 -shared` via `build.sh` |

---

## Setup & Run

```bash
# 1. Install Python dependencies
pip install fastapi uvicorn

# 2. Compile the C++ engine
bash build.sh

# 3. Start the server (default port 8080)
python server.py
```

### Local Testing

Run a solo game:
```bash
battlesnake play -W 11 -H 11 --name me --url http://localhost:8080
```

Run a full 4-snake game with browser visualization:
```bash
battlesnake play -W 11 -H 11 --browser \
  --name me  --url http://localhost:8080 \
  --name b1  --url http://localhost:8080 \
  --name b2  --url http://localhost:8080 \
  --name b3  --url http://localhost:8080
```

Run engine smoke tests:
```bash
python test_engine.py
```

---

## Project Structure

```
├── server.py          # FastAPI server — HTTP, JSON parsing, C++ bridge
├── build.sh           # Compiles C++ → libsnake.so / libsnake.dll
├── test_engine.py     # Smoke tests (wall avoidance, food-seeking, 4-snake scenarios)
├── cpp/
│   ├── engine.h       # Entire C++ engine (header-only)
│   └── engine.cpp     # Entry point — just #includes engine.h
└── CLAUDE.md          # Developer notes
```

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `libsnake.so not found` | Run `bash build.sh` |
| Snake always moves down | Check JSON coordinate parsing — print `data["you"]["body"]` in `server.py` |
| Snake times out | Reduce `TIMEOUT_MS` in `server.py` (currently 400ms budget) |
| Compilation errors | Ensure g++ 7+ with C++17: `g++ --version` |
