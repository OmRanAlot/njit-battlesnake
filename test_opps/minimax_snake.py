"""
Minimax Snake — the toughest test opponent.
Unlike other test snakes that use single-move heuristics, this one actually
searches 2-3 moves ahead with alpha-beta pruning. It simulates what happens
after its move AND the opponent's response before evaluating.

Port 8007, color purple (#800080).
"""

import sys
import time
import random
from collections import deque
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import uvicorn

app = FastAPI()

DIRS = {"up": (0, 1), "down": (0, -1), "left": (-1, 0), "right": (1, 0)}
DIR_LIST = ["up", "down", "left", "right"]
DX = [0, 0, -1, 1]
DY = [1, -1, 0, 0]

TIMEOUT_S = 0.38  # 380ms hard limit, leaves 120ms for HTTP


@app.get("/")
def index():
    return JSONResponse({
        "apiversion": "1",
        "author": "MiniMaxBot",
        "color": "#800080",
        "head": "beluga",
        "tail": "bolt",
        "version": "1.0.0",
    })


@app.post("/start")
async def start(request: Request):
    return JSONResponse({"ok": True})


# ---------------------------------------------------------------------------
# Game state representation (lightweight, copyable)
# ---------------------------------------------------------------------------

class Snake:
    __slots__ = ("body", "health", "sid", "alive")

    def __init__(self, body, health, sid, alive=True):
        self.body = list(body)  # list of (x, y), head first
        self.health = health
        self.sid = sid
        self.alive = alive

    def copy(self):
        s = Snake(self.body[:], self.health, self.sid, self.alive)
        return s

    @property
    def head(self):
        return self.body[0]

    @property
    def length(self):
        return len(self.body)


class Board:
    __slots__ = ("snakes", "food", "width", "height")

    def __init__(self, snakes, food, width, height):
        self.snakes = snakes
        self.food = set(food)
        self.width = width
        self.height = height

    def copy(self):
        return Board(
            [s.copy() for s in self.snakes],
            set(self.food),
            self.width,
            self.height,
        )


def parse_board(data):
    board = data["board"]
    you = data["you"]
    w, h = board["width"], board["height"]

    snakes = []
    my_idx = 0
    for i, s in enumerate(board["snakes"]):
        body = [(p["x"], p["y"]) for p in s["body"]]
        snakes.append(Snake(body, s["health"], s["id"], True))
        if s["id"] == you["id"]:
            my_idx = i

    food = [(f["x"], f["y"]) for f in board["food"]]
    return Board(snakes, food, w, h), my_idx


# ---------------------------------------------------------------------------
# Board utilities
# ---------------------------------------------------------------------------

def get_obstacles(board):
    """All snake body cells (except tails which will move)."""
    obs = set()
    for s in board.snakes:
        if not s.alive:
            continue
        for i, p in enumerate(s.body):
            if i < len(s.body) - 1:
                obs.add(p)
    return obs


def in_bounds(x, y, w, h):
    return 0 <= x < w and 0 <= y < h


def get_safe_moves(snake, board, obstacles):
    """Return list of (dir_idx, nx, ny) for valid moves."""
    hx, hy = snake.head
    moves = []
    for d in range(4):
        nx, ny = hx + DX[d], hy + DY[d]
        if in_bounds(nx, ny, board.width, board.height) and (nx, ny) not in obstacles:
            moves.append((d, nx, ny))
    return moves


def flood_fill_count(start, w, h, obstacles):
    """BFS flood fill returning reachable cell count."""
    visited = set()
    queue = deque([start])
    visited.add(start)
    while queue:
        cx, cy = queue.popleft()
        for dx, dy in [(0, 1), (0, -1), (-1, 0), (1, 0)]:
            nx, ny = cx + dx, cy + dy
            if 0 <= nx < w and 0 <= ny < h and (nx, ny) not in obstacles and (nx, ny) not in visited:
                visited.add((nx, ny))
                queue.append((nx, ny))
    return len(visited)


# ---------------------------------------------------------------------------
# Move simulation
# ---------------------------------------------------------------------------

