#pragma once

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstring>

// ============================================================
// Constants
// ============================================================

static const int BOARD_W = 11;
static const int BOARD_H = 11;
static const int BOARD_CELLS = BOARD_W * BOARD_H; // 121
static const int MAX_SNAKES = 4;
static const int MAX_BODY = 121;
static const int MAX_FOOD = 20;

// Directions: 0=up, 1=down, 2=left, 3=right
static const int DX[4] = {0, 0, -1, 1};
static const int DY[4] = {1, -1, 0, 0};
static const char *DIR_NAMES[4] = {"up", "down", "left", "right"};

// ============================================================
// 128-bit Bitboard (two uint64_t for 121 cells)
// Represents the 11x11 board (121 cells) using two 64-bit integers.
// Allows for extremely fast bitwise parallel operations (like flood fill).
// ============================================================

struct Bitboard {
  uint64_t lo; // bits 0-63 - exactly 64 bits
  uint64_t hi; // bits 64-120 - exactly 57 bits

  inline Bitboard() : lo(0), hi(0) {}
  inline Bitboard(uint64_t l, uint64_t h) : lo(l), hi(h) {}

  inline void set(int idx) {
    if (idx < 64)
      lo |= (1ULL << idx); // set bit idx in lo
    else
      hi |= (1ULL << (idx - 64)); // set bit idx in hi
  }

  inline void clear(int idx) {
    if (idx < 64)
      lo &= ~(1ULL << idx); // clear bit idx in lo
    else
      hi &= ~(1ULL << (idx - 64)); // clear bit idx in hi
  }

  inline bool get(int idx) const {
    if (idx < 64)
      return (lo >> idx) & 1; // get bit idx in lo
    else
      return (hi >> (idx - 64)) & 1; // get bit idx in hi
  }

  inline int popcount() const {
    return __builtin_popcountll(lo) +
           __builtin_popcountll(hi); // count bits in lo and hi
  }

  inline bool empty() const {
    return lo == 0 && hi == 0;
  } // check if both lo and hi are 0

  inline Bitboard operator|(const Bitboard &o) const {
    return {lo | o.lo, hi | o.hi}; // union of lo and hi
  }
  inline Bitboard operator&(const Bitboard &o) const {
    return {lo & o.lo, hi & o.hi}; // intersection of lo and hi
  }
  inline Bitboard operator~() const {
    return {~lo, ~hi};
  } // complement of lo and hi
  inline Bitboard operator^(const Bitboard &o) const {
    return {lo ^ o.lo, hi ^ o.hi}; // XOR of lo and hi
  }
  inline bool operator==(const Bitboard &o) const {
    return lo == o.lo && hi == o.hi; // check if both lo and hi are equal
  }
  inline bool operator!=(const Bitboard &o) const {
    return !(*this == o);
  } // check if both lo and hi are not equal

  inline Bitboard &operator|=(const Bitboard &o) {
    lo |= o.lo; // union of lo and hi
    hi |= o.hi;
    return *this;
  }
  inline Bitboard &operator&=(const Bitboard &o) {
    lo &= o.lo; // intersection of lo and hi
    hi &= o.hi;
    return *this;
  }
};

// Full mask: bits 0..120 set
static const Bitboard FULL_MASK = {
    0xFFFFFFFFFFFFFFFFULL,
    0x01FFFFFFFFFFFFFFULL // bits 64..120 = 57 bits
};

// Edge masks for preventing wraparound in shifts
// LEFT_EDGE: column 0 (x=0) — bits where x=0: indices 0, 11, 22, ...
// RIGHT_EDGE: column 10 (x=10) — bits where x=10: indices 10, 21, 32, ...
inline Bitboard make_column_mask(int col) {
  Bitboard b;
  for (int y = 0; y < BOARD_H; y++) {
    b.set(y * BOARD_W + col);
  }
  return b;
}

// Precomputed at startup via a function
struct Masks {
  Bitboard left_edge;  // column 0
  Bitboard right_edge; // column 10
  Bitboard row_masks[BOARD_H];

  Masks() {
    left_edge = make_column_mask(0);
    right_edge = make_column_mask(BOARD_W - 1);
    for (int y = 0; y < BOARD_H; y++) {
      row_masks[y] = Bitboard();
      for (int x = 0; x < BOARD_W; x++) {
        row_masks[y].set(y * BOARD_W + x);
      }
    }
  }
};

static const Masks MASKS;

// Shift bitboard in a direction (with edge masking)
// These functions efficiently move all set bits in a given direction
// simultaneously, applying masks to prevent wrapping from opposite edges of the
// board.
inline Bitboard shift_up(const Bitboard &b) {
  // UP = y+1 = index + 11 (left-shift all bits by 11)
  // Bits from lo that overflow past bit 63 carry into hi
  Bitboard r;
  r.lo = b.lo << BOARD_W;
  r.hi = (b.hi << BOARD_W) | (b.lo >> (64 - BOARD_W));
  return r & FULL_MASK;
}

inline Bitboard shift_down(const Bitboard &b) {
  // DOWN = y-1 = index - 11
  Bitboard r;
  r.lo = (b.lo >> BOARD_W) | (b.hi << (64 - BOARD_W));
  r.hi = b.hi >> BOARD_W;
  return r & FULL_MASK;
}

inline Bitboard shift_left(const Bitboard &b) {
  // LEFT = x-1 = index - 1, but must not wrap column 0 → column 10
  Bitboard masked = b & (~MASKS.left_edge);
  Bitboard r;
  r.lo = (masked.lo >> 1) | (masked.hi << 63);
  r.hi = masked.hi >> 1;
  return r & FULL_MASK;
}

inline Bitboard shift_right(const Bitboard &b) {
  // RIGHT = x+1 = index + 1, but must not wrap column 10 → column 0
  Bitboard masked = b & (~MASKS.right_edge);
  Bitboard r;
  r.lo = (masked.lo << 1);
  r.hi = (masked.hi << 1) | (masked.lo >> 63);
  return r & FULL_MASK;
}

inline Bitboard shift_dir(const Bitboard &b, int dir) {
  switch (dir) {
  case 0:
    return shift_up(b);
  case 1:
    return shift_down(b);
  case 2:
    return shift_left(b);
  case 3:
    return shift_right(b);
  default:
    return b;
  }
}

// ============================================================
// Snake and Board State
// Optimized structs to represent the game state without dynamic memory
// allocation, which is crucial for millions of state copies during the Minimax
// tree search.
// ============================================================

struct Snake {
  int body_x[MAX_BODY];
  int body_y[MAX_BODY];
  int length;
  int health;
  bool alive;
  bool ate_last_turn; // tail doesn't move if true
};

