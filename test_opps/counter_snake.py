"""
counter_snake.py — Tuned specifically to beat the NJIT BattleSnake C++ minimax engine.

EXPLOITED VULNERABILITIES:
──────────────────────────────────────────────────────────────────────────────
V1  GROWTH MODE (triggered when we're ≥ target_len + 2):
    Engine eval: food_weight=1.5, always active, chase weight drops 2.5→0.5.
    Engine picks nearest REACHABLE food by Manhattan distance — fully predictable.
    → We race to intercept that exact food, or block its A* path to it.

V2  FLEE PRESSURE (engine flee weight = 9.0/dist from equal/larger snakes):
    At distance 2: engine scores −4.5. At distance 1: −9.0.
    → We sit 2 squares from its head on the center-facing side, herding it
    toward the nearest wall/corner without risking a mutual head-on.

V3  WALL/CORNER AVERSION (edge −4.5, corner −9.0):
    Engine actively avoids walls; being near them costs it badly in eval.
    → Herding toward corners compounds its penalty every single turn.

V4  NO TAIL-CHASING FALLBACK:
    Engine has no tail-chase spiral when space runs out.
    → Once cornered and space-cut, it has no safe cycle and loses.

V5  SPACE (VORONOI) IS ENGINE'S TOP PRIORITY:
    Engine maximizes Voronoi territory above all else.
    → We cut the board so it gets the smaller region. Trapped penalty
    kicks in at space < 2×body_length → −500 scaled score.

PHASES:
  Phase 1 (shorter than target + 2): Grow fast with A* food seeking, avoid conflict.
  Phase 2 (≥ target + 2, growth mode active): Intercept food + herd toward corners.
  Phase 3 (target cornered): Aggressive space denial, hold position, starve it out.

Port: 8008  Color: #DC143C (crimson)
"""

import sys
import heapq
from collections import deque
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import uvicorn

app = FastAPI()

DX = [0, 0, -1, 1]
DY = [1, -1, 0, 0]
DIR_NAMES = ["up", "down", "left", "right"]


@app.get("/")
def index():
    return JSONResponse({
        "apiversion": "1",
        "author": "CounterBot",
        "color": "#DC143C",
        "head": "villain",
        "tail": "sharp",
        "version": "1.0.0",
    })


@app.post("/start")
async def start(request: Request):
    return JSONResponse({"ok": True})


# ---------------------------------------------------------------------------
# Board utilities
# ---------------------------------------------------------------------------

def in_bounds(x, y, w, h):
    return 0 <= x < w and 0 <= y < h


def build_obstacles(board_data):
    """All body segments except tails (tails vacate next turn)."""
    obs = set()
    for s in board_data["snakes"]:
        body = s["body"]
        for i, p in enumerate(body):
            if i < len(body) - 1:
                obs.add((p["x"], p["y"]))
    return obs


def get_moves(x, y, w, h, obstacles):
    """Returns list of (dir_idx, nx, ny) for each valid move."""
    out = []
    for d in range(4):
        nx, ny = x + DX[d], y + DY[d]
        if in_bounds(nx, ny, w, h) and (nx, ny) not in obstacles:
            out.append((d, nx, ny))
    return out


def flood_count(start, w, h, obstacles):
    """BFS flood fill from start; returns reachable cell count."""
    visited = {start}
    q = deque([start])
    while q:
        cx, cy = q.popleft()
        for dx, dy in ((0, 1), (0, -1), (-1, 0), (1, 0)):
            nx, ny = cx + dx, cy + dy
            if in_bounds(nx, ny, w, h) and (nx, ny) not in obstacles and (nx, ny) not in visited:
                visited.add((nx, ny))
                q.append((nx, ny))
    return len(visited)


def bfs_reachable(start, w, h, obstacles):
    """Returns set of all cells reachable from start."""
    visited = {start}
    q = deque([start])
    while q:
        cx, cy = q.popleft()
        for dx, dy in ((0, 1), (0, -1), (-1, 0), (1, 0)):
            nx, ny = cx + dx, cy + dy
            if in_bounds(nx, ny, w, h) and (nx, ny) not in obstacles and (nx, ny) not in visited:
                visited.add((nx, ny))
                q.append((nx, ny))
    return visited


def astar_cost(start, goal, w, h, obstacles):
    """A* shortest path cost. Returns float('inf') if unreachable."""
    if start == goal:
        return 0
    g_cost = {start: 0}
    open_set = [(abs(start[0] - goal[0]) + abs(start[1] - goal[1]), 0, start)]
    while open_set:
        _, g, cur = heapq.heappop(open_set)
        if cur == goal:
            return g
        if g > g_cost.get(cur, float("inf")):
            continue
        for d in range(4):
            nx, ny = cur[0] + DX[d], cur[1] + DY[d]
            if not in_bounds(nx, ny, w, h) or (nx, ny) in obstacles:
                continue
            ng = g + 1
            if ng < g_cost.get((nx, ny), float("inf")):
                g_cost[(nx, ny)] = ng
                hval = abs(nx - goal[0]) + abs(ny - goal[1])
                heapq.heappush(open_set, (ng + hval, ng, (nx, ny)))
    return float("inf")


