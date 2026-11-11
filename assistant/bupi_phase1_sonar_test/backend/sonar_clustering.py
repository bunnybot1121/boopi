"""
Morphological Closing, Connected-Component Object Pinpointing,
and Clustered 3D Voxel Extraction for BUPI Sonar Imaging.
"""

import math
from typing import Any, Dict, List, Tuple
import numpy as np
import cv2


def get_closed_occupancy_mask(
    prob_grid: np.ndarray,
    occ_thresh: float = 0.65,
    morph_close_size: int = 3
) -> np.ndarray:
    """Applies 3x3 morphological closing to fuse small gaps into solid wall contours."""
    occ_raw = (prob_grid >= occ_thresh).astype(np.uint8) * 255
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (morph_close_size, morph_close_size))
    return cv2.morphologyEx(occ_raw, cv2.MORPH_CLOSE, kernel)


def extract_connected_objects(
    closed_occ: np.ndarray,
    semantic_matrix: np.ndarray,
    d2_buffer: Dict[int, float],
    ox: int,
    oy: int,
    res: float,
    min_range_cm: float,
    max_range_cm: float
) -> List[Dict[str, Any]]:
    """
    Runs cv2.connectedComponentsWithStats on the closed occupancy mask
    to pinpoint discrete obstacles with exact (X, Y), normal distance,
    physical width, height profile, and 2D bounding boxes.
    """
    objects: List[Dict[str, Any]] = []
    if closed_occ is None or not np.any(closed_occ):
        return objects

    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(closed_occ, connectivity=8)

    for label_idx in range(1, num_labels):
        area = int(stats[label_idx, cv2.CC_STAT_AREA])
        if area < 2:
            continue

        rows, cols = np.where(labels == label_idx)
        wx_arr = (cols - ox) * res
        wy_arr = (oy - rows) * res
        dist_arr = np.hypot(wx_arr, wy_arr)

        # Reject false origin ringing or cells outside displayed range
        valid_mask = (dist_arr >= min_range_cm) & (dist_arr <= max_range_cm)
        if not np.any(valid_mask):
            continue

        rows = rows[valid_mask]
        cols = cols[valid_mask]
        wx_arr = wx_arr[valid_mask]
        wy_arr = wy_arr[valid_mask]
        dist_arr = dist_arr[valid_mask]

        min_idx = int(np.argmin(dist_arr))
        min_dist = round(float(dist_arr[min_idx]), 1)
        cx_cm = round(float(np.mean(wx_arr)), 1)
        cy_cm = round(float(np.mean(wy_arr)), 1)
        bearing_deg = round((math.degrees(math.atan2(cy_cm, cx_cm)) + 360.0) % 360.0, 1)

        # Estimate true physical object width using oriented bounding rectangle
        if len(cols) >= 3:
            pts = np.column_stack((cols, rows)).astype(np.float32)
            _, (rw, rh), _ = cv2.minAreaRect(pts)
            width_cm = round(max(float(rw), float(rh), 2.0) * res, 1)
        else:
            x_span = float(stats[label_idx, cv2.CC_STAT_WIDTH]) * res
            y_span = float(stats[label_idx, cv2.CC_STAT_HEIGHT]) * res
            width_cm = round(max(x_span, y_span, res * 2.0), 1)
        width_cm = max(width_cm, round(res * 2.0, 1))

        # World-coordinate bounding box for Viewport 2 overlay
        bbox_world = {
            "x_min": round(float(np.min(wx_arr) - 0.5 * res), 1),
            "x_max": round(float(np.max(wx_arr) + 0.5 * res), 1),
            "y_min": round(float(np.min(wy_arr) - 0.5 * res), 1),
            "y_max": round(float(np.max(wy_arr) + 0.5 * res), 1)
        }

        # Dual-sensor vertical classification (Low d1 vs High d2)
        sem_vals = semantic_matrix[rows, cols]
        comp_angles = (np.degrees(np.arctan2(wy_arr, wx_arr)) + 360.0) % 360.0
        min_a = int(np.floor(np.min(comp_angles))) - 2
        max_a = int(np.ceil(np.max(comp_angles))) + 2
        high_dists = [
            d2_buffer[a]
            for a in range(max(0, min_a), min(181, max_a + 1))
            if a in d2_buffer and d2_buffer[a] < 390.0
        ]

        if np.any(sem_vals == 4):
            cls_name = "OVERHANG_HAZARD"
        elif high_dists:
            avg_high = sum(high_dists) / len(high_dists)
            delta_h = avg_high - min_dist
            if delta_h > 20.0:
                cls_name = "LOW_STEP_RUBBLE"
            elif delta_h < -20.0:
                cls_name = "OVERHANG_HAZARD"
            else:
                cls_name = "TALL_SOLID_WALL"
        else:
            low_hits = int(np.sum(sem_vals == 2))
            wall_hits = int(np.sum(sem_vals == 3))
            cls_name = "LOW_STEP_RUBBLE" if low_hits > wall_hits else "TALL_SOLID_WALL"

        if cls_name == "LOW_STEP_RUBBLE":
            label, color, height_cm, traversable, directive = (
                "Low Step / Rubble", "#ffb703", 6.0, True, "STEP OVER (LOW)"
            )
        elif cls_name == "OVERHANG_HAZARD":
            label, color, height_cm, traversable, directive = (
                "Hanging Overhang", "#ff6d00", 18.0, False, "STOP / LOW CLEARANCE"
            )
        else:
            label, color, height_cm, traversable, directive = (
                "Tall Solid Wall", "#ff2a54", 25.0, False, "STOP / AVOID"
            )

        objects.append({
            "id": "OBJ-TEMP",
            "class": cls_name,
            "label": label,
            "x_cm": cx_cm,
            "y_cm": cy_cm,
            "distance_cm": min_dist,
            "angle_deg": bearing_deg,
            "width_cm": width_cm,
            "height_cm": height_cm,
            "traversable": traversable,
            "directive": directive,
            "color": color,
            "bbox_world": bbox_world,
            "points_count": int(len(rows))
        })

    # Nearest collision hazard first, deterministic OBJ-01..OBJ-NN IDs
    objects.sort(key=lambda obj: obj["distance_cm"])
    for idx, obj in enumerate(objects, start=1):
        obj["id"] = f"OBJ-{idx:02d}"

    return objects