struct Board {
  Snake snakes[MAX_SNAKES];
  int num_snakes;
  int food_x[MAX_FOOD];
  int food_y[MAX_FOOD];
  int num_food;
  int my_index; // which snake is "me"

  // Cached bitboards (rebuilt with build_bitboards())
  Bitboard occupied; // all snake bodies
  Bitboard food_board;
  Bitboard snake_bodies[MAX_SNAKES];
  Bitboard snake_heads[MAX_SNAKES];
};

inline int coord_to_idx(int x, int y) { return y * BOARD_W + x; }

inline void idx_to_coord(int idx, int &x, int &y) {
  x = idx % BOARD_W;
  y = idx / BOARD_W;
}

inline bool in_bounds(int x, int y) {
  return x >= 0 && x < BOARD_W && y >= 0 && y < BOARD_H;
}

inline void build_bitboards(Board &b) {
  b.occupied = Bitboard();
  b.food_board = Bitboard();

  for (int i = 0; i < b.num_snakes; i++) {
    // reset bitboards
    b.snake_bodies[i] = Bitboard();
    b.snake_heads[i] = Bitboard();

    if (!b.snakes[i].alive)
      continue;

    const Snake &s = b.snakes[i];
    for (int j = 0; j < s.length; j++) {
      // Maps snake body to bitboard
      int idx = coord_to_idx(s.body_x[j], s.body_y[j]);
      b.snake_bodies[i].set(idx);
      b.occupied.set(idx);
    }
    // Maps snake heads to bitboard
    b.snake_heads[i].set(coord_to_idx(s.body_x[0], s.body_y[0]));
  }

  for (int i = 0; i < b.num_food; i++) {
    b.food_board.set(coord_to_idx(b.food_x[i], b.food_y[i]));
  }
}

// ============================================================
// Flood Fill (bitboard BFS)
// Uses bitwise shifts to expand outwards in all 4 directions simultaneously.
// Incredibly fast way to calculate available space (Voronoi approximation).
// ============================================================

inline int flood_fill(const Bitboard &start, const Bitboard &walls) {
  Bitboard open = ~walls & FULL_MASK;
  Bitboard filled = start & open;
  if (filled.empty())
    return 0;

  while (true) {
    Bitboard expanded = filled | shift_up(filled) | shift_down(filled) |
                        shift_left(filled) | shift_right(filled);
    expanded = expanded & open;
    if (expanded == filled)
      break;
    filled = expanded;
  }
  return filled.popcount();
}

// Flood fill returning the actual filled bitboard
inline Bitboard flood_fill_board(const Bitboard &start, const Bitboard &walls) {
  Bitboard open = ~walls & FULL_MASK;
  Bitboard filled = start & open;
  if (filled.empty())
    return filled;

  while (true) {
    Bitboard expanded = filled | shift_up(filled) | shift_down(filled) |
                        shift_left(filled) | shift_right(filled);
    expanded = expanded & open;
    if (expanded == filled)
      break;
    filled = expanded;
  }
  return filled;
}

// Simultaneous multi-source BFS to calculate Voronoi territory for all snakes
inline void compute_voronoi(const Board &b, const Bitboard &walls,
                            int voronoi_counts[MAX_SNAKES]) {
  Bitboard claimed[MAX_SNAKES];
  Bitboard fronts[MAX_SNAKES];

  // Initialize starting fronts at snake heads
  Bitboard any_front;
  for (int i = 0; i < b.num_snakes; i++) {
    voronoi_counts[i] = 0;
    if (!b.snakes[i].alive)
      continue;

    fronts[i].set(coord_to_idx(b.snakes[i].body_x[0], b.snakes[i].body_y[0]));
    claimed[i] = fronts[i];
    any_front |= fronts[i];
  }

  Bitboard unowned = ~walls & ~any_front & FULL_MASK;

  // Expand simultaneously until no snake can expand further
  while (!any_front.empty()) {
    Bitboard next_fronts[MAX_SNAKES];
    Bitboard all_next_fronts;

    // 1. Propose expansions
    for (int i = 0; i < b.num_snakes; i++) {
      if (fronts[i].empty())
        continue;

      Bitboard expansion = shift_up(fronts[i]) | shift_down(fronts[i]) |
                           shift_left(fronts[i]) | shift_right(fronts[i]);

      // Only expand into currently unowned territory
      next_fronts[i] = expansion & unowned;
      all_next_fronts |= next_fronts[i];
    }

    // 2. Identify and resolve collisions (contested cells)
    // A cell is contested if multiple snakes try to claim it on the exact same
    // turn. We handle this by giving it to neither (or could give to both, but
    // neither is simpler).
    Bitboard contested;
    for (int i = 0; i < b.num_snakes; i++) {
      for (int j = i + 1; j < b.num_snakes; j++) {
        contested |= (next_fronts[i] & next_fronts[j]);
      }
    }

    // 3. Finalize claims
    any_front = Bitboard();
    for (int i = 0; i < b.num_snakes; i++) {
      // Remove contested cells from the expansion
      fronts[i] = next_fronts[i] & ~contested;
      claimed[i] |= fronts[i];
      any_front |= fronts[i];
    }

    // 4. Update unowned territory
    unowned &= ~all_next_fronts;
  }

  // Count territory
  for (int i = 0; i < b.num_snakes; i++) {
    if (b.snakes[i].alive) {
      voronoi_counts[i] = claimed[i].popcount();
    }
  }
}

// ============================================================
// Build wall bitboard (all snake bodies, minus tails that will move)
// Creates a bitboard of all obstacles. Note that snake tails are NOT counted as
// walls if the snake did not eat, because the tail will move out of the way on
// the next turn.
// ============================================================

inline Bitboard build_walls(const Board &b) {
  Bitboard walls;
  for (int i = 0; i < b.num_snakes; i++) {
    if (!b.snakes[i].alive)
      continue;
    const Snake &s = b.snakes[i];
    for (int j = 0; j < s.length; j++) {
      // Tail is passable if snake didn't eat last turn
      if (j == s.length - 1 && !s.ate_last_turn)
        continue;
      walls.set(coord_to_idx(s.body_x[j], s.body_y[j]));
    }
  }
  return walls;
}

// Build walls that also include head danger zones — squares adjacent to
// opponent heads where we'd lose or tie a head-to-head collision.
// Used for our own move filtering so we avoid stepping into kill zones.
inline Bitboard build_walls_with_head_danger(const Board &b) {
  Bitboard walls = build_walls(b);
  const Snake &me = b.snakes[b.my_index];

  for (int i = 0; i < b.num_snakes; i++) {
    if (i == b.my_index || !b.snakes[i].alive)
      continue;
    const Snake &opp = b.snakes[i];

    // If the opponent is >= our length, any square their head can reach
    // next turn is lethal (we lose or tie in head-to-head)
    if (opp.length >= me.length) {
      int ohx = opp.body_x[0], ohy = opp.body_y[0];
      for (int d = 0; d < 4; d++) {
        int nx = ohx + DX[d];
        int ny = ohy + DY[d];
        if (in_bounds(nx, ny)) {
          walls.set(coord_to_idx(nx, ny));
        }
      }
    }
  }
  return walls;
}

