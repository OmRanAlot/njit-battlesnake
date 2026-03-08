# How the Snake Thinks: A Deep Dive into the Search Engine

This document explains the complete decision-making architecture of this Battlesnake bot — from raw board representation all the way up to the final move selection. Nothing here is off-the-shelf. Every component was designed around the specific constraints of competitive Battlesnake: four adversarial agents, a discrete grid, and a hard 500ms wall-clock deadline.

---

## The Core Problem

Battlesnake is a simultaneous multi-agent game. Every turn, all four snakes commit to a move at the same time — there's no alternating play. This rules out classical two-player minimax as a direct tool, and it makes pure heuristic approaches fragile because they can't reason about what opponents will do next.

The solution is a **paranoid minimax** formulation: we assume all opponents are working together to minimize our score. This is pessimistic but robust — it plans for the worst case and finds moves that hold up even against coordinated opposition.

Getting that search to run meaningfully within 420ms (leaving 80ms for HTTP overhead and JSON marshalling) required an unusual combination of techniques borrowed from competitive chess programming and adapted for the geometry of a snake game.

---

## Layer 1: The Bitboard — 128 Bits for 121 Cells

The entire 11×11 board is encoded in two 64-bit integers:

```
Bit index = y * 11 + x
lo  → cells 0–63   (rows 0–5, plus 8 cells of row 6)
hi  → cells 64–120 (remainder of row 6 through row 10)
```

This is the same representation used in world-class chess and checkers engines, adapted here for a non-power-of-two grid. The payoff is that bulk operations that would otherwise require looping over every cell collapse into a few CPU instructions:

- **Flood expansion in one direction:** a single bitwise shift + AND with an edge mask
- **Counting reachable cells:** `__builtin_popcountll()` on both halves — one CPU instruction each on modern hardware
- **Union of all snake bodies into a wall mask:** bitwise OR over four bitboards

Edge masks prevent wraparound artifacts when shifting across row boundaries — without them, a cell at the rightmost column would appear to neighbor the leftmost column after a left-shift.

All performance-critical algorithms — flood fill, Voronoi territory, move generation — operate directly on these bitboards without ever touching per-cell loops.

---

## Layer 2: Voronoi Territory — Who Controls What

A naive flood fill answers: "how many cells can I reach from here?" That's useful, but it doesn't account for competition. A cell you can reach in 5 steps is worthless if an opponent gets there in 3.

The engine computes true **Voronoi territory**: a simultaneous BFS expanding from every live snake head at once. Each cell is claimed by the first snake to reach it. Contested cells (reached simultaneously by two snakes) are split or discarded, depending on the tie-breaking logic.

The result is a territorial partition of the board — a precise measure of who actually controls which space. This is far more informative than per-snake flood fills because it captures the competitive geometry of the position.

Implementation uses the bitboard shift operations: at each BFS step, every snake's frontier expands by one cell in all four directions simultaneously, masked against walls and previously-claimed cells. The iteration count matches the board diameter at most, and each iteration is a handful of 64-bit operations.

Voronoi territory is the single highest-weighted term in the evaluation function. Losing territory to opponents is bad; gaining it is good.

---

## Layer 3: The Evaluation Function

When the search reaches a leaf node, it scores the position using a weighted combination of features. The weights were tuned empirically across hundreds of test games against different opponent types.

**Terminal conditions** are checked first and short-circuit everything else:
- Our snake is dead → −10,000 (hard loss)
- All opponents are dead → +10,000 (hard win)

**Spatial control:**
- Voronoi territory: +0.12 per cell we own
- Territory deficit: −0.075 for each cell the leading opponent owns beyond us
- Trapped penalty: scales smoothly from 0 to −500 as available space drops below twice our length — captures the danger of being confined before it becomes a wall collision

**Length dynamics:**
- +7.0 per cell of length advantage over each opponent
- +100 bonus for each opponent shorter than us (we can kill them in a head-to-head)
- −100 penalty for each opponent longer (they can kill us)
- +20 immediate kill bonus when an opponent dies at this search node

**Positional penalties:**
- Wall adjacency: −2.5 on the wall, −1.5 one cell away
- Corner occupancy: −7.0 (corners cut off escape routes asymmetrically)
- Center attraction: −0.4 per Manhattan distance from board center (prevents degenerate wall-hugging loops)

**Food:**
- −0.25 per Manhattan distance to nearest food, but **only** when health < 30 or length < 8
- This avoids pathological food-chasing when we're already healthy and long — the snake ignores food unless it actually needs it

**Aggression:**
- +2.5 / distance toward shorter opponents (chase them down)
- −4.5 / distance away from longer opponents (flee or give space)

**Head-to-head danger (applied only to nearby heads, distance ≤ 2.5):**
- −200 / distance if opponent is equal or greater length (we lose this collision)
- +10 / distance if we're longer (favorable engagement)

The asymmetry between the attack (+10) and defense (−200) weights reflects the game-theoretic reality: losing a head-to-head eliminates us immediately, while winning one is merely a large advantage, not an instant win.

---

## Layer 4: The Search — Paranoid Minimax with Alpha-Beta

The game tree is structured as follows:

```
Root: maximize over our 4 possible moves
  └─ For each of our moves:
       Opponent 1 moves (minimize over their choices)
         └─ Opponent 2 moves
              └─ Opponent 3 moves
                   └─ Recurse (all opponents committed → full turn resolved)
```

