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
        "author": "TrapBot",
        "color": "#FF8C00",
        "head": "tiger-king",
        "tail": "hook",
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


def find_target(board, you):
    """Find the opponent closest to center (likely the C++ engine bot)."""
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


def predict_target_food(board, target):
    """Return the food the target is most likely heading toward (closest by Manhattan)."""
    if not board["food"] or target is None:
        return None
    th = target["body"][0]
    tx, ty = th["x"], th["y"]
    best_food = None
    best_dist = 999
    for food in board["food"]:
        dist = abs(food["x"] - tx) + abs(food["y"] - ty)
        if dist < best_dist:
            best_dist = dist
            best_food = food
    return best_food


def find_interception_cell(board, you, target, food, obstacles):
    """Find a cell between the target and its food that we can reach first."""
    w, h = board["width"], board["height"]
    my_head = (you["body"][0]["x"], you["body"][0]["y"])
    target_head = (target["body"][0]["x"], target["body"][0]["y"])
    food_pos = (food["x"], food["y"])

    mid_x = (target_head[0] + food_pos[0]) // 2
    mid_y = (target_head[1] + food_pos[1]) // 2

    best_cell = None
    best_score = -999

    # Search 5x5 area around midpoint for interception opportunities
    for dx in range(-2, 3):
        for dy in range(-2, 3):
            cx, cy = mid_x + dx, mid_y + dy
            if not (0 <= cx < w and 0 <= cy < h):
                continue
            if (cx, cy) in obstacles:
                continue

            _, my_cost = astar(my_head, (cx, cy), w, h, obstacles)
            _, target_cost = astar(target_head, (cx, cy), w, h, obstacles)

            if my_cost >= float("inf"):
                continue

            # Prefer cells we reach before the target, close to the food
            time_advantage = target_cost - my_cost
            food_proximity = abs(cx - food_pos[0]) + abs(cy - food_pos[1])
            cell_score = time_advantage * 10.0 - food_proximity * 2.0

            if cell_score > best_score:
                best_score = cell_score
                best_cell = (cx, cy)

    return best_cell