// ============================================================
// Move simulation
// ============================================================

inline void apply_move(Board &b, int snake_idx, int dir) {
  Snake &s = b.snakes[snake_idx];
  if (!s.alive)
    return;

  int new_x = s.body_x[0] + DX[dir];
  int new_y = s.body_y[0] + DY[dir];

  // Shift body backward
  if (!s.ate_last_turn) {
    // Normal: drop tail
    for (int j = s.length - 1; j > 0; j--) {
      s.body_x[j] = s.body_x[j - 1];
      s.body_y[j] = s.body_y[j - 1];
    }
  } else {
    // Grew: keep tail, shift everything else
    // length increases by 1
    s.length++;
    for (int j = s.length - 1; j > 0; j--) {
      s.body_x[j] = s.body_x[j - 1];
      s.body_y[j] = s.body_y[j - 1];
    }
  }

  s.body_x[0] = new_x;
  s.body_y[0] = new_y;
  s.health--;
  s.ate_last_turn = false;

  // Check food consumption
  for (int f = 0; f < b.num_food; f++) {
    if (b.food_x[f] == new_x && b.food_y[f] == new_y) {
      s.health = 100;
      s.ate_last_turn = true;
      // Remove food
      b.food_x[f] = b.food_x[b.num_food - 1];
      b.food_y[f] = b.food_y[b.num_food - 1];
      b.num_food--;
      break;
    }
  }
}

inline void resolve_deaths(Board &b) {
  bool dead[MAX_SNAKES] = {};

  for (int i = 0; i < b.num_snakes; i++) {
    if (!b.snakes[i].alive)
      continue;
    const Snake &s = b.snakes[i];
    int hx = s.body_x[0], hy = s.body_y[0];

    // Out of bounds
    if (!in_bounds(hx, hy)) {
      dead[i] = true;
      continue;
    }

    // Starvation
    if (s.health <= 0) {
      dead[i] = true;
      continue;
    }

    // Body collision (with any snake's body, excluding heads)
    for (int j = 0; j < b.num_snakes; j++) {
      if (!b.snakes[j].alive)
        continue;
      const Snake &other = b.snakes[j];
      int start = (i == j) ? 1 : 0; // skip own head
      for (int k = start; k < other.length; k++) {
        // Skip other snake's head (head-to-head handled separately)
        if (k == 0 && i != j)
          continue;
        if (other.body_x[k] == hx && other.body_y[k] == hy) {
          dead[i] = true;
          break;
        }
      }
      if (dead[i])
        break;
    }
  }

  // Head-to-head collisions
  for (int i = 0; i < b.num_snakes; i++) {
    if (!b.snakes[i].alive || dead[i])
      continue;
    for (int j = i + 1; j < b.num_snakes; j++) {
      if (!b.snakes[j].alive || dead[j])
        continue;
      if (b.snakes[i].body_x[0] == b.snakes[j].body_x[0] &&
          b.snakes[i].body_y[0] == b.snakes[j].body_y[0]) {
        if (b.snakes[i].length > b.snakes[j].length) {
          dead[j] = true;
        } else if (b.snakes[j].length > b.snakes[i].length) {
          dead[i] = true;
        } else {
          dead[i] = true;
          dead[j] = true;
        }
      }
    }
  }

  for (int i = 0; i < b.num_snakes; i++) {
    if (dead[i])
      b.snakes[i].alive = false;
  }
}

// ============================================================
// Evaluation function
// Calculates a heuristic score for the current board state from our snake's
// perspective. Positive scores are good, negative are bad. Applied at leaf
// nodes of Minimax.
// ============================================================

inline double evaluate(const Board &b) {

  const Snake &me = b.snakes[b.my_index];
  if (!me.alive)
    return -10000.0;

  // Count alive opponents
  int alive_opponents = 0;
  int dead_opponents = 0;
  for (int i = 0; i < b.num_snakes; i++) {
    if (i == b.my_index)
      continue;
    if (b.snakes[i].alive)
      alive_opponents++;
    else
      dead_opponents++;
  }

  // If we're the only one alive, we win
  if (alive_opponents == 0 && me.alive)
    return 10000.0;

  double score = 0.0;

  // Build walls for flood fill
  Bitboard walls = build_walls(b);

  int hx = me.body_x[0], hy = me.body_y[0];
  int head_idx = coord_to_idx(hx, hy);

  // 1. Space advantage (Voronoi Territory - MOST IMPORTANT)
  int voronoi_counts[MAX_SNAKES];
  compute_voronoi(b, walls, voronoi_counts);
  int my_space = voronoi_counts[b.my_index];
  score += my_space * 0.12;

  // Penalize if opponents have significantly more territory
  for (int i = 0; i < b.num_snakes; i++) {
    if (i == b.my_index || !b.snakes[i].alive)
      continue;
    if (voronoi_counts[i] > my_space) {
      score -= (voronoi_counts[i] - my_space) * 0.075;
    }
  }

  // Graduated trapped penalty — use actual flood-fill reachable space from
  // our head, NOT Voronoi territory. Voronoi counts cells geometrically closer
  // to our head but ignores whether our own body blocks them. When the snake
  // curls into a shrinking corridor, its Voronoi count stays high (all the
  // cells on "our side") while actual reachable space collapses — causing the
  // old code to never trigger this penalty and the snake to keep turning into
  // its own trap. Using flood fill correctly detects the shrinking corridor.
  Bitboard head_start;
  head_start.set(head_idx);
  int actual_reachable = flood_fill(head_start, walls);
  if (actual_reachable < me.length * 2) {
    double ratio = (double)actual_reachable / (double)(me.length * 2);
    score -= (1.0 - ratio) * 500.0;
  }

  // 2. Length advantage
  for (int i = 0; i < b.num_snakes; i++) {
    if (i == b.my_index || !b.snakes[i].alive)
      continue;
    score += (me.length - b.snakes[i].length) * 7.0;
    // checks if smallest snake
    if (b.snakes[i].length < me.length) {
      score += 100.0;
    }
    // checks if largest snake
    if (b.snakes[i].length > me.length) {
      score -= 100.0;
    }
  }

  // 3. Food proximity (activates when health < 30 or when length is less than
  // 8)
  if ((me.health < 30 || me.length < 8) && b.num_food > 0) {
    int min_dist = 999;
    for (int f = 0; f < b.num_food; f++) {
      int dist = abs(hx - b.food_x[f]) + abs(hy - b.food_y[f]);
      if (dist < min_dist)
        min_dist = dist;
    }
    score -= min_dist * 0.25;
  }

  // 4. Edge penalty
  if (hx == 0 || hx == BOARD_W - 1)
    score -= 2.5;
  else if (hx == 1 || hx == BOARD_W - 2)
    score -= 1.5;

  if (hy == 0 || hy == BOARD_H - 1)
    score -= 2.5;
  else if (hy == 1 || hy == BOARD_H - 2)
    score -= 1.5;

  // 5. Corner penalty
  if ((hx == 0 || hx == BOARD_W - 1) && (hy == 0 || hy == BOARD_H - 1)) {
    score -= 7.0;
  }

  // 5b. Center attraction — gentle pull toward board center to prevent
  // wall-hugging loops when all other heuristics are tied
  double center_dist = abs(hx - BOARD_W / 2) + abs(hy - BOARD_H / 2);
  score -= center_dist * 0.4;

  // 6. Aggression: chase smaller snakes, flee larger
  for (int i = 0; i < b.num_snakes; i++) {
    if (i == b.my_index || !b.snakes[i].alive)
      continue;
    int dist =
        abs(hx - b.snakes[i].body_x[0]) + abs(hy - b.snakes[i].body_y[0]);
    if (dist > 0) {
      if (me.length > b.snakes[i].length) {
        // Chase smaller snakes (closer = better)
        score += 2.5 / dist;
      } else {
        // Flee larger snakes (closer = worse)
        score -= 4.5 / dist;
      }
    }
  }

  // 7. Kill bonus
  score += dead_opponents * 20.0;

  // 8. Head-to-head danger penalty — if our head is adjacent to an opponent's
  // head, penalize heavily if we'd lose or tie (opponent length >= ours).
  // Reward if we'd win (we're longer) since that's a kill opportunity.
  for (int i = 0; i < b.num_snakes; i++) {
    if (i == b.my_index || !b.snakes[i].alive)
      continue;
    int ohx = b.snakes[i].body_x[0], ohy = b.snakes[i].body_y[0];
    int head_dist = abs(hx - ohx) + abs(hy - ohy);
    if (head_dist <= 2.5) {
      if (b.snakes[i].length >= me.length) {
        // We'd lose or tie — avoid this position hard
        score -= 200.0 / head_dist;
      } else {
        // We'd win — this is a kill opportunity
        score += 10.0 / head_dist;
      }
    }
  }

  return score;
}