All opponent moves at a given ply are evaluated under the paranoid assumption that they coordinate against us. Alpha-beta pruning applies across opponent move enumeration: if the score is already worse than what we can guarantee elsewhere (beta cutoff), the remaining opponent moves are skipped.

### Opponent Branching Reduction

Fully expanding every opponent move combination explodes the branching factor: 4 moves per snake × 3 opponents = 64 joint outcomes per ply. At depth 4 that's 16 million nodes.

Instead, opponent moves are aggressively culled:
- **Depth ≤ 2:** Consider only the single best opponent move (ranked by flood fill)
- **Depth > 2:** Consider only the top 2 opponent moves

This trades theoretical completeness for practical speed, allowing the search to reach depth 4–6 within the time budget rather than stalling at depth 2–3.

### Iterative Deepening

Rather than targeting a fixed depth, the engine searches depth 1, then depth 2, then depth 3, and so on, storing the best result at each completed depth. If the clock runs out mid-search, the result from the last fully completed depth is returned.

This has two advantages:
1. The search is always responsive — there's always a valid answer ready
2. Completed shallower iterations feed move ordering into deeper ones (see below)

### Alpha-Beta Pruning and Move Ordering

Alpha-beta pruning eliminates branches that cannot affect the final result. Its effectiveness is entirely dependent on move ordering — if the best moves are searched first, more branches get pruned.

The engine uses a four-tier ordering strategy:

**1. PV-move (principal variation):** The best move found at depth N is tried first at depth N+1. This single heuristic typically saves 30–40% of nodes at each depth increment.

**2. Killer move heuristic:** Moves that caused beta cutoffs at the same depth in sibling subtrees are promoted to the front. The engine maintains two killer slots per depth level, updated whenever a cutoff occurs.

**3. Flood-fill ordering (shallow nodes, depth ≤ max−2):** Each candidate move is simulated and flood-filled; moves that preserve more reachable space are tried first. This is expensive (a full BFS per move) but pays off at shallow depths where move ordering has the most impact on pruning.

**4. Center-distance ordering (deep nodes):** At deep nodes where flood filling is too costly, moves are ordered by how far the resulting head position is from the board edge. Center-biased moves go first.

### Aspiration Windows

At depth ≥ 3, the search is initially run with a narrow score window centered on the previous depth's result:

```
[prev_score − 50, prev_score + 50]
```

If the result falls outside this window (a "fail-low" or "fail-high"), the search is re-run with a full window. This technique — borrowed directly from tournament chess engines — substantially reduces the nodes explored when the score is stable between depths, which is the common case in most positions.

### Late Move Reductions (LMR)

After the first candidate move is searched at full depth, subsequent moves are initially explored at **depth − 2** instead of depth − 1. If the reduced-depth result looks promising (beats the current alpha), it is re-searched at full depth for a precise score.

LMR exploits the observation that the first move (after good ordering) is usually the best one. Later moves are likely to fail low and can be dismissed with a cheap shallow search. This is one of the highest-impact optimizations in modern chess engines, and it applies here with similar effectiveness.

---

## Layer 5: Survival Overrides

Two special-case overrides bypass the minimax search entirely when the situation is critical.

### Urgent Food (health < 15)

When health drops to 15 or below, the snake stops thinking about the future and finds the nearest reachable food via A*. A* with Manhattan distance heuristic is optimal for unweighted grids and navigates around obstacles that a straight-line approach would hit. The move toward that food is returned immediately — no tree search, no evaluation function.

This threshold was chosen because at health 15, a search to depth 5 would include turns where we're already dead of starvation. Better to guarantee food-seeking now than to plan optimally in a game state we'll never reach.

### Head-Danger Filtering

Before the minimax search runs, moves that would place our head adjacent to an opponent head of equal or greater length are filtered out. These positions are losing by definition — if both snakes move into the shared space, we die and they don't.

If all four moves are filtered by this rule (we're completely surrounded by larger snakes), the filter is relaxed and the search proceeds normally — dying to a head-to-head is better than dying to a wall.

---

## Layer 6: Python–C++ Integration

The search engine is compiled as a shared library (`libsnake.so`) and called from Python via `ctypes`. The Python server handles:
- JSON parsing of the Battlesnake API payload
- Population of the `CBoard`/`CSnake` ctypes structs
- State tracking (whether each snake ate last turn, for correct tail simulation)
- The `get_best_move(CBoard*)` call into C++ with a timeout budget

The struct layout is kept binary-compatible between the Python `ctypes` definitions and the C++ structs — field order, primitive types, and array sizes must match exactly. One `CBoard` holds up to 4 snakes and 20 food locations, all fixed-size for cache locality.

This architecture gives Python's ergonomics for HTTP and JSON handling while delegating the 99% of CPU time — game tree search — to optimized native code.

---

## Why These Choices

Every piece of this design was a deliberate response to a specific constraint:

| Constraint | Response |
|---|---|
| 500ms wall-clock limit | Iterative deepening + aspiration windows + LMR to maximize depth in bounded time |
| 4-agent simultaneous play | Paranoid minimax with opponent branching reduction |
| Need for fast bulk board ops | 128-bit bitboard representation |
| Territory control matters more than raw space | Voronoi territory over simple flood fill |
| Starvation is an instant loss | Urgent A* override at health < 15 |
| Head-to-head losses are asymmetric | Asymmetric danger weights + pre-search filtering |
| Alpha-beta needs good move ordering | PV-move + killer heuristic + flood-fill ordering |

The result is a bot that can reliably search 4–6 plies deep in four-snake games within the time budget, reason accurately about territory and threats, and fall back safely when the clock or health is low.
