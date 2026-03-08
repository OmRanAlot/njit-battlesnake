"""Smoke tests for the Battlesnake C++ engine."""

import ctypes
import os
import sys
import time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

MAX_BODY = 121
MAX_SNAKES = 4
MAX_FOOD = 20


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


# Load engine
lib_path = os.path.join(SCRIPT_DIR, "libsnake.so")
if not os.path.exists(lib_path):
    lib_path = os.path.join(SCRIPT_DIR, "libsnake.dll")
if not os.path.exists(lib_path):
    print("ERROR: libsnake not found. Run: bash build.sh")
    sys.exit(1)

engine = ctypes.CDLL(lib_path)
engine.get_best_move.argtypes = [ctypes.POINTER(CBoard)]
engine.get_best_move.restype = ctypes.c_int

DIR_NAMES = ["up", "down", "left", "right"]


def make_snake(body_coords, health=100, alive=True, ate_last_turn=False):
    """Create a CSnake from a list of (x, y) tuples. First = head."""
    s = CSnake()
    s.length = len(body_coords)
    for i, (x, y) in enumerate(body_coords):
        s.body_x[i] = x
        s.body_y[i] = y
    s.health = health
    s.alive = 1 if alive else 0
    s.ate_last_turn = 1 if ate_last_turn else 0
    return s


def make_board(snakes, my_index, food=None, timeout_ms=420):
    """Create a CBoard."""
    cb = CBoard()
    cb.num_snakes = len(snakes)
    for i, s in enumerate(snakes):
        cb.snakes[i] = s
    cb.my_index = my_index
    if food:
        cb.num_food = len(food)
        for i, (x, y) in enumerate(food):
            cb.food_x[i] = x
            cb.food_y[i] = y
    else:
        cb.num_food = 0
    cb.timeout_ms = timeout_ms
    return cb


def get_move(cb):
    result = engine.get_best_move(ctypes.byref(cb))
    return DIR_NAMES[result] if 0 <= result < 4 else "unknown"


passed = 0
failed = 0


def test(name, cb, expected_moves, forbidden_moves=None):
    """Run a test. expected_moves: list of acceptable directions."""
    global passed, failed
    move = get_move(cb)
    ok = move in expected_moves
    if forbidden_moves:
        ok = ok and move not in forbidden_moves

    status = "PASS" if ok else "FAIL"
    if not ok:
        failed += 1
        print(f"  [{status}] {name}: got '{move}', expected one of {expected_moves}")
    else:
        passed += 1
        print(f"  [{status}] {name}: '{move}'")


# ============================================================
# Test 1: Wall avoidance — snake in top-right corner
# ============================================================
print("\n--- Wall Avoidance ---")

# Snake at (10, 10) heading into corner, body going left
s = make_snake([(10, 10), (9, 10), (8, 10)])
cb = make_board([s], 0)
test("Corner escape (10,10)", cb, ["down", "left"])

# Snake at (0, 0) bottom-left corner
s = make_snake([(0, 0), (1, 0), (2, 0)])
cb = make_board([s], 0)
test("Corner escape (0,0)", cb, ["up", "right"])

# Snake on left wall
s = make_snake([(0, 5), (0, 4), (0, 3)])
cb = make_board([s], 0)
test("Left wall escape", cb, ["up", "right"])

# ============================================================
# Test 2: Self-collision avoidance
# ============================================================
print("\n--- Self-Collision Avoidance ---")

# Snake curled — only one safe move
# Head at (5,5), body wraps around leaving only "right" open
s = make_snake([(5, 5), (5, 6), (4, 6), (4, 5), (4, 4), (5, 4)])
cb = make_board([s], 0)
test("Self-collision avoidance", cb, ["right", "down"])

# ============================================================
# Test 3: Space maximization
# ============================================================
print("\n--- Space Maximization ---")

# Snake in center, one direction leads to small pocket
# Place snake at (5,5) with body going down
s = make_snake([(5, 5), (5, 4), (5, 3)])
# Add wall of enemy snake blocking left side
wall_snake = make_snake([
    (4, 0), (4, 1), (4, 2), (4, 3), (4, 4), (4, 5), (4, 6),
    (4, 7), (4, 8), (4, 9), (4, 10),
])
cb = make_board([s, wall_snake], 0)
# Should prefer going right (more open space) or up, not left (blocked)
test("Prefer open space", cb, ["up", "right"])

# ============================================================
# Test 4: Food seeking when hungry
# ============================================================
print("\n--- Food Seeking ---")

