"""
AI Map Reader & Navigation Decision Engine for BUPI Sonar Vision.
Provides 5-Sector Clearance Breakdown, 2D A* Pathfinding, Steering Commands,
and 20x20 ASCII Semantic Matrix.
"""

import math
import heapq
from typing import Dict, List, Optional, Tuple, Any
import numpy as np

from .config import CONFIG, SonarGridConfig
from .depth_profiler import DepthPortal, VerticalFeature


class AIMapDecisionReader:
    def __init__(self, cfg: SonarGridConfig = CONFIG):
        self.cfg = cfg
        self.grid_w = cfg.GRID_WIDTH
        self.grid_h = cfg.GRID_HEIGHT
        self.res = cfg.RESOLUTION_CM
        self.ox = cfg.ORIGIN_X
        self.oy = cfg.ORIGIN_Y

    def analyze_5_sectors(
        self,
        pass1_buffer: Dict[int, float],
        portals: List[DepthPortal],
        vertical_features: List[VerticalFeature]
    ) -> Dict[str, Dict[str, Any]]:
        """
        Calculates clearance distance and tactical status across 5 sectors:
        Right (0-35°), Front-Right (35-65°), Center (65-115°), Front-Left (115-145°), Left (145-180°).
        """
        sector_defs = [
            ("Right", 0.0, 35.0),
            ("Front-Right", 35.0, 65.0),
            ("Center", 65.0, 115.0),
            ("Front-Left", 115.0, 145.0),
            ("Left", 145.0, 180.0)
        ]

        result = {}
        portal_angles = [p.angle_deg for p in portals]

        for name, min_a, max_a in sector_defs:
            # Collect recorded distances in this sector
            sector_dists = [d for a, d in pass1_buffer.items() if min_a <= a <= max_a and d < 390.0]

            # Check if any doorway portal exists in this sector
            has_portal = any(min_a <= pa <= max_a for pa in portal_angles)

            # Check if any low step exists in this sector
            has_low_step = any(
                min_a <= vf.angle_deg <= max_a and vf.feature_type == "LOW_OBSTACLE"
                for vf in vertical_features
            )

            if sector_dists:
                min_dist = min(sector_dists)
                avg_dist = sum(sector_dists) / len(sector_dists)
            else:
                # If no scan yet, treat as open unknown (> 200cm)
                min_dist = 400.0
                avg_dist = 400.0

            # Determine tactical classification
            if has_portal:
                status = "DOORWAY_PORTAL"
            elif has_low_step:
                status = "LOW_STEP"
            elif min_dist <= 25.0:
                status = "BLOCKED_WALL"
            elif min_dist >= 120.0:
                status = "CLEAR_CORRIDOR"
            else:
                status = "RESTRICTED_WALL"

            result[name] = {
                "min_distance_cm": round(min_dist, 1),
                "avg_distance_cm": round(avg_dist, 1),
                "status": status,
                "has_portal": has_portal,
                "has_low_step": has_low_step
            }

        return result

    def compute_astar_path(
        self,
        prob_grid: np.ndarray,
        portals: List[DepthPortal],
        sectors: Dict[str, Dict[str, Any]]
    ) -> Tuple[List[Dict[str, float]], str, float]:
        """
        Computes 2D A* path from robot origin (60, 60) toward best open corridor or portal.
        Returns: (waypoints_list_cm, steering_command, path_heading_deg)
        """
        start = (self.ox, self.oy)

        # 1. Select Target Goal
        target_cell = None
        if portals:
            # Target the nearest doorway portal
            best_portal = min(portals, key=lambda p: math.hypot(p.x_cm, p.y_cm))
            tc = int(round(self.ox + (best_portal.x_cm / self.res)))
            tr = int(round(self.oy - (best_portal.y_cm / self.res)))
            target_cell = (max(0, min(self.grid_w - 1, tc)), max(0, min(self.grid_h - 1, tr)))
        else:
            # Target best open corridor sector
            best_sector = "Center"
            max_clearance = -1.0
            for sname in ["Center", "Front-Left", "Front-Right", "Left", "Right"]:
                c = sectors.get(sname, {}).get("min_distance_cm", 0.0)
                if c > max_clearance:
                    max_clearance = c
                    best_sector = sname

            # Map sector to target angle
            target_angles = {
                "Center": 90.0,
                "Front-Left": 130.0,
                "Front-Right": 50.0,
                "Left": 165.0,
                "Right": 15.0
            }
            tgt_ang = target_angles.get(best_sector, 90.0)
            tgt_dist = min(max_clearance * 0.7, 180.0)
            rad = math.radians(tgt_ang)
            tc = int(round(self.ox + (tgt_dist * math.cos(rad) / self.res)))
            tr = int(round(self.oy - (tgt_dist * math.sin(rad) / self.res)))
            target_cell = (max(0, min(self.grid_w - 1, tc)), max(0, min(self.grid_h - 1, tr)))

        # 2. A* Search
        path_cells = self._run_astar(start, target_cell, prob_grid)

        # Convert path cells to world coordinates (cm)
        waypoints = []
        for c, r in path_cells:
            wx = (c - self.ox) * self.res
            wy = (self.oy - r) * self.res
            waypoints.append({"x": round(wx, 1), "y": round(wy, 1)})

        # 3. Derive Immediate Steering Directive
        center_clearance = sectors.get("Center", {}).get("min_distance_cm", 400.0)
        if center_clearance <= 20.0:
            command = "STOP (CRITICAL COLLISION BUFFER < 20cm)"
            heading_deg = 90.0
        elif len(waypoints) >= 4:
            # Look ahead ~40cm along waypoints
            look_wp = waypoints[min(5, len(waypoints) - 1)]
            angle = math.degrees(math.atan2(look_wp["y"], look_wp["x"]))
            if angle < 0: angle += 360.0
            diff = angle - 90.0
            heading_deg = round(angle, 1)

            if abs(diff) <= 12.0:
                command = f"FORWARD (SPEED 60%, HEADING {angle:.0f}°)"
            elif diff > 12.0:
                command = f"STEER_LEFT (+{diff:.0f}°, SPEED 45%)"
            else:
                command = f"STEER_RIGHT ({diff:.0f}°, SPEED 45%)"
        else:
            command = "FORWARD (SPEED 50%)"
            heading_deg = 90.0

        return waypoints, command, heading_deg

    def _run_astar(self, start: Tuple[int, int], goal: Tuple[int, int], prob_grid: np.ndarray) -> List[Tuple[int, int]]:
        """Standard 8-connected grid A* search."""
        sx, sy = start
        gx, gy = goal

        def heuristic(a, b):
            return math.hypot(a[0] - b[0], a[1] - b[1])

        open_set = []
        heapq.heappush(open_set, (0.0, start))
        came_from = {}
        g_score = {start: 0.0}

        # Obstacle threshold
        def is_blocked(col, row):
            if not (0 <= col < self.grid_w and 0 <= row < self.grid_h):
                return True
            return prob_grid[row, col] >= self.cfg.PROB_OCC_THRESH

        neighbors_offsets = [
            (0, 1), (0, -1), (1, 0), (-1, 0),
            (1, 1), (1, -1), (-1, 1), (-1, -1)
        ]

        iterations = 0
        while open_set and iterations < 1200:
            iterations += 1
            _, current = heapq.heappop(open_set)

            if current == goal or heuristic(current, goal) <= 2.0:
                # Reconstruct path
                path = [current]
                while current in came_from:
                    current = came_from[current]
                    path.append(current)
                path.reverse()
                return path

            cx, cy = current
            for dx, dy in neighbors_offsets:
                nx, ny = cx + dx, cy + dy
                neighbor = (nx, ny)

                if is_blocked(nx, ny):
                    continue

                cost = math.hypot(dx, dy)
                tentative_g = g_score[current] + cost

                if tentative_g < g_score.get(neighbor, float('inf')):
                    came_from[neighbor] = current
                    g_score[neighbor] = tentative_g
                    f_score = tentative_g + heuristic(neighbor, goal)
                    heapq.heappush(open_set, (f_score, neighbor))

        # Fallback straight line if path blocked
        return [start, goal]

    def generate_ascii_20x20(
        self,
        prob_grid: np.ndarray,
        portals: List[DepthPortal],
        vertical_features: List[VerticalFeature]
    ) -> str:
        """
        Downsamples 120x120 grid into a 20x20 character matrix:
        '#' = Wall, '.' = Free Floor, '^' = Low Step, 'O' = Portal, 'B' = Robot Origin
        """
        down_size = 20
        block_size = self.grid_w // down_size  # 6 cells per block (24cm x 24cm)
        ascii_grid = [[" " for _ in range(down_size)] for _ in range(down_size)]

        # 1. Fill basic floor and walls
        for r_idx in range(down_size):
            for c_idx in range(down_size):
                sub_r = r_idx * block_size
                sub_c = c_idx * block_size
                block = prob_grid[sub_r:sub_r + block_size, sub_c:sub_c + block_size]

                max_p = np.max(block)
                min_p = np.min(block)

                if max_p >= self.cfg.PROB_OCC_THRESH:
                    ascii_grid[r_idx][c_idx] = "#"
                elif min_p <= self.cfg.PROB_FREE_THRESH:
                    ascii_grid[r_idx][c_idx] = "."
                else:
                    ascii_grid[r_idx][c_idx] = " "

        # 2. Mark Low Steps ('^')
        for vf in vertical_features:
            if vf.feature_type == "LOW_OBSTACLE":
                c = int(round(self.ox + (vf.x_cm / self.res))) // block_size
                r = int(round(self.oy - (vf.y_cm / self.res))) // block_size
                if 0 <= c < down_size and 0 <= r < down_size:
                    ascii_grid[r][c] = "^"

        # 3. Mark Doorway Portals ('O')
        for p in portals:
            c = int(round(self.ox + (p.x_cm / self.res))) // block_size
            r = int(round(self.oy - (p.y_cm / self.res))) // block_size
            if 0 <= c < down_size and 0 <= r < down_size:
                ascii_grid[r][c] = "O"

        # 4. Mark Robot Origin ('B')
        rc = self.ox // block_size
        rr = self.oy // block_size
        if 0 <= rc < down_size and 0 <= rr < down_size:
            ascii_grid[rr][rc] = "B"

        # Format into monospace string with border
        lines = ["+--------------------+"]
        for row in ascii_grid:
            lines.append("|" + "".join(row) + "|")
        lines.append("+--------------------+")
        return "\n".join(lines)

