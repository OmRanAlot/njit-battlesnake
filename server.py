import ctypes
import os
import sys
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import uvicorn

# ============================================================
# Load C++ engine
# ============================================================

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Try .so first (Linux/Mac), then .dll (Windows)
lib_path = os.path.join(SCRIPT_DIR, "libsnake.so")
if not os.path.exists(lib_path):
    lib_path = os.path.join(SCRIPT_DIR, "libsnake.dll")

if not os.path.exists(lib_path):
    print("ERROR: libsnake.so not found. Run: bash build.sh")
    sys.exit(1)

engine = ctypes.CDLL(lib_path)
# ============================================================
# ctypes struct definitions (MUST match engine.h exactly)
# ============================================================

# Maximum array sizes mapped directly from C++ constants for contiguous memory mapping
MAX_BODY = 121      # Maximum possible length of a snake on an 11x11 board
MAX_SNAKES = 4      # Maximum number of snakes supported in a game
MAX_FOOD = 20       # Maximum number of food pellets to track
TIMEOUT_MS = 400    # Compute budget (500ms total API limit - 200ms safety margin for
                    # HTTP overhead, JSON parsing, ctypes marshalling, and CLI latency)

class CSnake(ctypes.Structure):
    _fields_ = [
        ("body_x", ctypes.c_int * MAX_BODY),
        ("body_y", ctypes.c_int * MAX_BODY),
        ("length", ctypes.c_int),
        ("health", ctypes.c_int),
        ("alive", ctypes.c_int),
        ("ate_last_turn", ctypes.c_int),
    ]

class CBoard(ctypes.Structure):
    _fields_ = [
        ("snakes", CSnake * MAX_SNAKES),
        ("num_snakes", ctypes.c_int),
        ("food_x", ctypes.c_int * MAX_FOOD),
        ("food_y", ctypes.c_int * MAX_FOOD),
        ("num_food", ctypes.c_int),
        ("my_index", ctypes.c_int),
        ("timeout_ms", ctypes.c_int),
    ]

engine.get_best_move.argtypes = [ctypes.POINTER(CBoard)]
engine.get_best_move.restype = ctypes.c_int

DIR_NAMES = ["up", "down", "left", "right"]

# ============================================================
# Track ate_last_turn across turns
# ============================================================

# State dictionary: game_id -> {snake_id: prev_length}
# Tracks each snake's length from the previous turn to determine if they ate food.
# This prevents the C++ engine from misclassifying tail movement rules.
game_lengths: dict[str, dict[str, int]] = {}

# ============================================================
# FastAPI app
# ============================================================

app = FastAPI()


@app.get("/")
def index():
    return JSONResponse({
        "apiversion": "1",
        "author": "NJIT Battlesnake",
        "color": "#C7CCB9",
        "head": "default",
        "tail": "default",
        "version": "1.0.0",
    })  


@app.post("/start")
async def start(request: Request):
    data = await request.json()
    game_id = data["game"]["id"]
    # df = pd.DataFrame()
    game_lengths[game_id] = {}
    return JSONResponse({"ok": True})


@app.post("/move")
async def move(request: Request):
    data = await request.json()
    game_id = data["game"]["id"]
    board_data = data["board"]
    you = data["you"]
    # Initialize game tracking if needed
    if game_id not in game_lengths:
        game_lengths[game_id] = {}
    prev_lengths = game_lengths[game_id]

    # Build the CBoard C-struct iteratively to pass by reference to the C++ engine
    cb = CBoard()
    snakes = board_data["snakes"]
    cb.num_snakes = min(len(snakes), MAX_SNAKES)

    my_index = -1
    for i, snake in enumerate(snakes[:MAX_SNAKES]):
        cs = cb.snakes[i]
        body = snake["body"]
        cs.length = min(len(body), MAX_BODY)
        for j, part in enumerate(body[:MAX_BODY]):
            cs.body_x[j] = part["x"]
            cs.body_y[j] = part["y"]
        cs.health = snake["health"]
        cs.alive = 1

        # Detect ate_last_turn by comparing current body length to the previous turn.
        # If length increased, the snake ate food, meaning its tail will NOT shrink this turn.
        snake_id = snake["id"]
        if snake_id in prev_lengths and len(body) > prev_lengths[snake_id]:
            cs.ate_last_turn = 1
        else:
            cs.ate_last_turn = 0

        # Update tracked length
        prev_lengths[snake_id] = len(body)

        if snake["id"] == you["id"]:
            my_index = i

    if my_index == -1:
        return JSONResponse({"move": "up"})

    cb.my_index = my_index

    # Food
    food = board_data.get("food", [])
    cb.num_food = min(len(food), MAX_FOOD)
    for i, f in enumerate(food[:MAX_FOOD]):
        cb.food_x[i] = f["x"]
        cb.food_y[i] = f["y"]

    cb.timeout_ms = TIMEOUT_MS

    # Delegate the heavy computation to the C++ engine via ctypes
    # The result is an integer (0=up, 1=down, 2=left, 3=right)
    result = engine.get_best_move(ctypes.byref(cb))
    direction = DIR_NAMES[result] if 0 <= result < 4 else "up"

    return JSONResponse({"move": direction})


@app.post("/end")
async def end(request: Request):
    data = await request.json()
    game_id = data["game"]["id"]
    game_lengths.pop(game_id, None)
    return JSONResponse({"ok": True})


if __name__ == "__main__":
    # Priority: CLI arg → PORT env var (Railway/Render) → 8080
    if len(sys.argv) > 1:
        port = int(sys.argv[1])
    else:
        port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