def extract_clustered_voxels(
    closed_occ: np.ndarray,
    prob_grid: np.ndarray,
    semantic_matrix: np.ndarray,
    verified_floor: np.ndarray,
    dist_grid_cm: np.ndarray,
    ox: int,
    oy: int,
    res: float,
    max_range_cm: float,
    occ_thresh: float = 0.65
) -> List[Dict[str, Any]]:
    """
    Builds clean 3D volumetric voxels:
    - Obstacles come from the morphologically closed wall/object clusters.
    - Floor tiles ONLY render on verified short-range (< 150cm) free cells, never timeout voids.
    """
    voxels: List[Dict[str, Any]] = []

    # 1. Clustered 3D obstacle blocks
    obs_coords = np.argwhere(closed_occ > 0)
    obs_stride = 1 if len(obs_coords) <= 1000 else 2
    for r, c in obs_coords[::obs_stride]:
        wx = round(float((c - ox) * res), 1)
        wy = round(float((oy - r) * res), 1)
        sem = int(semantic_matrix[r, c])
        if sem == 2:
            voxels.append({"x": wx, "y": wy, "z_min": 0.0, "z_max": 8.0, "type": "LOW_STEP", "color": "#ffb703"})
        elif sem == 4:
            voxels.append({"x": wx, "y": wy, "z_min": 16.0, "z_max": 28.0, "type": "OVERHANG", "color": "#ff6d00"})
        else:
            voxels.append({"x": wx, "y": wy, "z_min": 0.0, "z_max": 28.0, "type": "TALL_WALL", "color": "#ff2a54"})

    # 2. Verified short-range floor only (< 150cm, bounded by detected hits, never max-range timeouts)
    floor_cap_cm = min(150.0, 0.85 * max_range_cm)
    floor_mask = verified_floor & (dist_grid_cm < floor_cap_cm) & (prob_grid < occ_thresh) & (closed_occ == 0)
    floor_stride = max(2, int(round(12.0 / max(res, 0.5))))
    sub_floor = np.argwhere(floor_mask[::floor_stride, ::floor_stride])
    for sr, sc in sub_floor:
        r = sr * floor_stride
        c = sc * floor_stride
        wx = round(float((c - ox) * res), 1)
        wy = round(float((oy - r) * res), 1)
        voxels.append({"x": wx, "y": wy, "z_min": 0.0, "z_max": 0.0, "type": "FREE_FLOOR", "color": "#0d3b46"})

    return voxels

