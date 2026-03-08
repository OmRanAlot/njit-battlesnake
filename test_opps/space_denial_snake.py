import sys
import random
import heapq
from collections import deque
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import uvicorn

app = FastAPI()

DIRS = {"up": (0, 1), "down": (0, -1), "left": (-1, 0), "right": (1, 0)}


@app.get("/")
def index():
    return JSONResponse({
        "apiversion": "1",
        "author": "SpaceDenialBot",
        "color": "#006400",
        "head": "sand-worm",
        "tail": "round-bum",
        "version": "1.0.0",
    })


@app.post("/start")
async def start(request: Request):
    return JSONResponse({"ok": True})


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def build_obstacles(board, you):
    obstacles = set()
    for snake in board["snakes"]:
        body = snake["body"]
        for i, part in enumerate(body):
            if i < len(body) - 1:
                obstacles.add((part["x"], part["y"]))
    return obstacles


def safe_neighbors(x, y, w, h, obstacles):
    out = []
    for name, (dx, dy) in DIRS.items():
        nx, ny = x + dx, y + dy
        if 0 <= nx < w and 0 <= ny < h and (nx, ny) not in obstacles:
            out.append((nx, ny, name))
    return out


def flood_fill(start, w, h, obstacles):
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
    return visited


def astar(start, goal, w, h, obstacles):
    def h_cost(a, b):
        return abs(a[0] - b[0]) + abs(a[1] - b[1])

    frontier = [(h_cost(start, goal), 0, start)]
    best_cost = {start: 0}
    first_move = {}

    while frontier:
        _, g, current = heapq.heappop(frontier)
        if current == goal:
            return first_move.get(goal), g
        if g > best_cost.get(current, float("inf")):
            continue
        for nx, ny, move in safe_neighbors(current[0], current[1], w, h, obstacles):
            nxt = (nx, ny)
            ng = g + 1
            if ng < best_cost.get(nxt, float("inf")):
                best_cost[nxt] = ng
                heapq.heappush(frontier, (ng + h_cost(nxt, goal), ng, nxt))
                first_move[nxt] = first_move[current] if current != start else move

    return None, float("inf")


def compute_voronoi(board, obstacles):
    """Simultaneous multi-source BFS from each snake's head.
    Returns dict: snake_id -> territory cell count."""
    w, h = board["width"], board["height"]
    owned = {}
    fronts = {}
    counts = {}

    for snake in board["snakes"]:
        sid = snake["id"]
        sh = snake["body"][0]
        pos = (sh["x"], sh["y"])
        fronts[sid] = deque([pos])
        owned[pos] = sid
        counts[sid] = 1

    while any(len(f) > 0 for f in fronts.values()):
        next_fronts = {sid: deque() for sid in fronts}
        proposed = {}

        for sid, front in fronts.items():
            for cx, cy in front:
                for dx, dy in [(0, 1), (0, -1), (-1, 0), (1, 0)]:
                    nx, ny = cx + dx, cy + dy
                    if 0 <= nx < w and 0 <= ny < h and (nx, ny) not in obstacles and (nx, ny) not in owned:
                        if (nx, ny) not in proposed:
                            proposed[(nx, ny)] = []
                        if sid not in proposed[(nx, ny)]:
                            proposed[(nx, ny)].append(sid)

        for pos, claimants in proposed.items():
            if len(claimants) == 1:
                sid = claimants[0]
                owned[pos] = sid
                counts[sid] = counts.get(sid, 0) + 1
                next_fronts[sid].append(pos)

        fronts = next_fronts

    return counts


def find_target(board, you):
    """Find the opponent most likely to be the C++ engine bot (closest to center)."""
    w, h = board["width"], board["height"]
    cx, cy = w // 2, h // 2
    best = None
    best_dist = 999
    for snake in board["snakes"]:
        if snake["id"] == you["id"]:
            continue
        sh = snake["body"][0]
        dist = abs(sh["x"] - cx) + abs(sh["y"] - cy)
        if dist < best_dist:
            best_dist = dist
            best = snake
    return best


# ---------------------------------------------------------------------------
# Move logic
# ---------------------------------------------------------------------------