def apply_move(board, snake_idx, dir_idx):
    """Apply a move to a snake on the board (mutates in place)."""
    s = board.snakes[snake_idx]
    if not s.alive:
        return

    hx, hy = s.head
    nx, ny = hx + DX[dir_idx], hy + DY[dir_idx]

    # Move body forward
    s.body.insert(0, (nx, ny))
    s.health -= 1

    # Check food
    if (nx, ny) in board.food:
        s.health = 100
        board.food.discard((nx, ny))
    else:
        s.body.pop()  # remove tail if didn't eat


def resolve_deaths(board):
    """Check for deaths: out of bounds, starvation, body collision, head-to-head."""
    dead = [False] * len(board.snakes)
    w, h = board.width, board.height

    # Build body set (excluding heads) for collision checks
    for i, s in enumerate(board.snakes):
        if not s.alive:
            dead[i] = True
            continue
        hx, hy = s.head

        # Out of bounds
        if not in_bounds(hx, hy, w, h):
            dead[i] = True
            continue

        # Starvation
        if s.health <= 0:
            dead[i] = True
            continue

        # Body collision (with any snake body segment, excluding heads)
        for j, other in enumerate(board.snakes):
            if not other.alive:
                continue
            start = 1 if i == j else 1  # skip other's head (handled below)
            for k in range(start, len(other.body)):
                if other.body[k] == (hx, hy):
                    dead[i] = True
                    break
            if dead[i]:
                break

    # Head-to-head
    for i in range(len(board.snakes)):
        if not board.snakes[i].alive or dead[i]:
            continue
        for j in range(i + 1, len(board.snakes)):
            if not board.snakes[j].alive or dead[j]:
                continue
            if board.snakes[i].head == board.snakes[j].head:
                li, lj = board.snakes[i].length, board.snakes[j].length
                if li > lj:
                    dead[j] = True
                elif lj > li:
                    dead[i] = True
                else:
                    dead[i] = True
                    dead[j] = True

    for i in range(len(board.snakes)):
        if dead[i]:
            board.snakes[i].alive = False


# ---------------------------------------------------------------------------
# Evaluation function
# ---------------------------------------------------------------------------

def evaluate(board, my_idx):
    """Heuristic board evaluation from our perspective."""
    me = board.snakes[my_idx]
    if not me.alive:
        return -10000.0

    alive_opps = [s for s in board.snakes if s.alive and s.sid != me.sid]
    if not alive_opps:
        return 10000.0

    score = 0.0
    obstacles = get_obstacles(board)
    hx, hy = me.head
    w, h = board.width, board.height

    # 1. Space (most important)
    my_space = flood_fill_count(me.head, w, h, obstacles)
    score += my_space * 1.5

    # Trapped penalty
    if my_space < me.length * 2:
        ratio = my_space / max(me.length * 2, 1)
        score -= (1.0 - ratio) * 500.0

    # 2. Length advantage
    for opp in alive_opps:
        score += (me.length - opp.length) * 8.0

    # 3. Food proximity (always on, scaled by health)
    if board.food:
        min_dist = min(abs(hx - fx) + abs(hy - fy) for fx, fy in board.food)
        health_weight = 0.1 if me.health > 50 else (0.3 if me.health > 20 else 1.0)
        score -= min_dist * health_weight

    # 4. Head-to-head danger
    for opp in alive_opps:
        ohx, ohy = opp.head
        dist = abs(hx - ohx) + abs(hy - ohy)
        if dist <= 2:
            if opp.length >= me.length:
                score -= 150.0 / max(dist, 1)
            else:
                score += 30.0 / max(dist, 1)  # kill opportunity

    # 5. Aggression
    for opp in alive_opps:
        ohx, ohy = opp.head
        dist = abs(hx - ohx) + abs(hy - ohy)
        if dist > 0:
            if me.length > opp.length + 1:
                score += 5.0 / dist  # chase hard
            elif opp.length > me.length:
                score -= 3.0 / dist  # flee

    # 6. Edge penalty
    if hx == 0 or hx == w - 1:
        score -= 2.0
    if hy == 0 or hy == h - 1:
        score -= 2.0

    # 7. Kill bonus
    dead_count = sum(1 for s in board.snakes if not s.alive and s.sid != me.sid)
    score += dead_count * 30.0

    return score


# ---------------------------------------------------------------------------
# Minimax with alpha-beta pruning
# ---------------------------------------------------------------------------