def head_danger_zones(board_data, you_id, my_len, w, h):
    """Cells adjacent to equal/larger opponent heads (lethal for us)."""
    danger = set()
    for s in board_data["snakes"]:
        if s["id"] == you_id:
            continue
        if len(s["body"]) >= my_len:
            ox, oy = s["body"][0]["x"], s["body"][0]["y"]
            for dx, dy in ((0, 1), (0, -1), (-1, 0), (1, 0)):
                nx, ny = ox + dx, oy + dy
                if in_bounds(nx, ny, w, h):
                    danger.add((nx, ny))
    return danger


def find_target(board_data, you_id):
    """Target = the longest non-us snake. Proxy for the main engine."""
    best = None
    best_len = -1
    for s in board_data["snakes"]:
        if s["id"] == you_id:
            continue
        if len(s["body"]) > best_len:
            best_len = len(s["body"])
            best = s
    return best


def predict_engine_food(target_head, food_list, w, h, obstacles):
    """
    V1 exploit: predict which food the engine will chase in growth mode.
    Engine logic: BFS reachability filter → nearest by Manhattan distance.
    We replicate that exact logic here to intercept the right food.
    Returns (food_pos, manhattan_dist) or (None, inf).
    """
    reachable = bfs_reachable(target_head, w, h, obstacles)
    best_food = None
    best_dist = float("inf")
    for fx, fy in food_list:
        if (fx, fy) not in reachable:
            continue
        dist = abs(target_head[0] - fx) + abs(target_head[1] - fy)
        if dist < best_dist:
            best_dist = dist
            best_food = (fx, fy)
    return best_food, best_dist


def nearest_corner(x, y, w, h):
    """Returns the nearest board corner to (x, y)."""
    corners = [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)]
    return min(corners, key=lambda c: abs(c[0] - x) + abs(c[1] - y))


# ---------------------------------------------------------------------------
# Move selection
# ---------------------------------------------------------------------------