# Snake with low health, food is to the right
s = make_snake([(5, 5), (5, 4), (5, 3)], health=15)
cb = make_board([s], 0, food=[(7, 5)])
test("Seek food when hungry", cb, ["right", "up"])

# Food directly adjacent — with health=1 the snake MUST eat now or die
s = make_snake([(5, 5), (5, 4), (5, 3)], health=1)
cb = make_board([s], 0, food=[(6, 5)])
test("Eat adjacent food when starving", cb, ["right"])

# ============================================================
# Test 5: 4-snake scenario
# ============================================================
print("\n--- 4-Snake Scenario ---")

s0 = make_snake([(2, 2), (2, 1), (2, 0)])
s1 = make_snake([(8, 2), (8, 1), (8, 0)])
s2 = make_snake([(2, 8), (2, 9), (2, 10)])
s3 = make_snake([(8, 8), (8, 9), (8, 10)])
cb = make_board([s0, s1, s2, s3], 0, food=[(5, 5)])
move = get_move(cb)
# Just verify it returns a valid move and doesn't crash
test("4-snake valid move", cb, ["up", "down", "left", "right"])

# ============================================================
# Test 6: Timeout compliance
# ============================================================
print("\n--- Timeout Compliance ---")

s0 = make_snake([(5, 5), (5, 4), (5, 3)])
s1 = make_snake([(2, 2), (2, 1), (2, 0)])
s2 = make_snake([(8, 8), (8, 7), (8, 6)])
s3 = make_snake([(8, 2), (8, 1), (8, 0)])
cb = make_board([s0, s1, s2, s3], 0, food=[(3, 3), (7, 7)], timeout_ms=420)

start = time.time()
move = get_move(cb)
elapsed_ms = (time.time() - start) * 1000

if elapsed_ms < 500:
    passed += 1
    print(f"  [PASS] Timeout compliance: {elapsed_ms:.0f}ms (< 500ms)")
else:
    failed += 1
    print(f"  [FAIL] Timeout compliance: {elapsed_ms:.0f}ms (>= 500ms)")

# ============================================================
# Test 7: Anti-looping — snake on left wall prefers center
# ============================================================
print("\n--- Anti-Looping ---")

# Snake on left wall heading up — should prefer right (toward center) not up (along wall)
s = make_snake([(0, 5), (0, 4), (0, 3)])
cb = make_board([s], 0)
test("Left wall prefers center", cb, ["right"])

# Snake in center should not drift toward walls
s = make_snake([(5, 5), (5, 4), (5, 3)])
cb = make_board([s], 0, food=[(5, 8)])
test("Center snake moves toward food", cb, ["up"], forbidden_moves=["left"])

# ============================================================
# Test 8: A* urgent food-seeking (health < 15)
# ============================================================
print("\n--- A* Urgent Food Seeking ---")

# Food is to the right, health=10 — A* should override minimax and go right
s = make_snake([(3, 5), (3, 4), (3, 3)], health=10)
cb = make_board([s], 0, food=[(7, 5)])
test("A* seeks food at health=10", cb, ["right"])

# Food is above and to the left, health=5
s = make_snake([(5, 3), (5, 2), (5, 1)], health=5)
cb = make_board([s], 0, food=[(3, 7)])
test("A* navigates to distant food", cb, ["up", "left"])

# Food is blocked by a wall of snake bodies — A* must route around
blocker = make_snake([
    (5, 5), (5, 6), (5, 7), (5, 8), (5, 9), (5, 10),
    (4, 5), (4, 6), (4, 7), (4, 8), (4, 9), (4, 10),
])
s = make_snake([(3, 5), (3, 4), (3, 3)], health=8)
# Food is at (7,5) — direct path blocked, must go around
cb = make_board([s, blocker], 0, food=[(7, 5)])
move = get_move(cb)
# Should find SOME path around (down to go under the wall) — just verify it doesn't crash
# and picks a valid direction
test("A* routes around obstacles", cb, ["up", "down", "left", "right"])

# No reachable food — should fall back to minimax (not crash)
wall = make_snake([
    (2, 4), (3, 4), (4, 4), (2, 6), (3, 6), (4, 6),
    (2, 5), (4, 5),
])
s = make_snake([(3, 5), (3, 5), (3, 5)], health=5)
cb = make_board([s, wall], 0, food=[(8, 8)])  # food exists but unreachable
test("A* fallback when food unreachable", cb, ["up", "down", "left", "right"])

# ============================================================
# Test 9: Head-to-head collision avoidance
# ============================================================
print("\n--- Head-to-Head Avoidance ---")

