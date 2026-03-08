import random
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import uvicorn
import sys

app = FastAPI()

@app.get("/")
def index():
    return JSONResponse({
        "apiversion": "1",
        "author": "RandomBot",
        "color": "#ff0000",
        "head": "silly",
        "tail": "freckled",
        "version": "1.0.0",
    })

@app.post("/start")
async def start(request: Request):
    return JSONResponse({"ok": True})

@app.post("/move")
async def move(request: Request):
    data = await request.json()
    board = data["board"]
    you = data["you"]
    head = you["body"][0]
    
    board_width = board["width"]
    board_height = board["height"]
    
    # We avoid the neck so the snake doesn't instantly kill itself on turn 1
    # We also avoid moving out of bounds (walls).
    safe_moves = []
    neck = you["body"][1] if len(you["body"]) > 1 else None
    
    for m in ["up", "down", "left", "right"]:
        nx, ny = head["x"], head["y"]
        if m == "up": ny += 1
        elif m == "down": ny -= 1
        elif m == "left": nx -= 1
        elif m == "right": nx += 1
        
        # Check walls
        if nx < 0 or nx >= board_width or ny < 0 or ny >= board_height:
            continue
            
        # Check neck
        if neck and nx == neck["x"] and ny == neck["y"]:
            continue
            
        safe_moves.append(m)
        
    direction = random.choice(safe_moves) if safe_moves else random.choice(["up", "down", "left", "right"])
    
    return JSONResponse({"move": direction})

@app.post("/end")
async def end(request: Request):
    return JSONResponse({"ok": True})

if __name__ == "__main__":
    #use arguments to set the port
    
    if len(sys.argv) > 1:
        port = int(sys.argv[1])
    else:
        port = 8002
    # Running on 8002 to not conflict with the main engine on 8000 or the opponent on 8001
    uvicorn.run(app, host="0.0.0.0", port=port)