// ============================================================
// A* Pathfinding — finds shortest safe path from (sx,sy) to (gx,gy)
// Returns the first-step direction (0-3) or -1 if no path exists.
// Uses Manhattan distance as heuristic (admissible on a grid).
// ============================================================

struct AStarNode {
  int x, y;
  int g;    // cost so far (steps taken)
  int f;    // g + heuristic (estimated total)
  int dir0; // direction of the FIRST step from the start (what we return)
};

inline int astar(int sx, int sy, int gx, int gy, const Bitboard &walls) {
  // closed set: which cells have been visited
  bool closed[BOARD_CELLS] = {};

  // Open list as a simple array-based min-heap on f-value.
  // Max possible entries = BOARD_CELLS (121), so fixed-size is fine.
  AStarNode open[BOARD_CELLS];
  int open_size = 0;

  // Helper: push onto min-heap sorted by f
  auto push = [&](AStarNode node) {
    open[open_size] = node;
    // Sift up
    int i = open_size++;
    while (i > 0) {
      int parent = (i - 1) / 2;
      if (open[i].f < open[parent].f) {
        std::swap(open[i], open[parent]);
        i = parent;
      } else
        break;
    }
  };

  // Helper: pop min-f node
  auto pop = [&]() -> AStarNode {
    AStarNode result = open[0];
    open[0] = open[--open_size];
    // Sift down
    int i = 0;
    while (true) {
      int left = 2 * i + 1, right = 2 * i + 2, smallest = i;
      if (left < open_size && open[left].f < open[smallest].f)
        smallest = left;
      if (right < open_size && open[right].f < open[smallest].f)
        smallest = right;
      if (smallest != i) {
        std::swap(open[i], open[smallest]);
        i = smallest;
      } else
        break;
    }
    return result;
  };

  // Seed: start position, g=0, no first-step yet
  int h0 = abs(sx - gx) + abs(sy - gy);
  push({sx, sy, 0, h0, -1});

  while (open_size > 0) {
    AStarNode cur = pop();

    int idx = coord_to_idx(cur.x, cur.y);
    if (closed[idx])
      continue;
    closed[idx] = true;

    // Reached the goal — return the direction of our very first step
    if (cur.x == gx && cur.y == gy)
      return cur.dir0;

    // Expand neighbors
    for (int d = 0; d < 4; d++) {
      int nx = cur.x + DX[d];
      int ny = cur.y + DY[d];
      if (!in_bounds(nx, ny))
        continue;
      int nidx = coord_to_idx(nx, ny);
      if (closed[nidx])
        continue;
      if (walls.get(nidx))
        continue;

      int ng = cur.g + 1;
      int nh = abs(nx - gx) + abs(ny - gy);
      // On the first expansion from start, record which direction we went
      int first_dir = (cur.dir0 == -1) ? d : cur.dir0;
      push({nx, ny, ng, ng + nh, first_dir});
    }
  }

  return -1; // no path found
}

// A* food search: finds the closest reachable food and returns the first-step
// direction toward it. Returns -1 if no food is reachable.
inline int astar_closest_food(const Board &b, int snake_idx) {
  const Snake &s = b.snakes[snake_idx];
  if (!s.alive)
    return -1;

  Bitboard walls = build_walls(b);
  int hx = s.body_x[0], hy = s.body_y[0];

  int best_dir = -1;
  int best_dist = 9999;

  for (int f = 0; f < b.num_food; f++) {
    int fx = b.food_x[f], fy = b.food_y[f];

    // Quick Manhattan lower bound — skip if it can't beat current best
    int manhattan = abs(hx - fx) + abs(hy - fy);
    if (manhattan >= best_dist)
      continue;

    int dir = astar(hx, hy, fx, fy, walls);
    if (dir == -1)
      continue; // unreachable

    // We need actual path length. A* with Manhattan heuristic on a uniform grid
    // guarantees the first path found is shortest, but we only stored the
    // first-step direction. Re-run to get the g-cost? No — since A* is optimal
    // on a grid and we check Manhattan first, the actual path length >=
    // manhattan. We just use Manhattan as a proxy for "closest" since it's a
    // lower bound and the paths are usually close to Manhattan distance on open
    // boards.
    if (manhattan < best_dist) {
      best_dist = manhattan;
      best_dir = dir;
    }
  }

  return best_dir;
}

