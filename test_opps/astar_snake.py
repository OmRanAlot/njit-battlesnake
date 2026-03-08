import sys
import random
import heapq
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import uvicorn

app = FastAPI()

@app.get("/")
def index():
    return JSONResponse({
        "apiversion": "1",
        "author": "AStarBot",
        "color": "#0000ff",
        "head": "smart-caterpillar",
        "tail": "fat-rattle",
        "version": "1.0.0",
    })

@app.post("/start")
async def start(request: Request):
    return JSONResponse({"ok": True})

def get_neighbors(x, y, width, height, obstacles):
    neighbors = []
    for dx, dy, move in [(0, 1, "up"), (0, -1, "down"), (-1, 0, "left"), (1, 0, "right")]:
        nx, ny = x + dx, y + dy
        if 0 <= nx < width and 0 <= ny < height and (nx, ny) not in obstacles:
            neighbors.append((nx, ny, move))
    return neighbors

def astar_search(start, goal, width, height, obstacles):
    # Manhattan distance heuristic
    def heuristic(a, b):
        return abs(a[0] - b[0]) + abs(a[1] - b[1])

    frontier = []
    heapq.heappush(frontier, (0, start))
    came_from = {start: None}
    cost_so_far = {start: 0}
    first_move = {}

    while frontier:
        _, current = heapq.heappop(frontier)

        if current == goal:
            break

        for nx, ny, move in get_neighbors(current[0], current[1], width, height, obstacles):
            next_node = (nx, ny)
            new_cost = cost_so_far[current] + 1
            if next_node not in cost_so_far or new_cost < cost_so_far[next_node]:
                cost_so_far[next_node] = new_cost
                priority = new_cost + heuristic(next_node, goal)
                heapq.heappush(frontier, (priority, next_node))
                came_from[next_node] = current
                
                # Track the very first move required to reach this path
                if current == start:
                    first_move[next_node] = move
                else:
                    first_move[next_node] = first_move[current]

    if goal in came_from:
        return first_move[goal], cost_so_far[goal]
    return None, float('inf')


@app.post("/move")
async def move(request: Request):
    data = await request.json()
    board = data["board"]
    you = data["you"]
    
    head = you["body"][0]
    head_pos = (head["x"], head["y"])
    
    width = board["width"]
    height = board["height"]
    
    # 1. Map all obstacles (snakes)
    obstacles = set()
    for snake in board["snakes"]:
        for i, part in enumerate(snake["body"]):
            # Don't count the snake's tail as an obstacle IF it hasn't eaten
            # For a simpler bot, we just treat all segments except the very last one as solid
            if i < len(snake["body"]) - 1:
                obstacles.add((part["x"], part["y"]))
            
            # Also avoid opponent heads if they are bigger or same size
            if i == 0 and snake["id"] != you["id"] and snake["length"] >= you["length"]:
                for dx, dy in [(0, 1), (0, -1), (-1, 0), (1, 0)]:
                    nx, ny = part["x"] + dx, part["y"] + dy
                    if 0 <= nx < width and 0 <= ny < height:
                        obstacles.add((nx, ny))
    
    # Ensure our own head isn't an obstacle when calculating paths
    if head_pos in obstacles:
        obstacles.remove(head_pos)

    # 2. Find the closest reachable food
    best_move = None
    min_cost = float('inf')
    
    for food in board["food"]:
        goal = (food["x"], food["y"])
        move, cost = astar_search(head_pos, goal, width, height, obstacles)
        if move and cost < min_cost:
            min_cost = cost
            best_move = move
            
    # 3. If food is reachable, go for it!
    if best_move:
        return JSONResponse({"move": best_move})
        
    # 4. Fallback: If no food is reachable, pick any safe contiguous move
    safe_moves = []
    for x, y, move in get_neighbors(head_pos[0], head_pos[1], width, height, obstacles):
        safe_moves.append(move)
        
    if safe_moves:
        # Prefer moves closer to the center as a basic fallback heuristic
        # Actually random is fine for this advanced-but-not-perfect snake
        direction = random.choice(safe_moves)
    else:
        # Doomed.
        direction = "up"
        
    return JSONResponse({"move": direction})

@app.post("/end")
async def end(request: Request):
    return JSONResponse({"ok": True})

if __name__ == "__main__":
    if len(sys.argv) > 1:
        port = int(sys.argv[1])
    else:
        port = 8003
    
    print(f"Starting A* Snake on port {port}...")
    uvicorn.run(app, host="0.0.0.0", port=port)
