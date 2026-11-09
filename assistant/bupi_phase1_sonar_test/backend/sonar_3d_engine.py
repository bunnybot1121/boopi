"""
Dual-Ultrasonic + Dual-Servo 2.5D/3D Volumetric Mapping Engine.
Coordinates multi-layer 120x120 Log-Odds grid, differential depth classification,
3D point cloud generation, and volumetric voxel extraction.
"""

import math
from typing import Dict, List, Optional, Tuple, Any
import numpy as np
import cv2

from .config import CONFIG, SonarGridConfig
from .astar_2_5d import compute_astar_2_5d, analyze_5_sectors_3d, generate_ascii_20x20_3d


class Sonar3DEngine:
    def __init__(self, cfg: SonarGridConfig = CONFIG):
        self.cfg = cfg
        self.gw = cfg.GRID_WIDTH       # 120
        self.gh = cfg.GRID_HEIGHT      # 120
        self.res = cfg.RESOLUTION_CM   # 4.0 cm
        self.ox = cfg.ORIGIN_X         # 60
        self.oy = cfg.ORIGIN_Y         # 60

        # Layer 0: Dual Log-Odds Occupancy Grids (Low & High planes)
        self.grid_low = np.full((self.gh, self.gw), cfg.L_0, dtype=np.float32)
        self.grid_high = np.full((self.gh, self.gw), cfg.L_0, dtype=np.float32)

        # Layer 1: Semantic Classification Matrix (0=Unknown, 1=Floor, 2=Step, 3=Wall, 4=Overhang, 5=Portal)
        self.semantic_matrix = np.zeros((self.gh, self.gw), dtype=np.uint8)

        # 3D Point Cloud and Feature Buffers
        self.points_3d: List[Dict[str, float]] = []
        self.classified_features: List[Dict[str, Any]] = []
        self.portals: List[Dict[str, Any]] = []
        self.last_theta: Optional[float] = None
        self.last_d1: Optional[float] = None

        # Angular buffers for fast sector queries (0..180 deg)
        self.d1_buffer: Dict[int, float] = {}
        self.d2_buffer: Dict[int, float] = {}
        self.class_buffer: Dict[int, str] = {}

        # Dilation structuring element (12 cm radius = 3 cells)
        self.dil_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))

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
        """
        Processes single-pass dual-beam ultrasonic telemetry:
        1. Classifies 2.5D feature (Wall, Low Step, Overhang, Portal, Corridor).
        2. Carves free space and hits in Log-Odds grids.
        3. Generates true 3D point cloud coordinates (X, Y, Z).
        """
        rad = math.radians(theta_deg)
        phi_rad = math.radians(pitch_deg)
        cos_t, sin_t = math.cos(rad), math.sin(rad)
        bin_idx = int(round(theta_deg))

        # 1. Doorway Portal Detection (Horizontal Discontinuity)
        is_portal = False
        if valid1 and d1_cm < self.cfg.MAX_RANGE_CM:
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

        if valid2 and d2_cm < self.cfg.MAX_RANGE_CM:
            self.d2_buffer[bin_idx] = d2_cm

        # 2. Single-Pass Differential Depth Classifier
        f_class, f_color, f_z = "OPEN_CORRIDOR", "#00e5ff", 0.0
        if valid1 and valid2 and d1_cm < 390.0 and d2_cm < 390.0:
            delta_v = d2_cm - d1_cm
            if abs(delta_v) <= 25.0:
                f_class, f_color, f_z = "TALL_SOLID_WALL", "#ff3344", 25.0
            elif delta_v > 30.0:
                f_class, f_color, f_z = "LOW_STEP_RUBBLE", "#ffb300", 6.0
            elif delta_v < -30.0:
                f_class, f_color, f_z = "OVERHANG_HAZARD", "#ff6d00", 18.0
        elif valid1 and d1_cm < 390.0:
            f_class, f_color, f_z = "TALL_SOLID_WALL", "#ff3344", 25.0

        self.class_buffer[bin_idx] = f_class

        # 3. Raycast Log-Odds Grid & Carve Depth Behind Rubble
        self._integrate_ray(self.grid_low, theta_deg, d1_cm, valid1)
        self._integrate_ray(self.grid_high, theta_deg, d2_cm, valid2)

        if valid1 and d1_cm < 390.0:
            c1, r1 = self.world_to_grid(d1_cm * cos_t, d1_cm * sin_t)
            if self.is_in_bounds(c1, r1):
                if f_class == "LOW_STEP_RUBBLE":
                    self.semantic_matrix[r1, c1] = 2
                    if valid2 and d2_cm > d1_cm:
                        c2, r2 = self.world_to_grid(d2_cm * cos_t, d2_cm * sin_t)
                        for bc, br in self._bresenham(c1, r1, c2, r2)[1:]:
                            if self.is_in_bounds(bc, br):
                                self.grid_low[br, bc] = max(-2.5, self.grid_low[br, bc] - 0.40)
                                self.semantic_matrix[br, bc] = 1
                elif f_class == "TALL_SOLID_WALL":
                    self.semantic_matrix[r1, c1] = 3
                elif f_class == "OVERHANG_HAZARD":
                    self.semantic_matrix[r1, c1] = 4

        # 4. 3D Point Cloud Buffers (X, Y, Z in cm)
        p1_3d = {"x": round(d1_cm * cos_t, 1), "y": round(d1_cm * sin_t, 1), "z": 4.0, "beam": "low", "class": f_class} if (valid1 and d1_cm < 390.0) else None
        p2_3d = {"x": round(d2_cm * math.cos(phi_rad) * cos_t, 1), "y": round(d2_cm * math.cos(phi_rad) * sin_t, 1), "z": round(14.0 + (d2_cm * math.sin(phi_rad)), 1), "beam": "high", "class": f_class} if (valid2 and d2_cm < 390.0) else None

        if p1_3d: self.points_3d.append(p1_3d)
        if p2_3d: self.points_3d.append(p2_3d)
        if len(self.points_3d) > 300: self.points_3d = self.points_3d[-300:]

        return {
            "theta_deg": round(theta_deg, 1), "s1_ang": round(s1_ang, 1), "s2_ang": round(s2_ang, 1),
            "d1_cm": round(d1_cm, 1), "d2_cm": round(d2_cm, 1), "delta_d": round(d2_cm - d1_cm, 1),
            "class": f_class, "color": f_color, "z_cm": f_z, "is_portal": is_portal,
            "p1_3d": p1_3d, "p2_3d": p2_3d
        }

    def _integrate_ray(self, target_grid: np.ndarray, theta: float, dist_cm: float, is_valid: bool):
        if dist_cm <= 0.0: return
        eff_dist = min(max(dist_cm, self.cfg.MIN_RANGE_CM), self.cfg.MAX_RANGE_CM)
        for off in [-6.0, 0.0, 6.0]:
            rad = math.radians(theta + off)
            gw = math.exp(-0.5 * ((off / 4.0) ** 2))
            c_end, r_end = self.world_to_grid(eff_dist * math.cos(rad), eff_dist * math.sin(rad))
            pts = self._bresenham(self.ox, self.oy, c_end, r_end)
            for c, r in pts[:-2]:
                if self.is_in_bounds(c, r):
                    target_grid[r, c] = max(self.cfg.L_MIN, target_grid[r, c] + (self.cfg.L_FREE * gw))
                    if self.semantic_matrix[r, c] == 0:
                        self.semantic_matrix[r, c] = 1 # OPEN_CORRIDOR
            if is_valid and eff_dist < (self.cfg.MAX_RANGE_CM - 8.0):
                for c, r in pts[-2:]:
                    if self.is_in_bounds(c, r):
                        target_grid[r, c] = min(self.cfg.L_MAX, target_grid[r, c] + (self.cfg.L_HIT * gw))

    def get_probability_grid(self) -> np.ndarray:
        odds = np.exp(self.grid_low)
        return odds / (1.0 + odds)

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
        """
        Clusters continuous obstacle returns across angular bins to pinpoint
        exact (X, Y) obstacle centroids, physical widths, distances, and 3D classes.
        Fuses Sensor 1 (Low) and Sensor 2 (High) to classify vertical boundaries.
        """
        objects = []
        if not self.d1_buffer:
            return objects

        sorted_angles = sorted(self.d1_buffer.keys())
        clusters: List[List[Tuple[int, float]]] = []
        current_cluster: List[Tuple[int, float]] = []

        for ang in sorted_angles:
            d = self.d1_buffer[ang]
            if d < (self.cfg.MAX_RANGE_CM - 15.0) and d > self.cfg.MIN_RANGE_CM:
                if not current_cluster:
                    current_cluster.append((ang, d))
                else:
                    prev_ang, prev_d = current_cluster[-1]
                    if abs(ang - prev_ang) <= 6 and abs(d - prev_d) <= 25.0:
                        current_cluster.append((ang, d))
                    else:
                        if len(current_cluster) >= 2:
                            clusters.append(current_cluster)
                        current_cluster = [(ang, d)]
            else:
                if len(current_cluster) >= 2:
                    clusters.append(current_cluster)
                current_cluster = []

        if len(current_cluster) >= 2:
            clusters.append(current_cluster)

        obj_id = 1
        for cluster in clusters:
            min_entry = min(cluster, key=lambda pt: pt[1])
            best_ang, min_dist = min_entry[0], min_entry[1]
            rad = math.radians(best_ang)

            exact_x = round(min_dist * math.cos(rad), 1)
            exact_y = round(min_dist * math.sin(rad), 1)

            ang_start, d_start = cluster[0]
            ang_end, d_end = cluster[-1]
            x_start = d_start * math.cos(math.radians(ang_start))
            y_start = d_start * math.sin(math.radians(ang_start))
            x_end = d_end * math.cos(math.radians(ang_end))
            y_end = d_end * math.sin(math.radians(ang_end))
            width_cm = round(math.hypot(x_end - x_start, y_end - y_start), 1)
            width_cm = max(width_cm, 8.0)

            high_dists = [self.d2_buffer[a] for a, _ in cluster if a in self.d2_buffer and self.d2_buffer[a] < 390.0]

            if high_dists:
                avg_high = sum(high_dists) / len(high_dists)
                delta_h = avg_high - min_dist
                if abs(delta_h) <= 20.0:
                    cls_name = "TALL_SOLID_WALL"
                    label = "Tall Solid Wall"
                    color = "#ff3344"
                    height_cm = 25.0
                    traversable = False
                elif delta_h > 20.0:
                    cls_name = "LOW_STEP_RUBBLE"
                    label = "Low Step / Rubble"
                    color = "#ffb300"
                    height_cm = 6.0
                    traversable = True
                else:
                    cls_name = "OVERHANG_HAZARD"
                    label = "Hanging Overhang"
                    color = "#ff6d00"
                    height_cm = 18.0
                    traversable = False
            else:
                cls_name = "LOW_STEP_RUBBLE" if min_dist < 150.0 else "TALL_SOLID_WALL"
                label = "Low Floor Obstacle" if min_dist < 150.0 else "Tall Barrier"
                color = "#ffb300" if min_dist < 150.0 else "#ff3344"
                height_cm = 6.0 if min_dist < 150.0 else 25.0
                traversable = (min_dist < 150.0)

            objects.append({
                "id": f"OBJ-{obj_id}",
                "class": cls_name,
                "label": label,
                "x_cm": exact_x,
                "y_cm": exact_y,
                "distance_cm": round(min_dist, 1),
                "angle_deg": round(best_ang, 1),
                "width_cm": width_cm,
                "height_cm": height_cm,
                "traversable": traversable,
                "color": color,
                "points_count": len(cluster)
            })
            obj_id += 1

        return objects

    def extract_3d_voxels(self) -> List[Dict[str, Any]]:
        voxels = []
        prob_grid = self.get_probability_grid()
        h, w = prob_grid.shape
        step = 1 if np.sum(prob_grid >= self.cfg.PROB_OCC_THRESH) < 400 else 2
        for r in range(0, h, step):
            for c in range(0, w, step):
                sem, p = self.semantic_matrix[r, c], prob_grid[r, c]
                wx, wy = self.grid_to_world(c, r)
                if sem == 2:
                    voxels.append({"x": round(wx, 1), "y": round(wy, 1), "z_max": 6.0, "z_min": 0.0, "type": "LOW_STEP", "color": "#ffb300"})
                elif sem == 4:
                    voxels.append({"x": round(wx, 1), "y": round(wy, 1), "z_max": 25.0, "z_min": 12.0, "type": "OVERHANG", "color": "#ff6d00"})
                elif sem == 3 or p >= self.cfg.PROB_OCC_THRESH:
                    voxels.append({"x": round(wx, 1), "y": round(wy, 1), "z_max": 25.0, "z_min": 0.0, "type": "TALL_WALL", "color": "#ff3344"})
                elif p <= self.cfg.PROB_FREE_THRESH and (r % 3 == 0 and c % 3 == 0):
                    voxels.append({"x": round(wx, 1), "y": round(wy, 1), "z_max": 0.0, "z_min": 0.0, "type": "FREE_FLOOR", "color": "#00e5ff"})
        return voxels

    def reset(self):
        self.grid_low.fill(self.cfg.L_0)
        self.grid_high.fill(self.cfg.L_0)
        self.semantic_matrix.fill(0)
        self.points_3d.clear()
        self.portals.clear()
        self.d1_buffer.clear()
        self.d2_buffer.clear()
        self.class_buffer.clear()
        self.last_theta = None
        self.last_d1 = None
