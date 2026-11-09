"""
A* 2.5D Pathfinding, 3D Sector Analysis, and ASCII Semantic Matrix Generator.
"""

import math
import heapq
from typing import Dict, List, Tuple, Any, Callable
import numpy as np
import cv2


def compute_astar_2_5d(
    prob_grid: np.ndarray,
    semantic_matrix: np.ndarray,
    portals: List[Dict[str, Any]],
    ox: int,
    oy: int,
    res: float,
    occ_thresh: float,
    dil_kernel: np.ndarray,
    is_in_bounds: Callable[[int, int], bool],
    world_to_grid: Callable[[float, float], Tuple[int, int]],
    grid_to_world: Callable[[int, int], Tuple[float, float]]
) -> Tuple[List[Dict[str, float]], str, float]:
    """
    A* 2.5D Pathfinding: Traversable through OPEN_CORRIDOR (cost 1.0) and
    LOW_STEP_RUBBLE (cost 4.5), completely avoiding TALL_SOLID_WALL (infinity).
    """
    h, w = prob_grid.shape
    wall_mask = (prob_grid >= occ_thresh).astype(np.uint8) * 255
    dilated_mask = cv2.dilate(wall_mask, dil_kernel, iterations=1)

    best_goal = None
    if portals:
        p = portals[-1]
        gc, gr = world_to_grid(p["x_cm"], p["y_cm"])
        if is_in_bounds(gc, gr) and dilated_mask[gr, gc] == 0:
            best_goal = (gc, gr)

    if not best_goal:
        for r in range(10, oy):
            for c in range(ox - 30, ox + 30):
                if is_in_bounds(c, r) and dilated_mask[r, c] == 0 and prob_grid[r, c] < 0.35:
                    best_goal = (c, r)
                    break
            if best_goal:
                break

    if not best_goal:
        return [], "HALT: NO SAFE TRAVERSABLE PATH", 90.0

    start = (ox, oy)
    open_set = [(0.0, start[0], start[1])]
    came_from = {}
    g_score = {start: 0.0}

    def heuristic(a, b):
        return math.hypot(a[0] - b[0], a[1] - b[1])

    found = False
    while open_set:
        _, cx, cy = heapq.heappop(open_set)
        if (cx, cy) == best_goal or math.hypot(cx - best_goal[0], cy - best_goal[1]) <= 2.0:
            best_goal = (cx, cy)
            found = True
            break

        for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (1, -1), (-1, 1), (1, 1)]:
            nx, ny = cx + dx, cy + dy
            if not is_in_bounds(nx, ny) or dilated_mask[ny, nx] > 0:
                continue

            cell_cost = 1.0
            if semantic_matrix[ny, nx] == 2:  # LOW_STEP_RUBBLE
                cell_cost = 4.5

            step_cost = math.hypot(dx, dy) * cell_cost
            tentative_g = g_score[(cx, cy)] + step_cost

            if tentative_g < g_score.get((nx, ny), float('inf')):
                came_from[(nx, ny)] = (cx, cy)
                g_score[(nx, ny)] = tentative_g
                f = tentative_g + heuristic((nx, ny), best_goal)
                heapq.heappush(open_set, (f, nx, ny))

    if not found and best_goal not in came_from:
        return [], "EXPLORE: NO DIRECT A* FRONTIER", 90.0

    path = []
    curr = best_goal
    while curr in came_from:
        wx, wy = grid_to_world(curr[0], curr[1])
        path.append({"x_cm": round(wx, 1), "y_cm": round(wy, 1)})
        curr = came_from[curr]
    path.reverse()

    if len(path) > 3:
        target_pt = path[min(5, len(path) - 1)]
        dx = target_pt["x_cm"]
        dy = target_pt["y_cm"]
        heading = (math.degrees(math.atan2(dy, dx)) + 360) % 360
        angle_err = heading - 90.0
        if abs(angle_err) <= 8.0:
            cmd = "MOVE_FORWARD (LOCKED ON CORRIDOR)"
        elif angle_err > 8.0:
            cmd = f"STEER_LEFT +{int(round(angle_err))}°"
        else:
            cmd = f"STEER_RIGHT {int(round(angle_err))}°"
    else:
        cmd = "NAVIGATE: AWAITING STEER ANGLE"
        heading = 90.0

    return path, cmd, round(heading, 1)


def analyze_5_sectors_3d(
    d1_buffer: Dict[int, float],
    class_buffer: Dict[int, str],
    portals: List[Dict[str, Any]]
) -> Dict[str, Dict[str, Any]]:
    """Evaluates 3D sector clearance across Left, Front-Left, Center, Front-Right, Right."""
    sector_bounds = [
        ("Right", 0.0, 35.0),
        ("Front-Right", 35.0, 65.0),
        ("Center", 65.0, 115.0),
        ("Front-Left", 115.0, 145.0),
        ("Left", 145.0, 180.0)
    ]
    res = {}
    for name, a_min, a_max in sector_bounds:
        dists = [d for a, d in d1_buffer.items() if a_min <= a <= a_max and d < 390.0]
        classes = [c for a, c in class_buffer.items() if a_min <= a <= a_max]

        has_portal = any(a_min <= p["angle_deg"] <= a_max for p in portals)
        has_step = "LOW_STEP_RUBBLE" in classes
        has_overhang = "OVERHANG_HAZARD" in classes
        has_wall = "TALL_SOLID_WALL" in classes

        min_d = min(dists) if dists else 400.0
        avg_d = (sum(dists) / len(dists)) if dists else 400.0

        if has_portal:
            status, trav_pct = "PORTAL_ENTRANCE", 95
        elif has_step:
            status, trav_pct = "LOW_STEP_CLIMBABLE", 60
        elif has_overhang:
            status, trav_pct = "OVERHANG_HAZARD", 20
        elif has_wall or min_d <= 20.0:
            status, trav_pct = "BLOCKED_WALL", 0
        elif min_d >= 120.0:
            status, trav_pct = "CLEAR_CORRIDOR", 100
        else:
            status, trav_pct = "RESTRICTED", 40

        res[name] = {
            "min_distance_cm": round(min_d, 1),
            "avg_distance_cm": round(avg_d, 1),
            "status": status,
            "traversability_pct": trav_pct
        }
    return res


def generate_ascii_20x20_3d(
    prob_grid: np.ndarray,
    semantic_matrix: np.ndarray,
    gh: int,
    gw: int,
    occ_thresh: float,
    free_thresh: float
) -> str:
    """Generates 20x20 ASCII 3D Semantic Map (#=Wall, .=Floor, ^=Step, ~=Overhang, O=Portal, B=Bot)."""
    matrix = []
    step_r = gh // 20
    step_c = gw // 20

    for br in range(20):
        row_chars = []
        for bc in range(20):
            r = br * step_r
            c = bc * step_c
            if br == 10 and bc == 10:
                row_chars.append("B")
                continue
            sem = semantic_matrix[r, c]
            p = prob_grid[r, c]
            if sem == 5:
                row_chars.append("O")
            elif sem == 4:
                row_chars.append("~")
            elif sem == 2:
                row_chars.append("^")
            elif sem == 3 or p >= occ_thresh:
                row_chars.append("#")
            elif p <= free_thresh:
                row_chars.append(".")
            else:
                row_chars.append(" ")
        matrix.append("".join(row_chars))

    box_top = "+" + ("-" * 20) + "+"
    return box_top + "\n" + "\n".join("|" + r + "|" for r in matrix) + "\n" + box_top

