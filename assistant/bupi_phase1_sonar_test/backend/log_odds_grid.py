"""
Log-Odds Bayesian Occupancy Grid with Bresenham Line & Acoustic Cone Integration.
"""

import math
import numpy as np
from typing import List, Tuple
from .config import CONFIG, SonarGridConfig


class LogOddsOccupancyGrid:
    def __init__(self, cfg: SonarGridConfig = CONFIG):
        self.cfg = cfg
        self.width = cfg.GRID_WIDTH
        self.height = cfg.GRID_HEIGHT
        self.res = cfg.RESOLUTION_CM
        self.origin_x = cfg.ORIGIN_X
        self.origin_y = cfg.ORIGIN_Y

        # Persistent log-odds grid initialized to L_0 (0.0 -> P=0.5 unknown)
        self.grid = np.full((self.height, self.width), cfg.L_0, dtype=np.float32)

    def world_to_grid(self, x_cm: float, y_cm: float) -> Tuple[int, int]:
        """Convert world coordinates (cm) to grid (col, row). Origin is at bottom-center/middle."""
        col = int(round(self.origin_x + (x_cm / self.res)))
        # Invert Y so positive Y (forward) points upward in image space (smaller row index)
        row = int(round(self.origin_y - (y_cm / self.res)))
        return col, row

    def grid_to_world(self, col: int, row: int) -> Tuple[float, float]:
        """Convert grid (col, row) to world coordinates (cm)."""
        x_cm = (col - self.origin_x) * self.res
        y_cm = (self.origin_y - row) * self.res
        return x_cm, y_cm

    def is_in_bounds(self, col: int, row: int) -> bool:
        return 0 <= col < self.width and 0 <= row < self.height

    def _bresenham_line(self, x0: int, y0: int, x1: int, y1: int) -> List[Tuple[int, int]]:
        """Standard 2D Bresenham integer line algorithm."""
        points: List[Tuple[int, int]] = []
        dx = abs(x1 - x0)
        dy = abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx - dy

        x, y = x0, y0
        while True:
            points.append((x, y))
            if x == x1 and y == y1:
                break
            e2 = 2 * err
            if e2 > -dy:
                err -= dy
                x += sx
            if e2 < dx:
                err += dx
                y += sy
        return points

    def integrate_ping(self, angle_deg: float, distance_cm: float, is_valid: bool = True, weight_scale: float = 1.0):
        """
        Integrate a single ultrasonic ping into the log-odds grid using a 15-degree Gaussian cone.
        Clears free space along the beam and accumulates hit probability along the arc.
        """
        if not is_valid or distance_cm <= 0.0 or distance_cm >= (self.cfg.MAX_RANGE_CM - 2.0):
            # Do not plot phantom readings or corrupt map on hardware timeouts / missed echoes
            return
        # Clamp distance within sensor bounds
        eff_dist = min(max(distance_cm, self.cfg.MIN_RANGE_CM), self.cfg.MAX_RANGE_CM)
        cone_half = self.cfg.CONE_HALF_ANGLE_DEG

        # Sub-rays across the 15-degree acoustic cone (-7.5 deg to +7.5 deg)
        angular_offsets = [-7.5, -4.5, -1.5, 0.0, 1.5, 4.5, 7.5]

        # Cells updated during this ping to avoid duplicate updates from overlapping sub-rays
        free_cells_updated = set()
        hit_cells_updated = set()

        for offset in angular_offsets:
            sub_angle = angle_deg + offset
            rad = math.radians(sub_angle)

            # Gaussian weight across the cone: peak at center, tapering at borders
            # sigma = 4.0 deg
            gauss_w = math.exp(-0.5 * ((offset / 4.0) ** 2)) * weight_scale

            # Endpoint in world coordinates (cm)
            end_x = eff_dist * math.cos(rad)
            end_y = eff_dist * math.sin(rad)

            c_end, r_end = self.world_to_grid(end_x, end_y)
            c_start, r_start = self.origin_x, self.origin_y

            # Ray-cast from origin to endpoint
            line_cells = self._bresenham_line(c_start, r_start, c_end, r_end)
            arc_thickness_cm = 8.0  # obstacle arc thickness in cm

            for c, r in line_cells:
                if not self.is_in_bounds(c, r):
                    continue

                # Cell distance from origin in cm
                cell_x, cell_y = self.grid_to_world(c, r)
                cell_dist = math.hypot(cell_x, cell_y)

                if cell_dist < eff_dist - (arc_thickness_cm / 2.0):
                    # Free-space region along the beam cone
                    if (c, r) not in free_cells_updated:
                        self.grid[r, c] += self.cfg.L_FREE * gauss_w * 0.6
                        free_cells_updated.add((c, r))
                elif is_valid and (eff_dist < (self.cfg.MAX_RANGE_CM - 5.0)):
                    # Obstacle hit arc region
                    if abs(cell_dist - eff_dist) <= (arc_thickness_cm / 2.0):
                        if (c, r) not in hit_cells_updated:
                            self.grid[r, c] += self.cfg.L_HIT * gauss_w
                            hit_cells_updated.add((c, r))

        # Clamp all updated cells
        np.clip(self.grid, self.cfg.L_MIN, self.cfg.L_MAX, out=self.grid)

    def get_probability_grid(self) -> np.ndarray:
        """Convert log-odds grid to occupancy probability P in [0.0, 1.0]."""
        # P = 1.0 - 1.0 / (1.0 + exp(L)) = 1 / (1 + exp(-L))
        return 1.0 / (1.0 + np.exp(-self.grid))

    def reset(self):
        """Reset the grid back to unobserved initial state."""
        self.grid.fill(self.cfg.L_0)
