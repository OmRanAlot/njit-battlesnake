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
        "author": "AggressiveBot",
        "color": "#8B00FF",
        "head": "evil",
        "tail": "sharp",
        "version": "1.0.0",
    })


@app.post("/start")
async def start(request: Request):
    return JSONResponse({"ok": True})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def build_obstacles(board, you):
    """Build obstacle set from all snake bodies (tails excluded)."""
    obstacles = set()
    for snake in board["snakes"]:
        body = snake["body"]
        for i, part in enumerate(body):
            if i < len(body) - 1:
                obstacles.add((part["x"], part["y"]))
    return obstacles


def safe_neighbors(x, y, w, h, obstacles):
    """Return list of (nx, ny, move_name) for passable adjacent cells."""
    out = []
    for name, (dx, dy) in DIRS.items():
        nx, ny = x + dx, y + dy
        if 0 <= nx < w and 0 <= ny < h and (nx, ny) not in obstacles:
            out.append((nx, ny, name))
    return out


def flood_fill(start, w, h, obstacles):
    """BFS flood fill returning set of reachable cells."""
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
    """A* search returning (first_move_name, cost) or (None, inf)."""
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


# ---------------------------------------------------------------------------
# Move scoring
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
    # Remove own head from obstacles if present
    obstacles.discard((hx, hy))

    # Head danger zones: cells adjacent to larger/equal opponent heads
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

    # Evaluate each candidate move
    candidates = safe_neighbors(hx, hy, w, h, obstacles)
    if not candidates:
        return JSONResponse({"move": "up"})

    scored = []
    for nx, ny, move_name in candidates:
        score = 0.0

        # --- 1. Space (flood fill) ---
        space = len(flood_fill((nx, ny), w, h, obstacles))
        score += space * 1.5
        # Heavily penalize moves into small pockets
        if space < my_len * 1.5:
            score -= 300.0

        # --- 2. Head danger avoidance ---
        if (nx, ny) in head_danger:
            score -= 150.0

        # --- 3. Food seeking (scales with hunger) ---
        if board["food"]:
            best_food_cost = float("inf")
            for food in board["food"]:
                goal = (food["x"], food["y"])
                _, cost = astar((nx, ny), goal, w, h, obstacles)
                if cost < best_food_cost:
                    best_food_cost = cost
            if best_food_cost < float("inf"):
                # Stronger pull when hungry
                hunger_weight = 3.0 if my_health < 40 else 1.0
                if my_health < 15:
                    hunger_weight = 8.0
                score -= best_food_cost * hunger_weight

        # --- 4. Aggression ---
        for snake in board["snakes"]:
            if snake["id"] == you["id"]:
                continue
            sh = snake["body"][0]
            opp_head = (sh["x"], sh["y"])
            dist = abs(nx - opp_head[0]) + abs(ny - opp_head[1])
            opp_len = len(snake["body"])

            if my_len > opp_len + 1:
                # We're bigger — chase for the kill
                if dist <= 3:
                    score += (4 - dist) * 15.0
                # Bonus for cutting off their space
                opp_space = len(flood_fill(opp_head, w, h, obstacles | {(nx, ny)}))
                if opp_space < opp_len:
                    score += 25.0
            elif opp_len >= my_len:
                # They're bigger or equal — flee
                if dist <= 2:
                    score -= 40.0

        # --- 5. Center preference (mild) ---
        center_dist = abs(nx - w // 2) + abs(ny - h // 2)
        score -= center_dist * 0.5

        # --- 6. Edge/corner penalty ---
        if nx == 0 or nx == w - 1:
            score -= 3.0
        if ny == 0 or ny == h - 1:
            score -= 3.0
        if (nx in (0, w - 1)) and (ny in (0, h - 1)):
            score -= 8.0

        # --- 7. Tail chase fallback ---
        # If we can reach our own tail, that's always a safe cycle
        my_tail = you["body"][-1]
        tail_pos = (my_tail["x"], my_tail["y"])
        _, tail_cost = astar((nx, ny), tail_pos, w, h, obstacles)
        if tail_cost < float("inf"):
            score += 5.0  # mild bonus for having an escape route

        scored.append((score, move_name))

    # Pick the highest-scoring move
    scored.sort(key=lambda x: x[0], reverse=True)
    best_score = scored[0][0]

    # Among ties, pick randomly
    top = [m for s, m in scored if s >= best_score - 0.01]
    choice = random.choice(top)

    return JSONResponse({"move": choice})


@app.post("/end")
async def end(request: Request):
    return JSONResponse({"ok": True})


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8004
    print(f"Starting Aggressive Snake on port {port}...")
    uvicorn.run(app, host="0.0.0.0", port=port)