@app.post("/move")
async def move(request: Request):
    data = await request.json()
    board = data["board"]
    you = data["you"]

    head = you["body"][0]
    hx, hy = head["x"], head["y"]
    my_len = len(you["body"])
    my_health = you["health"]
    w, h = board["width"], board["height"]

    obstacles = build_obstacles(board, you)
    obstacles.discard((hx, hy))

    target = find_target(board, you)
    target_len = len(target["body"]) if target else 3
    target_head = (target["body"][0]["x"], target["body"][0]["y"]) if target else (w // 2, h // 2)

    # Head danger zones from equal/larger opponents
    head_danger = set()
    for snake in board["snakes"]:
        if snake["id"] == you["id"]:
            continue
        if len(snake["body"]) >= my_len:
            sh = snake["body"][0]
            for dx, dy in [(0, 1), (0, -1), (-1, 0), (1, 0)]:
                nx, ny = sh["x"] + dx, sh["y"] + dy
                if 0 <= nx < w and 0 <= ny < h:
                    head_danger.add((nx, ny))

    candidates = safe_neighbors(hx, hy, w, h, obstacles)
    if not candidates:
        return JSONResponse({"move": "up"})

    # Precompute Voronoi once
    voronoi = compute_voronoi(board, obstacles)

    scored = []
    for nx, ny, move_name in candidates:
        score = 0.0

        # 1. SURVIVAL — flood fill space
        space = len(flood_fill((nx, ny), w, h, obstacles))
        score += space * 2.0
        if space < my_len * 1.5:
            score -= 400.0

        # 2. HEAD SAFETY
        if (nx, ny) in head_danger:
            score -= 200.0

        # 3. FOOD — aggressive eating to maintain size >= target
        #    Exploits: ±100 binary cliff per opponent comparison
        if board["food"]:
            best_food_cost = float("inf")
            for food in board["food"]:
                _, cost = astar((nx, ny), (food["x"], food["y"]), w, h, obstacles)
                if cost < best_food_cost:
                    best_food_cost = cost
            if best_food_cost < float("inf"):
                if my_len <= target_len:
                    food_weight = 6.0    # CRITICAL: we're losing the -100 cliff
                elif my_health < 15:
                    food_weight = 10.0   # about to starve
                elif my_health < 40:
                    food_weight = 4.0    # getting hungry
                else:
                    food_weight = 1.5    # maintenance eating
                score -= best_food_cost * food_weight

        # 4. CENTER CONTROL — camp center to exploit target's center attraction
        #    Target's center pull is only 0.4; ours is 3.0 — we get there first
        cx, cy = w // 2, h // 2
        center_dist = abs(nx - cx) + abs(ny - cy)
        score -= center_dist * 3.0

        # 5. HEAD PRESSURE — stay at distance 2-3 from target to trigger
        #    its -200/dist penalty (requires we are >= target length)
        dist_to_target = abs(nx - target_head[0]) + abs(ny - target_head[1])
        if my_len >= target_len:
            if dist_to_target == 2:
                score += 50.0     # ideal: costs target -200/2 = -100
            elif dist_to_target == 3:
                score += 30.0     # still costs target -200/3 = -67
            elif dist_to_target == 1:
                score += 20.0     # maximum pressure but risky
            elif dist_to_target <= 5:
                score += 10.0 / max(dist_to_target, 1)
        else:
            # We're smaller — flee to avoid being chased (+10/dist for target)
            if dist_to_target <= 2:
                score -= 60.0

        # 6. VORONOI DENIAL — prefer positions that cut off target territory
        # Simulate moving here and recompute how much territory target would have
        sim_obstacles = obstacles | {(nx, ny)}
        sim_voronoi = compute_voronoi(board, sim_obstacles)
        my_territory = sim_voronoi.get(you["id"], 0)
        target_territory = sim_voronoi.get(target["id"], 0) if target else 0
        score += my_territory * 0.5
        score -= target_territory * 0.3

        # 7. EDGE / CORNER AVOIDANCE
        if nx == 0 or nx == w - 1:
            score -= 3.0
        if ny == 0 or ny == h - 1:
            score -= 3.0
        if (nx in (0, w - 1)) and (ny in (0, h - 1)):
            score -= 10.0

        # 8. TAIL CHASE — maintain escape route to own tail
        my_tail = you["body"][-1]
        _, tail_cost = astar((nx, ny), (my_tail["x"], my_tail["y"]), w, h, obstacles)
        if tail_cost < float("inf"):
            score += 8.0

        scored.append((score, move_name))

    scored.sort(key=lambda x: x[0], reverse=True)
    best_score = scored[0][0]
    top = [m for s, m in scored if s >= best_score - 0.01]
    choice = random.choice(top)

    return JSONResponse({"move": choice})


@app.post("/end")
async def end(request: Request):
    return JSONResponse({"ok": True})


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8005
    print(f"Starting Space Denial Snake on port {port}...")
    uvicorn.run(app, host="0.0.0.0", port=port)