# ---------------------------------------------------------------------------
# Move logic — three modes based on target health
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
    target_health = target["health"] if target else 100
    target_head = (target["body"][0]["x"], target["body"][0]["y"]) if target else (w // 2, h // 2)

    # Determine mode based on target's health
    # TRAP:      target health < 15 — it's in predictable A* beeline mode
    # INTERCEPT: target health 15-39 — it's getting hungry, position now
    # CONTROL:   target health >= 40 — it ignores food, we eat everything
    if target_health < 15:
        mode = "TRAP"
    elif target_health < 40:
        mode = "INTERCEPT"
    else:
        mode = "CONTROL"

    # Head danger zones
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

    # Precompute food predictions for INTERCEPT and TRAP modes
    predicted_food = predict_target_food(board, target) if target else None
    interception_cell = None
    if predicted_food and target and mode in ("INTERCEPT", "TRAP"):
        interception_cell = find_interception_cell(board, you, target, predicted_food, obstacles)

    scored = []
    for nx, ny, move_name in candidates:
        score = 0.0

        # --- Shared: survival ---
        space = len(flood_fill((nx, ny), w, h, obstacles))
        if mode == "TRAP":
            # More aggressive in trap mode — accept tighter spaces
            score += space * 1.5
            if space < my_len:
                score -= 400.0
        else:
            score += space * 2.0
            if space < my_len * 1.5:
                score -= 400.0

        # --- Shared: head safety ---
        if (nx, ny) in head_danger:
            score -= 200.0

        # --- Shared: edge/corner avoidance ---
        if nx == 0 or nx == w - 1:
            score -= 3.0
        if ny == 0 or ny == h - 1:
            score -= 3.0
        if (nx in (0, w - 1)) and (ny in (0, h - 1)):
            score -= 10.0

        # --- Shared: tail chase escape route ---
        my_tail = you["body"][-1]
        _, tail_cost = astar((nx, ny), (my_tail["x"], my_tail["y"]), w, h, obstacles)
        if tail_cost < float("inf"):
            score += 5.0

        dist_to_target = abs(nx - target_head[0]) + abs(ny - target_head[1])

        # =============================================
        # MODE: CONTROL — eat everything, grow unopposed
        # Target has zero food incentive at health >= 40 + length >= 8
        # =============================================
        if mode == "CONTROL":
            if board["food"]:
                best_food_cost = float("inf")
                # Prefer food that's closer to US than to target (deny it)
                best_denial_score = -999
                for food in board["food"]:
                    fpos = (food["x"], food["y"])
                    _, my_cost = astar((nx, ny), fpos, w, h, obstacles)
                    target_food_dist = abs(target_head[0] - fpos[0]) + abs(target_head[1] - fpos[1])

                    if my_cost < best_food_cost:
                        best_food_cost = my_cost

                    # Food denial: prefer food we can reach but target can't easily
                    if my_cost < float("inf"):
                        denial = target_food_dist - my_cost
                        if denial > best_denial_score:
                            best_denial_score = denial

                if best_food_cost < float("inf"):
                    food_weight = 5.0
                    if my_len <= target_len:
                        food_weight = 7.0   # urgently need to match size
                    elif my_health < 40:
                        food_weight = 6.0
                    score -= best_food_cost * food_weight

                # Bonus for denying food to the target
                if best_denial_score > 0:
                    score += best_denial_score * 2.0

            # Food camping: stay near food clusters
            if board["food"]:
                total_proximity = sum(
                    abs(nx - f["x"]) + abs(ny - f["y"]) for f in board["food"]
                )
                score -= total_proximity * 0.3

            # Size urgency
            if my_len <= target_len:
                score -= 50.0

        # =============================================
        # MODE: INTERCEPT — position between target and food
        # Target is starting to get hungry (health 15-39)
        # =============================================
        elif mode == "INTERCEPT":
            # Move toward interception point
            if interception_cell:
                _, intercept_cost = astar((nx, ny), interception_cell, w, h, obstacles)
                if intercept_cost < float("inf"):
                    score -= intercept_cost * 8.0

            # Still eat food to maintain size
            if board["food"]:
                best_food_cost = float("inf")
                for food in board["food"]:
                    _, cost = astar((nx, ny), (food["x"], food["y"]), w, h, obstacles)
                    if cost < best_food_cost:
                        best_food_cost = cost
                if best_food_cost < float("inf"):
                    food_weight = 3.0
                    if my_len <= target_len:
                        food_weight = 6.0
                    score -= best_food_cost * food_weight

            # Head pressure if we're equal/bigger
            if my_len >= target_len and dist_to_target in (2, 3):
                score += 40.0

        # =============================================
        # MODE: TRAP — target is in predictable A* beeline
        # Block its path to food, go for the kill
        # =============================================
        elif mode == "TRAP":
            if predicted_food:
                food_pos = (predicted_food["x"], predicted_food["y"])

                # Can we reach the food before the target? Eat it first!
                _, my_food_cost = astar((nx, ny), food_pos, w, h, obstacles)
                _, target_food_cost = astar(target_head, food_pos, w, h, obstacles - {(hx, hy)})

                if my_food_cost < float("inf") and my_food_cost < target_food_cost:
                    score += 80.0   # eat the food before them
                    score -= my_food_cost * 6.0

                # Move toward interception point on target's A* path
                if interception_cell:
                    _, intercept_cost = astar((nx, ny), interception_cell, w, h, obstacles)
                    if intercept_cost < float("inf"):
                        score -= intercept_cost * 10.0

            # Go for head-on kill if we're bigger
            if my_len > target_len and dist_to_target <= 2:
                score += 100.0
            elif my_len > target_len and dist_to_target <= 4:
                score += 40.0 / max(dist_to_target, 1)

            # Still eat any food we pass to maintain advantage
            if board["food"]:
                best_food_cost = float("inf")
                for food in board["food"]:
                    _, cost = astar((nx, ny), (food["x"], food["y"]), w, h, obstacles)
                    if cost < best_food_cost:
                        best_food_cost = cost
                if best_food_cost < float("inf"):
                    score -= best_food_cost * 2.0

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
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8006
    print(f"Starting Trap Snake on port {port}...")
    uvicorn.run(app, host="0.0.0.0", port=port)