def minimax(board, my_idx, depth, alpha, beta, maximizing, deadline):
    """Paranoid minimax: we maximize, all opponents minimize."""
    if time.time() >= deadline:
        return None  # timeout sentinel

    me = board.snakes[my_idx]
    if not me.alive:
        return -10000.0

    alive = [s for s in board.snakes if s.alive]
    if len(alive) <= 1:
        return evaluate(board, my_idx)

    if depth == 0:
        return evaluate(board, my_idx)

    obstacles = get_obstacles(board)

    if maximizing:
        # Our turn
        moves = get_safe_moves(me, board, obstacles)
        if not moves:
            return -10000.0

        # Order moves by flood fill (best first)
        move_scores = []
        for d, nx, ny in moves:
            space = flood_fill_count((nx, ny), board.width, board.height, obstacles)
            move_scores.append((space, d, nx, ny))
        move_scores.sort(reverse=True)

        best = -100000.0
        for _, d, nx, ny in move_scores:
            child = board.copy()
            apply_move(child, my_idx, d)

            # Opponents each pick their best flood-fill move (fast approx)
            for i, s in enumerate(child.snakes):
                if i == my_idx or not s.alive:
                    continue
                child_obs = get_obstacles(child)
                opp_moves = get_safe_moves(s, child, child_obs)
                if opp_moves:
                    # Pick move maximizing opponent's space
                    best_opp = max(
                        opp_moves,
                        key=lambda m: flood_fill_count(
                            (m[1], m[2]), child.width, child.height, child_obs
                        ),
                    )
                    apply_move(child, i, best_opp[0])
                else:
                    apply_move(child, i, 0)  # doomed

            resolve_deaths(child)

            val = minimax(child, my_idx, depth - 1, alpha, beta, True, deadline)
            if val is None:
                return None  # timeout

            if val > best:
                best = val
            if best > alpha:
                alpha = best
            if alpha >= beta:
                break

        return best

    return evaluate(board, my_idx)


# ---------------------------------------------------------------------------
# Top-level move selection with iterative deepening
# ---------------------------------------------------------------------------

@app.post("/move")
async def move(request: Request):
    data = await request.json()
    board, my_idx = parse_board(data)
    me = board.snakes[my_idx]

    obstacles = get_obstacles(board)
    moves = get_safe_moves(me, board, obstacles)

    if not moves:
        return JSONResponse({"move": "up"})

    # Order by flood fill
    move_scores = []
    for d, nx, ny in moves:
        space = flood_fill_count((nx, ny), board.width, board.height, obstacles)
        move_scores.append((space, d, nx, ny))
    move_scores.sort(reverse=True)

    best_move = DIR_LIST[move_scores[0][1]]  # fallback: best flood fill
    deadline = time.time() + TIMEOUT_S

    # Iterative deepening: depth 1, 2, 3...
    for depth in range(1, 8):
        if time.time() >= deadline:
            break

        depth_best_dir = move_scores[0][1]
        depth_best_score = -100000.0
        alpha = -100000.0

        timed_out = False
        for _, d, nx, ny in move_scores:
            child = board.copy()
            apply_move(child, my_idx, d)

            # Opponents move (flood fill best)
            for i, s in enumerate(child.snakes):
                if i == my_idx or not s.alive:
                    continue
                child_obs = get_obstacles(child)
                opp_moves = get_safe_moves(s, child, child_obs)
                if opp_moves:
                    best_opp = max(
                        opp_moves,
                        key=lambda m: flood_fill_count(
                            (m[1], m[2]), child.width, child.height, child_obs
                        ),
                    )
                    apply_move(child, i, best_opp[0])
                else:
                    apply_move(child, i, 0)

            resolve_deaths(child)

            val = minimax(child, my_idx, depth - 1, alpha, 100000.0, True, deadline)
            if val is None:
                timed_out = True
                break

            if val > depth_best_score:
                depth_best_score = val
                depth_best_dir = d

            if val > alpha:
                alpha = val

        if not timed_out:
            best_move = DIR_LIST[depth_best_dir]

    return JSONResponse({"move": best_move})


@app.post("/end")
async def end(request: Request):
    return JSONResponse({"ok": True})


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8007
    print(f"Starting MiniMax Snake on port {port}...")
    uvicorn.run(app, host="0.0.0.0", port=port)