// ============================================================
// Flood-fill best move (fast fallback)
// ============================================================

inline int flood_fill_best_move(const Board &b, int snake_idx) {
  const Snake &s = b.snakes[snake_idx];
  if (!s.alive)
    return 0;

  // Use head-danger walls for our snake so we avoid stepping next to
  // larger/equal opponent heads. Use normal walls for opponents.
  Bitboard walls = (snake_idx == b.my_index) ? build_walls_with_head_danger(b)
                                             : build_walls(b);
  int hx = s.body_x[0], hy = s.body_y[0];

  int best_dir = 0;
  int best_space = -1;
  int best_center_dist = 999;

  for (int d = 0; d < 4; d++) {
    int nx = hx + DX[d];
    int ny = hy + DY[d];
    if (!in_bounds(nx, ny))
      continue;
    int idx = coord_to_idx(nx, ny);
    if (walls.get(idx))
      continue;

    Bitboard start;
    start.set(idx);
    int space = flood_fill(start, walls);
    int center_dist = abs(nx - BOARD_W / 2) + abs(ny - BOARD_H / 2);
    // Prefer more space; break ties by preferring moves closer to center
    if (space > best_space ||
        (space == best_space && center_dist < best_center_dist)) {
      best_space = space;
      best_center_dist = center_dist;
      best_dir = d;
    }
  }
  return best_dir;
}

// ============================================================
// Minimax with Alpha-Beta Pruning + Optimizations
// - PV-move ordering from previous iteration
// - Late Move Reductions (LMR)
// - Reduced opponent branching at deeper depths
// - Lightweight opponent move ordering at deep nodes
// - Killer move heuristic
// ============================================================

static const int MAX_DEPTH = 25;

struct SearchState {
  std::chrono::steady_clock::time_point deadline;
  bool timed_out;
  int nodes_searched;
  // Killer moves: moves that caused beta cutoffs at each depth
  int killer_moves[MAX_DEPTH][2];
};

// Get number of valid (non-wall) moves for a snake — cheap, no flood fill
inline int count_safe_moves(const Board &b, int snake_idx,
                            const Bitboard &walls) {
  const Snake &s = b.snakes[snake_idx];
  int count = 0;
  for (int d = 0; d < 4; d++) {
    int nx = s.body_x[0] + DX[d];
    int ny = s.body_y[0] + DY[d];
    if (in_bounds(nx, ny) && !walls.get(coord_to_idx(nx, ny)))
      count++;
  }
  return count;
}

// Lightweight opponent move generation: no flood fill, just validity check.
// Used at deeper depths where full flood-fill ordering is too expensive.
inline int get_opp_moves_fast(const Board &b, int snake_idx,
                              const Bitboard &walls, int out_moves[4]) {
  const Snake &s = b.snakes[snake_idx];
  int hx = s.body_x[0], hy = s.body_y[0];
  int count = 0;
  for (int d = 0; d < 4; d++) {
    int nx = hx + DX[d];
    int ny = hy + DY[d];
    if (in_bounds(nx, ny) && !walls.get(coord_to_idx(nx, ny)))
      out_moves[count++] = d;
  }
  if (count == 0) {
    out_moves[0] = 0; // doomed move
    return 1;
  }
  return count;
}