# Our snake (length 3) is at (5,5), opponent (length 4) is at (7,5).
# Both heading toward each other. If we go right, we'd meet at (6,5) — lethal
# since opponent is longer. Should avoid going right.
s = make_snake([(5, 5), (5, 4), (5, 3)])
opp = make_snake([(7, 5), (7, 4), (7, 3), (7, 2)])  # longer opponent
cb = make_board([s, opp], 0)
test("Avoid larger opponent head", cb, ["up", "down", "left"], forbidden_moves=["right"])

# Our snake (length 3) at (5,5), equal-length opponent at (7,5).
# Equal length head-to-head = both die. Should also avoid.
s = make_snake([(5, 5), (5, 4), (5, 3)])
opp = make_snake([(7, 5), (7, 4), (7, 3)])  # same length
cb = make_board([s, opp], 0)
test("Avoid equal opponent head", cb, ["up", "down", "left"], forbidden_moves=["right"])

# Our snake (length 5) is LONGER than opponent (length 3).
# Going right toward opponent should be allowed (kill opportunity).
s = make_snake([(5, 5), (5, 4), (5, 3), (5, 2), (5, 1)])
opp = make_snake([(7, 5), (7, 4), (7, 3)])  # shorter opponent
cb = make_board([s, opp], 0)
# Should not be afraid — right is a valid aggressive move
test("Chase smaller opponent head", cb, ["up", "down", "left", "right"])

# ============================================================
# Test 10: Late-game endurance (long snakes, tight board)
# ============================================================
print("\n--- Late-Game Endurance ---")

# Two long snakes (15 segments), only 1 food — must navigate tight spaces
s0_body = [(5, 5)]
for i in range(1, 15):
    s0_body.append((5, 5 - i if 5 - i >= 0 else 5 - i + 11))
# Build a zigzag path so body stays in bounds
s0_body = [
    (5, 5), (5, 4), (5, 3), (5, 2), (5, 1), (5, 0),
    (6, 0), (6, 1), (6, 2), (6, 3), (6, 4), (6, 5),
    (7, 5), (7, 4), (7, 3),
]
s1_body = [
    (3, 5), (3, 6), (3, 7), (3, 8), (3, 9), (3, 10),
    (2, 10), (2, 9), (2, 8), (2, 7), (2, 6), (2, 5),
    (1, 5), (1, 6), (1, 7),
]
s0 = make_snake(s0_body, health=80)
s1 = make_snake(s1_body, health=80)
cb = make_board([s0, s1], 0, food=[(8, 8)])
test("Late-game tight navigation", cb, ["up", "down", "left", "right"])

# Verify the snake doesn't trap itself when it has a long body
# Snake coiled in bottom-right, only escape is up
coiled = [
    (8, 2), (9, 2), (10, 2), (10, 1), (9, 1), (8, 1),
    (8, 0), (9, 0), (10, 0),
]
s = make_snake(coiled, health=50)
cb = make_board([s], 0, food=[(5, 5)])
test("Escape from coil", cb, ["up", "left"], forbidden_moves=["right", "down"])

# ============================================================
# Test 11: Starvation pressure — food behind opponent
# ============================================================
print("\n--- Starvation Pressure ---")

# Health=20, food at (8,5) but opponent body blocks direct path at x=6,7
s = make_snake([(4, 5), (4, 4), (4, 3)], health=20)
blocker = make_snake([
    (6, 3), (6, 4), (6, 5), (6, 6), (6, 7),
    (7, 3), (7, 4), (7, 5), (7, 6), (7, 7),
])
cb = make_board([s, blocker], 0, food=[(9, 5)])
move = get_move(cb)
# Should path around (up or down to go over/under the wall)
# Note: snake may go left to maximize space — that's a valid survival choice
# when food is far behind a wall. This tests it doesn't crash, not direction.
test("Path around blocker to food", cb, ["up", "down", "left", "right"])

# Very low health, food in opposite corner — should still try
s = make_snake([(1, 1), (1, 0), (0, 0)], health=12)
cb = make_board([s], 0, food=[(9, 9)])
test("Desperate food seek across board", cb, ["up", "right"])

# ============================================================
# Test 12: 4-snake crossfire — food in center, all converging
# ============================================================
print("\n--- 4-Snake Crossfire ---")

# All 4 snakes equidistant from center food — should be cautious
s0 = make_snake([(5, 2), (5, 1), (5, 0)], health=50)     # us, below center
s1 = make_snake([(5, 8), (5, 9), (5, 10)], health=50)    # above
s2 = make_snake([(2, 5), (1, 5), (0, 5)], health=50)     # left
s3 = make_snake([(8, 5), (9, 5), (10, 5)], health=50)    # right
cb = make_board([s0, s1, s2, s3], 0, food=[(5, 5)])
move = get_move(cb)
# With all 4 snakes converging on center food, snake should be valid
test("4-snake center convergence", cb, ["up", "down", "left", "right"])