@app.post("/move")
async def move(request: Request):
    data = await request.json()
    board_data = data["board"]
    you = data["you"]

    hx, hy = you["body"][0]["x"], you["body"][0]["y"]
    my_len = len(you["body"])
    my_health = you["health"]
    w, h = board_data["width"], board_data["height"]
    food = [(f["x"], f["y"]) for f in board_data["food"]]

    obstacles = build_obstacles(board_data)
    moves = get_moves(hx, hy, w, h, obstacles)
    if not moves:
        return JSONResponse({"move": "up"})

    danger = head_danger_zones(board_data, you["id"], my_len, w, h)
    target = find_target(board_data, you["id"])

    target_head = None
    target_len = 0
    if target:
        target_head = (target["body"][0]["x"], target["body"][0]["y"])
        target_len = len(target["body"])

    # V1: We trigger engine's growth mode by being ≥ target_len + 2
    dominant = (my_len >= target_len + 2)

    # Predict engine's food target once (expensive-ish — only do it once per turn)
    engine_food = None
    engine_food_dist = float("inf")
    if dominant and target_head and food:
        engine_food, engine_food_dist = predict_engine_food(
            target_head, food, w, h, obstacles
        )

    scored = []
    for d, nx, ny in moves:
        score = 0.0
        pos = (nx, ny)

        # ── SURVIVAL: flood fill space ────────────────────────────────────
        # Mirror engine's trapped-penalty threshold: space < 2×body_length is bad
        space = flood_count(pos, w, h, obstacles)
        score += space * 1.0
        if space < my_len * 2:
            ratio = space / max(my_len * 2, 1)
            score -= (1.0 - ratio) * 500.0  # matches engine's own penalty scale

        # ── SAFETY: head danger avoidance ─────────────────────────────────
        if pos in danger:
            score -= 350.0

        # ══ PHASE 1: GROW FAST ════════════════════════════════════════════
        # Until we're 2+ longer than target, just grow and avoid conflict.
        if not dominant:
            # A* to nearest food (actual path cost, not just Manhattan)
            if food:
                best_food_cost = min(astar_cost(pos, f, w, h, obstacles) for f in food)
                if best_food_cost < float("inf"):
                    score -= best_food_cost * 2.5

            # Don't pick fights when equal/shorter — engine models us adversarially
            if target_head:
                dist_to_target = abs(nx - target_head[0]) + abs(ny - target_head[1])
                if dist_to_target <= 1 and my_len <= target_len:
                    score -= 250.0  # head-on suicide when we'd lose or tie

        # ══ PHASE 2 & 3: DOMINATE ════════════════════════════════════════
        # Growth mode is active in the engine — exploit all V1-V5 weaknesses.
        else:
            # V1 — FOOD INTERCEPTION ──────────────────────────────────────
            # Engine chase weight is 0.5 (growth mode) — it won't fight for food.
            # We race to the engine's predicted food target.
            if engine_food:
                our_cost = astar_cost(pos, engine_food, w, h, obstacles)
                if our_cost <= engine_food_dist:
                    # We arrive first or tied: intercept! Big reward.
                    score += (engine_food_dist - our_cost + 1) * 12.0
                else:
                    # Can't get there first — block the midpoint of its path.
                    # Cells on the engine→food line are high-value blocking spots.
                    mid_x = (target_head[0] + engine_food[0]) // 2
                    mid_y = (target_head[1] + engine_food[1]) // 2
                    dist_to_midpoint = abs(nx - mid_x) + abs(ny - mid_y)
                    score += max(0.0, 6.0 - dist_to_midpoint) * 3.0

            # V2 — FLEE PRESSURE HERDING ──────────────────────────────────
            # Engine flee weight = 9.0/dist. At dist=2: score hit of −4.5/turn.
            # We sit at dist=2 from engine's head, forcing it away from center.
            # At dist=1 and we're longer: head-on kill opportunity.
            if target_head:
                dist_to_target = abs(nx - target_head[0]) + abs(ny - target_head[1])
                if dist_to_target == 1:
                    if my_len > target_len:
                        score += 70.0   # kill shot: head-on collision, we survive
                    else:
                        score -= 300.0  # equal = mutual death
                elif dist_to_target == 2:
                    score += 30.0   # maximum flee pressure (9.0/2 = −4.5 on engine)
                elif dist_to_target == 3:
                    score += 12.0   # moderate pressure
                # Don't let target escape — penalize moving away from it too much
                elif dist_to_target > 6:
                    score -= (dist_to_target - 6) * 2.0

            # V3 — CORNER HERDING ─────────────────────────────────────────
            # Engine's corner penalty = −9.0, edge = −4.5.
            # Block center access → engine is pushed toward walls/corners.
            if target_head:
                cx, cy = w // 2, h // 2
                our_to_center = abs(nx - cx) + abs(ny - cy)
                target_to_center = abs(target_head[0] - cx) + abs(target_head[1] - cy)
                if our_to_center < target_to_center:
                    # We're closer to center than target = we block its escape inward
                    score += 18.0

                # Pull toward the herding position: between target and its nearest corner
                # (once herded into a corner, engine's eval tanks and it can't escape)
                corner = nearest_corner(target_head[0], target_head[1], w, h)
                # We want to be between target_head and corner — score moves toward it
                corner_midpoint = (
                    (target_head[0] + corner[0]) // 2,
                    (target_head[1] + corner[1]) // 2,
                )
                our_dist_to_herd_pos = abs(nx - corner_midpoint[0]) + abs(ny - corner_midpoint[1])
                score += max(0.0, 8.0 - our_dist_to_herd_pos) * 1.5

            # V4/V5 — SPACE DENIAL ────────────────────────────────────────
            # After our move, simulate how much space target has.
            # Engine's Voronoi weight = 0.12/cell + trapped penalty at space < 2×len.
            # Cutting it below that threshold is extremely punishing for it.
            if target_head:
                target_space_after = flood_count(target_head, w, h, obstacles | {pos})
                score -= target_space_after * 0.4
                # Extra bonus for cutting target below its trapped-penalty threshold
                if target_space_after < target_len * 2:
                    score += 30.0  # we've crossed engine's self-destruct threshold

        # ── SELF-FOOD: eat when health is low, regardless of phase ────────
        if my_health < 40 and food:
            best_food_cost = min(astar_cost(pos, f, w, h, obstacles) for f in food)
            if best_food_cost < float("inf"):
                urgency = 4.0 if my_health < 20 else 1.5
                score -= best_food_cost * urgency

        # ── MILD WALL AVOIDANCE for ourselves ─────────────────────────────
        if nx == 0 or nx == w - 1:
            score -= 2.5
        if ny == 0 or ny == h - 1:
            score -= 2.5

        scored.append((score, DIR_NAMES[d]))

    scored.sort(reverse=True)
    return JSONResponse({"move": scored[0][1]})


@app.post("/end")
async def end(request: Request):
    return JSONResponse({"ok": True})


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8008
    print(f"Starting Counter Snake on port {port}...")
    uvicorn.run(app, host="0.0.0.0", port=port)