inline double minimax(Board &b, int depth, double alpha, double beta,
                      bool maximizing, SearchState &ss, int max_depth) {
  if (ss.timed_out)
    return 0.0;

  ss.nodes_searched++;

  // Check timeout periodically (every 1024 nodes to reduce overhead)
  if ((ss.nodes_searched & 1023) == 0) {
    if (std::chrono::steady_clock::now() >= ss.deadline) {
      ss.timed_out = true;
      return 0.0;
    }
  }

  // Terminal checks
  if (!b.snakes[b.my_index].alive)
    return -10000.0;

  int alive_count = 0;
  for (int i = 0; i < b.num_snakes; i++) {
    if (b.snakes[i].alive)
      alive_count++;
  }
  if (alive_count <= 1)
    return evaluate(b);

  if (depth == 0)
    return evaluate(b);

  if (maximizing) {
    const Snake &me = b.snakes[b.my_index];
    int hx = me.body_x[0], hy = me.body_y[0];

    // At shallow depths, use full flood-fill move ordering.
    // At deep depths, use lightweight ordering to save time.
    bool use_full_ordering = (depth >= max_depth - 2);

    Bitboard safe_walls = build_walls(b);

    struct MoveScore {
      int dir;
      int space;
      int center_dist;
    };
    MoveScore moves[4];
    int num_moves = 0;

    if (use_full_ordering) {
      Bitboard danger_walls = build_walls_with_head_danger(b);

      for (int d = 0; d < 4; d++) {
        int nx = hx + DX[d];
        int ny = hy + DY[d];
        if (!in_bounds(nx, ny))
          continue;
        int idx = coord_to_idx(nx, ny);
        if (danger_walls.get(idx))
          continue;

        Bitboard start;
        start.set(idx);
        int space = flood_fill(start, safe_walls);
        int cdist = abs(nx - BOARD_W / 2) + abs(ny - BOARD_H / 2);
        moves[num_moves] = {d, space, cdist};
        num_moves++;
      }

      // Fallback if danger walls blocked everything
      if (num_moves == 0) {
        for (int d = 0; d < 4; d++) {
          int nx = hx + DX[d];
          int ny = hy + DY[d];
          if (!in_bounds(nx, ny))
            continue;
          int idx = coord_to_idx(nx, ny);
          if (safe_walls.get(idx))
            continue;

          Bitboard start;
          start.set(idx);
          int space = flood_fill(start, safe_walls);
          int cdist = abs(nx - BOARD_W / 2) + abs(ny - BOARD_H / 2);
          moves[num_moves] = {d, space, cdist};
          num_moves++;
        }
      }
    } else {
      // Lightweight: just check validity, use center distance for ordering
      for (int d = 0; d < 4; d++) {
        int nx = hx + DX[d];
        int ny = hy + DY[d];
        if (!in_bounds(nx, ny))
          continue;
        int idx = coord_to_idx(nx, ny);
        if (safe_walls.get(idx))
          continue;
        int cdist = abs(nx - BOARD_W / 2) + abs(ny - BOARD_H / 2);
        moves[num_moves] = {d, 0, cdist};
        num_moves++;
      }
    }

    // Killer move heuristic: try killer moves first
    int cur_depth_idx = max_depth - depth;
    if (cur_depth_idx >= 0 && cur_depth_idx < MAX_DEPTH) {
      for (int ki = 0; ki < 2; ki++) {
        int killer = ss.killer_moves[cur_depth_idx][ki];
        if (killer < 0)
          continue;
        // Find killer in moves and swap to front
        for (int m = 1; m < num_moves; m++) {
          if (moves[m].dir == killer) {
            std::swap(moves[0], moves[m]);
            break;
          }
        }
      }
    }

    // Sort descending by space, then ascending by center distance
    // (killer move swap may have already placed best move first)
    if (use_full_ordering) {
      for (int i = 0; i < num_moves - 1; i++) {
        for (int j = i + 1; j < num_moves; j++) {
          if (moves[j].space > moves[i].space ||
              (moves[j].space == moves[i].space &&
               moves[j].center_dist < moves[i].center_dist)) {
            std::swap(moves[i], moves[j]);
          }
        }
      }
    }

    if (num_moves == 0)
      return -10000.0;

    double best = -100000.0;

    for (int m = 0; m < num_moves; m++) {
      Board copy = b;
      apply_move(copy, b.my_index, moves[m].dir);

      // At deeper depths, reduce opponent branching to top-1 move
      // to dramatically cut the branching factor
      int max_opp_keep = (depth <= 2) ? 1 : 2;

      // Pre-compute opponent moves
      int opp_moves[MAX_SNAKES][4];
      int num_opp_moves[MAX_SNAKES];
      Bitboard copy_walls = build_walls(copy);

      for (int i = 0; i < b.num_snakes; i++) {
        num_opp_moves[i] = 0;
        if (i == b.my_index || !copy.snakes[i].alive)
          continue;

        if (depth <= 3) {
          // Deep node: fast move gen, no flood fill
          int fast_moves[4];
          int n = get_opp_moves_fast(copy, i, copy_walls, fast_moves);
          int keep = (n > max_opp_keep) ? max_opp_keep : n;
          for (int k = 0; k < keep; k++)
            opp_moves[i][k] = fast_moves[k];
          num_opp_moves[i] = keep;
        } else {
          // Shallow node: full flood-fill ordering
          int hx_opp = copy.snakes[i].body_x[0];
          int hy_opp = copy.snakes[i].body_y[0];

          MoveScore o_moves[4];
          int o_num = 0;
          for (int d = 0; d < 4; d++) {
            int nx = hx_opp + DX[d];
            int ny = hy_opp + DY[d];
            if (!in_bounds(nx, ny))
              continue;
            int idx = coord_to_idx(nx, ny);
            if (copy_walls.get(idx))
              continue;

            Bitboard start;
            start.set(idx);
            o_moves[o_num] = {d, flood_fill(start, copy_walls), 0};
            o_num++;
          }

          for (int x = 0; x < o_num - 1; x++) {
            for (int y = x + 1; y < o_num; y++) {
              if (o_moves[y].space > o_moves[x].space)
                std::swap(o_moves[x], o_moves[y]);
            }
          }

          int keep = (o_num > max_opp_keep) ? max_opp_keep : o_num;
          if (keep == 0) {
            opp_moves[i][0] = 0;
            num_opp_moves[i] = 1;
          } else {
            for (int m2 = 0; m2 < keep; m2++)
              opp_moves[i][m2] = o_moves[m2].dir;
            num_opp_moves[i] = keep;
          }
        }
      }

      // Recursive lambda to apply combinations of opponent moves
      auto eval_opp_combinations = [&](auto &self, Board current_board,
                                       int current_opp_idx, double a,
                                       double bt) -> double {
        if (ss.timed_out)
          return 0.0;

        if (current_opp_idx == current_board.num_snakes) {
          resolve_deaths(current_board);
          build_bitboards(current_board);
          return minimax(current_board, depth - 1, a, bt, true, ss, max_depth);
        }

        if (current_opp_idx == current_board.my_index ||
            !current_board.snakes[current_opp_idx].alive) {
          return self(self, current_board, current_opp_idx + 1, a, bt);
        }

        double opp_best = 100000.0;

        for (int k = 0; k < num_opp_moves[current_opp_idx]; k++) {
          Board next_b = current_board;
          apply_move(next_b, current_opp_idx, opp_moves[current_opp_idx][k]);

          double val = self(self, next_b, current_opp_idx + 1, a, bt);

          if (val < opp_best)
            opp_best = val;
          if (opp_best < bt)
            bt = opp_best;
          if (a >= bt)
            break;
        }

        return opp_best;
      };

      // Late Move Reductions (LMR): search moves after the first at
      // reduced depth. If the reduced search beats alpha, re-search
      // at full depth to get the accurate score.
      double val;
      if (m >= 2 && depth >= 4 && !use_full_ordering) {
        // Reduced depth search first
        Board lmr_copy = copy;
        // Temporarily reduce depth by 1
        int saved_depth = depth;
        // Use a shallower search
        auto eval_lmr = [&](auto &self, Board current_board,
                            int current_opp_idx, double a,
                            double bt) -> double {
          if (ss.timed_out)
            return 0.0;
          if (current_opp_idx == current_board.num_snakes) {
            resolve_deaths(current_board);
            build_bitboards(current_board);
            return minimax(current_board, depth - 2, a, bt, true, ss,
                           max_depth);
          }
          if (current_opp_idx == current_board.my_index ||
              !current_board.snakes[current_opp_idx].alive) {
            return self(self, current_board, current_opp_idx + 1, a, bt);
          }
          double opp_best = 100000.0;
          for (int k = 0; k < num_opp_moves[current_opp_idx]; k++) {
            Board next_b = current_board;
            apply_move(next_b, current_opp_idx, opp_moves[current_opp_idx][k]);
            double v = self(self, next_b, current_opp_idx + 1, a, bt);
            if (v < opp_best)
              opp_best = v;
            if (opp_best < bt)
              bt = opp_best;
            if (a >= bt)
              break;
          }
          return opp_best;
        };

        val = eval_lmr(eval_lmr, copy, 0, alpha, beta);

        // If reduced search suggests this move is interesting, re-search fully
        if (!ss.timed_out && val > alpha) {
          val = eval_opp_combinations(eval_opp_combinations, copy, 0, alpha,
                                      beta);
        }
      } else {
        val =
            eval_opp_combinations(eval_opp_combinations, copy, 0, alpha, beta);
      }

      if (val > best)
        best = val;
      if (best > alpha) {
        alpha = best;
        // Store killer move
        if (cur_depth_idx >= 0 && cur_depth_idx < MAX_DEPTH) {
          if (ss.killer_moves[cur_depth_idx][0] != moves[m].dir) {
            ss.killer_moves[cur_depth_idx][1] =
                ss.killer_moves[cur_depth_idx][0];
            ss.killer_moves[cur_depth_idx][0] = moves[m].dir;
          }
        }
      }
      if (alpha >= beta)
        break;
    }
    return best;
  }

  // Should not reach here in current architecture (opponents handled inline)
  return evaluate(b);
}

