"""
Dual-Ultrasonic + Dual-Servo 2.5D/3D Volumetric Mapping Engine.
Coordinates dense 200x200 polar wedge rasterization (zero radial spoke artifacts),
Hit-Lock Hysteresis Log-Odds updates, morphological gap closing,
cv2.connectedComponentsWithStats object pinpointing, and 3D voxel extraction.
"""

import math
from collections import deque
from typing import Dict, List, Optional, Tuple, Any
import numpy as np
import cv2

from .config import CONFIG, SonarGridConfig
from .astar_2_5d import compute_astar_2_5d, analyze_5_sectors_3d, generate_ascii_20x20_3d
from .sonar_clustering import (
    get_closed_occupancy_mask,
    extract_connected_objects,
    extract_clustered_voxels
)


class Sonar3DEngine:
    def __init__(self, cfg: SonarGridConfig = CONFIG):
        self.cfg = cfg
        self.gw = cfg.GRID_WIDTH       # 200
        self.gh = cfg.GRID_HEIGHT      # 200
        self.ox = cfg.ORIGIN_X         # 100
        self.oy = cfg.ORIGIN_Y         # 100

        self.max_range_cm = float(cfg.MAX_RANGE_CM)  # Default 200.0 cm Room scale
        self.res = self.max_range_cm / 100.0         # 2.0 cm/px at 200 cm

        # Dual Log-Odds Occupancy Grids (Low & High planes) + Verified Floor Mask
        self.grid_low = np.full((self.gh, self.gw), cfg.L_0, dtype=np.float32)
        self.grid_high = np.full((self.gh, self.gw), cfg.L_0, dtype=np.float32)
        self.verified_floor = np.zeros((self.gh, self.gw), dtype=bool)

        # Semantic Classification Matrix (0=Unknown, 1=Floor, 2=Step, 3=Wall, 4=Overhang)
        self.semantic_matrix = np.zeros((self.gh, self.gw), dtype=np.uint8)

        # Point Cloud, Portals, and Angular Buffers
        self.points_3d: List[Dict[str, float]] = []
        self.portals: List[Dict[str, Any]] = []
        self.last_theta: Optional[float] = None
        self.last_d1: Optional[float] = None

        self.d1_buffer: Dict[int, float] = {}
        self.d2_buffer: Dict[int, float] = {}
        self.d1_miss_counts: Dict[int, int] = {}
        self.class_buffer: Dict[int, str] = {}

        # Raw ping ring buffer so MAX RANGE toggles re-render live scans cleanly
        self._ping_replay_buffer: deque = deque(maxlen=400)

        # Dilation structuring element for A* collision buffer
        self.dil_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
        self._rebuild_geometry_caches()

    def _rebuild_geometry_caches(self):
        cols_arr, rows_arr = np.meshgrid(np.arange(self.gw), np.arange(self.gh))
        wx = (cols_arr - self.ox) * self.res
        wy = (self.oy - rows_arr) * self.res
        self.dist_grid_cm = np.hypot(wx, wy).astype(np.float32)
        self.ang_grid_deg = ((np.degrees(np.arctan2(wy, wx)) + 360.0) % 360.0).astype(np.float32)

    def set_max_range(self, max_range_cm: float):
        """Dynamically rescales resolution (e.g. 100cm->1.0, 200cm->2.0, 400cm->4.0) and replays scan."""
        clamped = float(max(50.0, min(400.0, max_range_cm)))
        if abs(clamped - self.max_range_cm) < 0.1:
            return
        saved_pings = list(self._ping_replay_buffer)
        self.max_range_cm = clamped
        self.res = self.max_range_cm / 100.0
        self._rebuild_geometry_caches()
        self._clear_grids_only()
        for p_args in saved_pings:
            self._integrate_dual_ping_internal(*p_args)

    def world_to_grid(self, x_cm: float, y_cm: float) -> Tuple[int, int]:
        return int(round(self.ox + (x_cm / self.res))), int(round(self.oy - (y_cm / self.res)))

    def grid_to_world(self, col: int, row: int) -> Tuple[float, float]:
        return (col - self.ox) * self.res, (self.oy - row) * self.res

    def is_in_bounds(self, c: int, r: int) -> bool:
        return 0 <= c < self.gw and 0 <= r < self.gh

    def _bresenham(self, x0: int, y0: int, x1: int, y1: int) -> List[Tuple[int, int]]:
        pts: List[Tuple[int, int]] = []
        dx, dy = abs(x1 - x0), abs(y1 - y0)
        sx, sy = (1 if x0 < x1 else -1), (1 if y0 < y1 else -1)
        err = dx - dy
        x, y = x0, y0
        while True:
            pts.append((x, y))
            if x == x1 and y == y1:
                break
            e2 = 2 * err
            if e2 > -dy:
                err -= dy
                x += sx
            if e2 < dx:
                err += dx
                y += sy
        return pts

    def integrate_dual_ping(
        self,
        theta_deg: float,
        d1_cm: float,
        d2_cm: float,
        valid1: bool,
        valid2: bool,
        s1_ang: float,
        s2_ang: float,
        pitch_deg: float = 12.0
    ) -> Dict[str, Any]:
        """Stores ping for dynamic range zoom replay and integrates into volumetric grids."""
        self._ping_replay_buffer.append((
            theta_deg, d1_cm, d2_cm, valid1, valid2, s1_ang, s2_ang, pitch_deg
        ))
        return self._integrate_dual_ping_internal(
            theta_deg, d1_cm, d2_cm, valid1, valid2, s1_ang, s2_ang, pitch_deg
        )

    def _integrate_dual_ping_internal(
        self,
        theta_deg: float,
        d1_cm: float,
        d2_cm: float,
        valid1: bool,
        valid2: bool,
        s1_ang: float,
        s2_ang: float,
        pitch_deg: float = 12.0
    ) -> Dict[str, Any]:
        rad = math.radians(theta_deg)
        phi_rad = math.radians(pitch_deg)
        cos_t, sin_t = math.cos(rad), math.sin(rad)
        bin_idx = int(round(theta_deg))

        eff_v1 = bool(valid1 and self.cfg.MIN_RANGE_CM <= d1_cm < 395.0)
        eff_v2 = bool(valid2 and self.cfg.MIN_RANGE_CM <= d2_cm < 395.0)

        # 1. Doorway Portal Detection (Horizontal Discontinuity)
        is_portal = False
        if eff_v1:
            if self.last_theta is not None and self.last_d1 is not None:
                if abs(theta_deg - self.last_theta) <= 15.0 and abs(d1_cm - self.last_d1) >= 40.0:
                    is_portal = True
                    d_near = min(d1_cm, self.last_d1)
                    self.portals.append({
                        "angle_deg": round(theta_deg, 1),
                        "d_near_cm": round(d_near, 1),
                        "d_far_cm": round(max(d1_cm, self.last_d1), 1),
                        "delta_cm": round(d1_cm - self.last_d1, 1),
                        "x_cm": round(d_near * cos_t, 1),
                        "y_cm": round(d_near * sin_t, 1),
                        "type": "DOORWAY_DEPTH_PORTAL",
                        "color": "#e040fb"
                    })
                    if len(self.portals) > 30:
                        self.portals.pop(0)
            self.last_theta = theta_deg
            self.last_d1 = d1_cm
            self.d1_buffer[bin_idx] = d1_cm
            self.d1_miss_counts[bin_idx] = 0
        else:
            # Allow 1 missed reading per angle before clearing cached contour point
            misses = self.d1_miss_counts.get(bin_idx, 0) + 1
            self.d1_miss_counts[bin_idx] = misses
            if misses >= 2:
                self.d1_buffer.pop(bin_idx, None)

        if eff_v2:
            self.d2_buffer[bin_idx] = d2_cm
        else:
            self.d2_buffer.pop(bin_idx, None)

        # 2. Single-Pass Differential Depth Classifier
        f_class, f_color, f_z, sem_code = "OPEN_CORRIDOR", "#00e5ff", 0.0, 1
        if eff_v1 and eff_v2:
            delta_v = d2_cm - d1_cm
            if delta_v > 25.0:
                f_class, f_color, f_z, sem_code = "LOW_STEP_RUBBLE", "#ffb703", 6.0, 2
            elif delta_v < -25.0:
                f_class, f_color, f_z, sem_code = "OVERHANG_HAZARD", "#ff6d00", 18.0, 4
            else:
                f_class, f_color, f_z, sem_code = "TALL_SOLID_WALL", "#ff2a54", 25.0, 3
        elif eff_v1:
            f_class, f_color, f_z, sem_code = "TALL_SOLID_WALL", "#ff2a54", 25.0, 3

        self.class_buffer[bin_idx] = f_class

        # 3. Dense Polar Wedge Rasterization with Hit-Lock Hysteresis
        self._integrate_wedge(self.grid_low, theta_deg, d1_cm, eff_v1, beam_class=sem_code, is_primary=True)
        self._integrate_wedge(self.grid_high, s2_ang, d2_cm, eff_v2, beam_class=sem_code, is_primary=False)

        # Low-step over-look clearance behind rubble
        if f_class == "LOW_STEP_RUBBLE" and eff_v1 and eff_v2 and d2_cm > d1_cm + 20.0:
            c1, r1 = self.world_to_grid(d1_cm * cos_t, d1_cm * sin_t)
            c2, r2 = self.world_to_grid(min(d2_cm, self.max_range_cm) * cos_t, min(d2_cm, self.max_range_cm) * sin_t)
            for bc, br in self._bresenham(c1, r1, c2, r2)[2:]:
                if self.is_in_bounds(bc, br) and self.grid_low[br, bc] <= self.cfg.L_LOCK_THRESH:
                    self.grid_low[br, bc] = max(self.cfg.L_MIN, self.grid_low[br, bc] - 0.30)
                    self.semantic_matrix[br, bc] = 1

        # 4. 3D Point Cloud Buffers (X, Y, Z in cm)
        p1_3d = {"x": round(d1_cm * cos_t, 1), "y": round(d1_cm * sin_t, 1), "z": 4.0, "beam": "low", "class": f_class} if (eff_v1 and d1_cm <= self.max_range_cm) else None
        p2_3d = {"x": round(d2_cm * math.cos(phi_rad) * cos_t, 1), "y": round(d2_cm * math.cos(phi_rad) * sin_t, 1), "z": round(14.0 + (d2_cm * math.sin(phi_rad)), 1), "beam": "high", "class": f_class} if (eff_v2 and d2_cm <= self.max_range_cm) else None

        if p1_3d:
            self.points_3d.append(p1_3d)
        if p2_3d:
            self.points_3d.append(p2_3d)
        if len(self.points_3d) > 300:
            self.points_3d = self.points_3d[-300:]

        return {
            "theta_deg": round(theta_deg, 1), "s1_ang": round(s1_ang, 1), "s2_ang": round(s2_ang, 1),
            "d1_cm": round(d1_cm, 1), "d2_cm": round(d2_cm, 1), "delta_d": round(d2_cm - d1_cm, 1),
            "class": f_class, "color": f_color, "z_cm": f_z, "is_portal": is_portal,
            "p1_3d": p1_3d, "p2_3d": p2_3d
        }

    def _integrate_wedge(
        self,
        target_grid: np.ndarray,
        theta: float,
        dist_cm: float,
        is_valid: bool,
        beam_class: int = 3,
        is_primary: bool = True
    ):
        """
        Dense polar wedge fill (eliminates black spoke streaks) + asymmetric Hit-Lock Hysteresis.
        Timeout readings only fade free-space to 85% max_range and never stamp floor voxels.
        """
        if dist_cm < self.cfg.MIN_RANGE_CM:
            is_valid = False

        if is_valid and dist_cm <= (self.max_range_cm - 1.0):
            eff_dist = dist_cm
            free_dist = max(self.cfg.MIN_RANGE_CM, eff_dist - max(4.0, self.res * 2.0))
            draw_hit = True
        elif is_valid and dist_cm > (self.max_range_cm - 1.0):
            # Valid echo beyond current zoomed range: clear up to viewport boundary cleanly
            eff_dist = self.max_range_cm
            free_dist = self.max_range_cm
            draw_hit = False
        else:
            # Timeout / no echo: cap free-space fade at 85% max_range
            eff_dist = 0.85 * self.max_range_cm
            free_dist = eff_dist
            draw_hit = False

        # Rasterize dense free-space sector wedge across +-8.0 deg (seamless step overlap)
        wedge_mask = np.zeros((self.gh, self.gw), dtype=np.uint8)
        half_span = 8.0
        poly_pts = [(self.ox, self.oy)]
        free_r_px = free_dist / self.res
        for step_a in np.linspace(theta - half_span, theta + half_span, 17):
            rad = math.radians(float(step_a))
            px = int(round(self.ox + free_r_px * math.cos(rad)))
            py = int(round(self.oy - free_r_px * math.sin(rad)))
            poly_pts.append((px, py))

        poly_np = np.array(poly_pts, dtype=np.int32)
        cv2.fillConvexPoly(wedge_mask, poly_np, 255)

        ang_diff = np.abs((self.ang_grid_deg - theta + 180.0) % 360.0 - 180.0)
        in_wedge = (wedge_mask > 0) & (self.dist_grid_cm >= self.cfg.MIN_RANGE_CM)

        # Hit-Lock Hysteresis: protect locked walls (> +1.5) from outer-edge free carving
        unprotected = target_grid <= self.cfg.L_LOCK_THRESH
        direct_clear = (ang_diff <= 2.0) & (self.dist_grid_cm <= (eff_dist - 20.0))
        clear_mask = in_wedge & (unprotected | direct_clear)

        target_grid[clear_mask] = np.maximum(
            self.cfg.L_MIN,
            target_grid[clear_mask] + self.cfg.L_FREE
        )

        if is_primary:
            # Keep semantic layer synced when free cells are cleared below 0.0
            cleared_now = clear_mask & (target_grid < 0.0)
            self.semantic_matrix[cleared_now] = 1
            if is_valid:
                # Verified short-range floor tracking only when a valid echo bounded the ray
                short_floor = cleared_now & (self.dist_grid_cm < min(150.0, free_dist))
                self.verified_floor[short_floor] = True

        # Solid Thick Arc Hit Rendering (thickness=2 across +-7.5 deg around theta)
        if draw_hit:
            r_px = max(2, int(round(dist_cm / self.res)))
            hit_mask = np.zeros((self.gh, self.gw), dtype=np.uint8)
            cv2.ellipse(
                hit_mask,
                (self.ox, self.oy),
                (r_px, r_px),
                0.0,
                -(theta + self.cfg.CONE_HALF_ANGLE_DEG),
                -(theta - self.cfg.CONE_HALF_ANGLE_DEG),
                255,
                thickness=2
            )
            hit_cells = hit_mask > 0
            target_grid[hit_cells] = np.minimum(self.cfg.L_MAX, target_grid[hit_cells] + self.cfg.L_HIT)
            if is_primary:
                self.semantic_matrix[hit_cells] = beam_class
                self.verified_floor[hit_cells] = False

    def get_probability_grid(self) -> np.ndarray:
        odds = np.exp(self.grid_low)
        return odds / (1.0 + odds)

    def get_closed_occupancy(self) -> np.ndarray:
        return get_closed_occupancy_mask(
            self.get_probability_grid(),
            self.cfg.PROB_OCC_THRESH,
            self.cfg.MORPH_CLOSE_SIZE
        )

    def get_contour_scan(self) -> List[Dict[str, Any]]:
        """Sorted valid sonar contour points across 0..180 deg within active range."""
        contour = []
        for ang in sorted(self.d1_buffer.keys()):
            d1 = self.d1_buffer[ang]
            if self.cfg.MIN_RANGE_CM <= d1 <= self.max_range_cm:
                contour.append({
                    "angle_deg": float(ang),
                    "d1_cm": round(d1, 1),
                    "d2_cm": round(self.d2_buffer.get(ang, 400.0), 1),
                    "class_3d": self.class_buffer.get(ang, "TALL_SOLID_WALL")
                })
        return contour

    def compute_astar_2_5d(self) -> Tuple[List[Dict[str, float]], str, float]:
        return compute_astar_2_5d(
            self.get_probability_grid(), self.semantic_matrix, self.portals,
            self.ox, self.oy, self.res, self.cfg.PROB_OCC_THRESH, self.dil_kernel,
            self.is_in_bounds, self.world_to_grid, self.grid_to_world
        )

    def analyze_5_sectors_3d(self) -> Dict[str, Dict[str, Any]]:
        return analyze_5_sectors_3d(self.d1_buffer, self.class_buffer, self.portals)

    def generate_ascii_20x20_3d(self) -> str:
        return generate_ascii_20x20_3d(
            self.get_probability_grid(), self.semantic_matrix, self.gh, self.gw,
            self.cfg.PROB_OCC_THRESH, self.cfg.PROB_FREE_THRESH
        )

    def extract_pinpointed_objects(self) -> List[Dict[str, Any]]:
        return extract_connected_objects(
            self.get_closed_occupancy(),
            self.semantic_matrix,
            self.d2_buffer,
            self.ox,
            self.oy,
            self.res,
            self.cfg.MIN_RANGE_CM,
            self.max_range_cm
        )

    def extract_3d_voxels(self) -> List[Dict[str, Any]]:
        prob_grid = self.get_probability_grid()
        closed_occ = self.get_closed_occupancy()
        return extract_clustered_voxels(
            closed_occ,
            prob_grid,
            self.semantic_matrix,
            self.verified_floor,
            self.dist_grid_cm,
            self.ox,
            self.oy,
            self.res,
            self.max_range_cm,
            self.cfg.PROB_OCC_THRESH
        )

    def _clear_grids_only(self):
        self.grid_low.fill(self.cfg.L_0)
        self.grid_high.fill(self.cfg.L_0)
        self.semantic_matrix.fill(0)
        self.verified_floor.fill(False)
        self.points_3d.clear()
        self.portals.clear()
        self.d1_buffer.clear()
        self.d2_buffer.clear()
        self.d1_miss_counts.clear()
        self.class_buffer.clear()
        self.last_theta = None
        self.last_d1 = None

    def reset(self):
        self._ping_replay_buffer.clear()
        self._clear_grids_only()