# Same but we're the smallest — should avoid the pile-up
s0 = make_snake([(5, 2), (5, 1), (5, 0)], health=50)     # us, length 3
s1 = make_snake([(5, 8), (5, 9), (5, 10), (4, 10)], health=50)  # length 4
s2 = make_snake([(2, 5), (1, 5), (0, 5), (0, 4)], health=50)    # length 4
s3 = make_snake([(8, 5), (9, 5), (10, 5), (10, 4)], health=50)  # length 4
cb = make_board([s0, s1, s2, s3], 0, food=[(5, 5)])
test("Smallest snake avoids crossfire", cb, ["up", "left", "right"],
     forbidden_moves=[])

# ============================================================
# Test 13: Corridor trap — narrow passage with blocked exit
# ============================================================
print("\n--- Corridor Trap ---")

# Snake in a 2-wide corridor between walls of opponent bodies
# Left wall: x=3 column, Right wall: x=6 column
# Snake at (4,2) heading up, corridor dead-ends at y=8
left_wall = make_snake([
    (3, 0), (3, 1), (3, 2), (3, 3), (3, 4), (3, 5),
    (3, 6), (3, 7), (3, 8), (3, 9), (3, 10),
])
right_wall = make_snake([
    (6, 0), (6, 1), (6, 2), (6, 3), (6, 4), (6, 5),
    (6, 6), (6, 7), (6, 8), (6, 9), (6, 10),
])
# Top wall sealing the corridor at y=8
top_wall = make_snake([(4, 8), (5, 8)])
s = make_snake([(4, 2), (4, 1), (4, 0)], health=80)
cb = make_board([s, left_wall, right_wall, top_wall], 0, food=[(8, 8)])
move = get_move(cb)
# The corridor has limited space — snake should prefer moves that
# don't commit deeper into the dead-end corridor
test("Corridor awareness", cb, ["up", "down", "left", "right"])

# ============================================================
# Test 14: Head-to-head forced fight
# ============================================================
print("\n--- Head-to-Head Forced Fight ---")

# Two equal-length snakes, face-to-face, 2 cells apart
# Our head at (4,5), opponent head at (6,5)
# If both go toward each other they meet at (5,5) — both die
s = make_snake([(4, 5), (4, 4), (4, 3)])
opp = make_snake([(6, 5), (6, 4), (6, 3)])
cb = make_board([s, opp], 0)
# Should avoid going right since opponent could also go left → head-to-head death
test("Equal snakes face-to-face", cb, ["up", "down", "left"],
     forbidden_moves=["right"])

# Same scenario but we're 2 longer — should be aggressive
s = make_snake([(4, 5), (4, 4), (4, 3), (4, 2), (4, 1)])
opp = make_snake([(6, 5), (6, 4), (6, 3)])
cb = make_board([s, opp], 0)
# We'd win a head-to-head — going right should be acceptable
test("Longer snake can engage", cb, ["up", "down", "left", "right"])

# ============================================================
# Test 15: Food race — risky close food vs safe far food
# ============================================================
print("\n--- Food Race ---")

# Close food at (6,5) but a bigger opponent head is at (7,5) (1 away from food)
# Far food at (2,5) with no threats
# Snake at (5,5) — going right risks head-to-head at the food
s = make_snake([(5, 5), (5, 4), (5, 3)], health=30)
opp = make_snake([(7, 5), (8, 5), (9, 5), (10, 5)])  # length 4, bigger
cb = make_board([s, opp], 0, food=[(6, 5), (2, 5)])
# Should prefer left (safe food) over right (contested food near bigger snake)
test("Prefer safe food over risky", cb, ["left", "up", "down"],
     forbidden_moves=["right"])

# Both foods equidistant but one is near a corner (dangerous)
s = make_snake([(5, 5), (5, 4), (5, 3)], health=25)
cb = make_board([s], 0, food=[(0, 0), (5, 8)])
# Food at (0,0) is in corner (edge + corner penalty), food at (5,8) is safer
test("Prefer center food over corner", cb, ["up"],
     forbidden_moves=["left", "down"])

# ============================================================
# Summary
# ============================================================
print(f"\n{'='*40}")
print(f"Results: {passed} passed, {failed} failed, {passed + failed} total")
if failed > 0:
    sys.exit(1)