// ============================================================
// Find Best Move (iterative deepening)
// Repeatedly deepens the Minimax search tree by 1 level until the timeout is
// reached. Iterative deepening is safer than fixed-depth search when time is
// strictly limited.
// ============================================================

inline int find_best_move(Board &b, int timeout_ms) {
  auto start_time = std::chrono::steady_clock::now();
  auto deadline = start_time + std::chrono::milliseconds(timeout_ms);

  build_bitboards(b);

  // Fallback: flood fill best
  int best_move = flood_fill_best_move(b, b.my_index);

  const Snake &me = b.snakes[b.my_index];
  if (!me.alive)
    return best_move;

  // URGENT FOOD MODE: when health < 15, use A* to find the closest reachable
  // food and head straight for it. This overrides the normal minimax search
  // because at low health we can't afford to spend turns on space optimization
  // — we need to eat or we die.
  if (me.health < 15 && b.num_food > 0) {
    int food_dir = astar_closest_food(b, b.my_index);
    if (food_dir >= 0) {
      // Verify the A* direction doesn't walk us into immediate death
      // (A* already avoids walls, but double-check bounds)
      int nx = me.body_x[0] + DX[food_dir];
      int ny = me.body_y[0] + DY[food_dir];
      if (in_bounds(nx, ny)) {
        return food_dir;
      }
    }
    // If A* found no path to any food, fall through to normal minimax
    // (maybe we can survive by space-maximizing until food spawns)
  }

  int hx = me.body_x[0], hy = me.body_y[0];
  // Use head-danger walls so we don't step next to larger/equal opponent heads
  Bitboard danger_walls = build_walls_with_head_danger(b);
  Bitboard safe_walls = build_walls(b);

  // Gather legal moves using danger-aware walls first
  struct MoveScore {
    int dir;
    int space;
    int center_dist;
  };
  MoveScore moves[4];
  int num_moves = 0;

  for (int d = 0; d < 4; d++) {
    int nx = hx + DX[d];
    int ny = hy + DY[d];
    if (!in_bounds(nx, ny))
      continue;
    int idx = coord_to_idx(nx, ny);
    if (danger_walls.get(idx))
      continue;

    Bitboard start_bb;
    start_bb.set(idx);
    // Use normal walls for flood fill (head danger zones aren't real walls,
    // just places we don't want to step — space behind them is still reachable)
    int space = flood_fill(start_bb, safe_walls);
    int cdist = abs(nx - BOARD_W / 2) + abs(ny - BOARD_H / 2);
    moves[num_moves] = {d, space, cdist};
    num_moves++;
  }

  // If all moves are blocked by head danger zones, fall back to normal walls
  // (better to risk a head-to-head than to have no moves at all)
  if (num_moves == 0) {
    for (int d = 0; d < 4; d++) {
      int nx = hx + DX[d];
      int ny = hy + DY[d];
      if (!in_bounds(nx, ny))
        continue;
      int idx = coord_to_idx(nx, ny);
      if (safe_walls.get(idx))
        continue;

      Bitboard start_bb;
      start_bb.set(idx);
      int space = flood_fill(start_bb, safe_walls);
      int cdist = abs(nx - BOARD_W / 2) + abs(ny - BOARD_H / 2);
      moves[num_moves] = {d, space, cdist};
      num_moves++;
    }
  }

  if (num_moves == 0)
    return best_move;

  // Sort moves descending by space, then ascending by center distance
  for (int i = 0; i < num_moves - 1; i++) {
    for (int j = i + 1; j < num_moves; j++) {
      if (moves[j].space > moves[i].space ||
          (moves[j].space == moves[i].space &&
           moves[j].center_dist < moves[i].center_dist)) {
        std::swap(moves[i], moves[j]);
      }
    }
  }

  // Iterative deepening with PV-move ordering and aspiration windows
  int pv_move = -1;        // Best move from previous iteration
  double prev_score = 0.0; // Score from previous iteration

  for (int depth = 1; depth <= MAX_DEPTH; depth++) {
    if (std::chrono::steady_clock::now() >= deadline)
      break;

    SearchState ss;
    ss.deadline = deadline;
    ss.timed_out = false;
    ss.nodes_searched = 0;
    std::memset(ss.killer_moves, -1, sizeof(ss.killer_moves));

    // PV-move ordering: if we have a best move from the previous iteration,
    // try it first. This dramatically improves alpha-beta cutoffs.
    if (pv_move >= 0) {
      for (int m = 1; m < num_moves; m++) {
        if (moves[m].dir == pv_move) {
          std::swap(moves[0], moves[m]);
          break;
        }
      }
    }

    int depth_best_move = moves[0].dir;
    double depth_best_score = -100000.0;

    // Aspiration window: start with a narrow window around previous score.
    // If the search fails outside the window, re-search with full window.
    double asp_alpha = -100000.0;
    double asp_beta = 100000.0;
    if (depth >= 3 && prev_score > -9000.0 && prev_score < 9000.0) {
      asp_alpha = prev_score - 50.0;
      asp_beta = prev_score + 50.0;
    }

    bool needs_research = false;

    int saved_opp_moves[4][MAX_SNAKES][4];
    int saved_num_opp_moves[4][MAX_SNAKES];

    for (int m = 0; m < num_moves; m++) {
      Board copy = b;
      apply_move(copy, b.my_index, moves[m].dir);

      // Reduce opponent branching at deeper depths
      int max_opp_keep = (depth <= 2) ? 1 : 2;

      int(&opp_moves_arr)[MAX_SNAKES][4] = saved_opp_moves[m];
      int(&num_opp_moves)[MAX_SNAKES] = saved_num_opp_moves[m];
      Bitboard copy_walls = build_walls(copy);

      for (int i = 0; i < copy.num_snakes; i++) {
        num_opp_moves[i] = 0;
        if (i == copy.my_index || !copy.snakes[i].alive)
          continue;

        if (depth <= 3) {
          // Fast move gen at deep nodes
          int fast_moves[4];
          int n = get_opp_moves_fast(copy, i, copy_walls, fast_moves);
          int keep = (n > max_opp_keep) ? max_opp_keep : n;
          for (int k = 0; k < keep; k++)
            opp_moves_arr[i][k] = fast_moves[k];
          num_opp_moves[i] = keep;
        } else {
          // Full flood-fill ordering at shallow depths
          int hx_opp = copy.snakes[i].body_x[0];
          int hy_opp = copy.snakes[i].body_y[0];

          struct MS {
            int dir, space;
          };
          MS o_moves[4];
          int o_num = 0;
          for (int d = 0; d < 4; d++) {
            int nx = hx_opp + DX[d];
            int ny = hy_opp + DY[d];
            if (!in_bounds(nx, ny))
              continue;
            int idx = coord_to_idx(nx, ny);
            if (copy_walls.get(idx))
              continue;

            Bitboard start;
            start.set(idx);
            o_moves[o_num] = {d, flood_fill(start, copy_walls)};
            o_num++;
          }

          for (int x = 0; x < o_num - 1; x++) {
            for (int y = x + 1; y < o_num; y++) {
              if (o_moves[y].space > o_moves[x].space)
                std::swap(o_moves[x], o_moves[y]);
            }
          }

          int keep = (o_num > max_opp_keep) ? max_opp_keep : o_num;
          if (keep == 0) {
            opp_moves_arr[i][0] = 0;
            num_opp_moves[i] = 1;
          } else {
            for (int m2 = 0; m2 < keep; m2++)
              opp_moves_arr[i][m2] = o_moves[m2].dir;
            num_opp_moves[i] = keep;
          }
        }
      }

      auto eval_opp_combinations = [&](auto &self, Board current_board,
                                       int current_opp_idx, double a,
                                       double bt) -> double {
        if (ss.timed_out)
          return 0.0;
        if (current_opp_idx == current_board.num_snakes) {
          resolve_deaths(current_board);
          build_bitboards(current_board);
          return minimax(current_board, depth - 1, a, bt, true, ss, depth);
        }
        if (current_opp_idx == current_board.my_index ||
            !current_board.snakes[current_opp_idx].alive) {
          return self(self, current_board, current_opp_idx + 1, a, bt);
        }
        double opp_best = 100000.0;
        for (int k = 0; k < num_opp_moves[current_opp_idx]; k++) {
          Board next_b = current_board;
          apply_move(next_b, current_opp_idx,
                     opp_moves_arr[current_opp_idx][k]);
          double val = self(self, next_b, current_opp_idx + 1, a, bt);
          if (val < opp_best)
            opp_best = val;
          if (opp_best < bt)
            bt = opp_best;
          if (a >= bt)
            break;
        }
        return opp_best;
      };

      double val = eval_opp_combinations(eval_opp_combinations, copy, 0,
                                         asp_alpha, asp_beta);

      if (ss.timed_out)
        break;

      if (val > depth_best_score) {
        depth_best_score = val;
        depth_best_move = moves[m].dir;
      }

      // Update aspiration alpha for next root move
      if (val > asp_alpha)
        asp_alpha = val;
    }

    if (!ss.timed_out) {
      // Check if score fell outside aspiration window — if so, re-search
      // with full window (but only if we have time)
      if (depth >= 3 && (depth_best_score <= prev_score - 50.0 ||
                         depth_best_score >= prev_score + 50.0)) {
        // Score outside window — the result might be inaccurate.
        // Re-search with full window if time permits.
        if (std::chrono::steady_clock::now() < deadline) {
          SearchState ss2;
          ss2.deadline = deadline;
          ss2.timed_out = false;
          ss2.nodes_searched = 0;
          std::memset(ss2.killer_moves, -1, sizeof(ss2.killer_moves));

          int re_best_move = moves[0].dir;
          double re_best_score = -100000.0;
          double re_alpha = -100000.0;

          for (int m = 0; m < num_moves; m++) {
            Board copy = b;
            apply_move(copy, b.my_index, moves[m].dir);

            // Reuse same opponent move setup (already computed for this depth)
            auto eval2 = [&](auto &self, Board current_board,
                             int current_opp_idx, double a,
                             double bt) -> double {
              if (ss2.timed_out)
                return 0.0;
              if (current_opp_idx == current_board.num_snakes) {
                resolve_deaths(current_board);
                build_bitboards(current_board);
                return minimax(current_board, depth - 1, a, bt, true, ss2,
                               depth);
              }
              if (current_opp_idx == current_board.my_index ||
                  !current_board.snakes[current_opp_idx].alive)
                return self(self, current_board, current_opp_idx + 1, a, bt);
              double opp_best = 100000.0;
              // Re-use full branching for re-search to get an accurate score!
              // The naive fast-move fallback overrides the failure mechanism
              // and ruins ordering.
              for (int k = 0; k < saved_num_opp_moves[m][current_opp_idx];
                   k++) {
                Board next_b = current_board;
                apply_move(next_b, current_opp_idx,
                           saved_opp_moves[m][current_opp_idx][k]);
                double val = self(self, next_b, current_opp_idx + 1, a, bt);
                if (val < opp_best)
                  opp_best = val;
                if (opp_best < bt)
                  bt = opp_best;
                if (a >= bt)
                  break;
              }
              return opp_best;
            };

            double val = eval2(eval2, copy, 0, re_alpha, 100000.0);

            if (ss2.timed_out)
              break;

            if (val > re_best_score) {
              re_best_score = val;
              re_best_move = moves[m].dir;
            }
            if (val > re_alpha)
              re_alpha = val;
          }

          if (!ss2.timed_out) {
            depth_best_move = re_best_move;
            depth_best_score = re_best_score;
          }
        }
      }

      best_move = depth_best_move;
      pv_move = depth_best_move;
      prev_score = depth_best_score;
    }
  }

  return best_move;
}

// ============================================================
// C API (called from Python via ctypes)
// ============================================================

struct CSnake {
  int body_x[MAX_BODY];
  int body_y[MAX_BODY];
  int length;
  int health;
  int alive;         // 1 = alive, 0 = dead
  int ate_last_turn; // 1 = ate, 0 = didn't
};

struct CBoard {
  CSnake snakes[MAX_SNAKES];
  int num_snakes;
  int food_x[MAX_FOOD];
  int food_y[MAX_FOOD];
  int num_food;
  int my_index;
  int timeout_ms;
};

inline Board cboard_to_board(const CBoard *cb) {
  Board b;
  b.num_snakes = cb->num_snakes;
  b.num_food = cb->num_food;
  b.my_index = cb->my_index;

  for (int i = 0; i < cb->num_snakes; i++) {
    b.snakes[i].length = cb->snakes[i].length;
    b.snakes[i].health = cb->snakes[i].health;
    b.snakes[i].alive = cb->snakes[i].alive != 0;
    b.snakes[i].ate_last_turn = cb->snakes[i].ate_last_turn != 0;
    for (int j = 0; j < cb->snakes[i].length; j++) {
      b.snakes[i].body_x[j] = cb->snakes[i].body_x[j];
      b.snakes[i].body_y[j] = cb->snakes[i].body_y[j];
    }
  }

  for (int f = 0; f < cb->num_food; f++) {
    b.food_x[f] = cb->food_x[f];
    b.food_y[f] = cb->food_y[f];
  }

  return b;
}

extern "C" {
int get_best_move(const CBoard *cb) {
  Board b = cboard_to_board(cb);
  return find_best_move(b, cb->timeout_ms);
}
}
