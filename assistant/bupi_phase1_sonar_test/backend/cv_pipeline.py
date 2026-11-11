"""
OpenCV Image Processing Pipeline for BUPI Sonar DIP Tensor.
Transforms raw Bayesian occupancy grid into Grayscale, Gap-Free Semantic RGB, and Dilated Maps.
"""

import cv2
import base64
import numpy as np
from typing import List, Tuple, Optional, Dict, Any
from .config import CONFIG, SonarGridConfig


class SonarCVPipeline:
    def __init__(self, cfg: SonarGridConfig = CONFIG):
        self.cfg = cfg
        self.dilation_kernel = cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE,
            (self.cfg.DILATION_KERNEL_SIZE, self.cfg.DILATION_KERNEL_SIZE)
        )
        self.close_kernel = cv2.getStructuringElement(
            cv2.MORPH_RECT,
            (self.cfg.MORPH_CLOSE_SIZE, self.cfg.MORPH_CLOSE_SIZE)
        )

    def generate_grayscale_image(self, prob_grid: np.ndarray) -> np.ndarray:
        """DIP Raw Probability Map: uint8 [0..255]."""
        return np.clip(prob_grid * 255.0, 0, 255).astype(np.uint8)

    def generate_dilation_mask(self, grid: np.ndarray) -> np.ndarray:
        """Binary obstacle mask dilated with structuring element representing robot clearance buffer."""
        if grid.dtype != np.uint8:
            obs_mask = (grid >= self.cfg.PROB_OCC_THRESH).astype(np.uint8) * 255
        else:
            obs_mask = grid
        return cv2.dilate(obs_mask, self.dilation_kernel, iterations=1)

    def generate_semantic_image(
        self,
        prob_grid: np.ndarray,
        portals: List[Any],
        semantic_matrix: Optional[np.ndarray] = None,
        points_3d: Optional[List[Dict[str, Any]]] = None,
        vertical_features: Optional[List[Any]] = None,
        show_dilation: bool = True,
        closed_occ: Optional[np.ndarray] = None,
        origin_x: Optional[int] = None,
        origin_y: Optional[int] = None,
        resolution_cm: Optional[float] = None
    ) -> np.ndarray:
        """
        Generates gap-free 3-channel RGB semantic image using Upgrade 4 palette:
        - Unknown:         #0b1017 -> (11, 16, 23)
        - Free space:      #0d3b46 -> (13, 59, 70)
        - Tall Solid Wall: #ff2a54 -> (255, 42, 84)
        - Low Step/Rubble: #ffb703 -> (255, 183, 3)
        - Hanging Overhang:#ff6d00 -> (255, 109, 0)
        - Depth Portals:   #e040fb -> (224, 64, 251)
        - Robot Origin:    #00e676 -> (0, 230, 118)
        """
        h, w = prob_grid.shape
        ox = origin_x if origin_x is not None else self.cfg.ORIGIN_X
        oy = origin_y if origin_y is not None else self.cfg.ORIGIN_Y
        res = resolution_cm if resolution_cm is not None else self.cfg.RESOLUTION_CM

        # Base canvas: gap-free Unknown (#0b1017)
        semantic_rgb = np.full((h, w, 3), [11, 16, 23], dtype=np.uint8)

        # Morphologically closed solid obstacle mask
        if closed_occ is not None:
            obs_mask_uint8 = closed_occ
        else:
            raw_obs = (prob_grid >= self.cfg.PROB_OCC_THRESH).astype(np.uint8) * 255
            obs_mask_uint8 = cv2.morphologyEx(raw_obs, cv2.MORPH_CLOSE, self.close_kernel)

        obs_bool = obs_mask_uint8 > 0

        # 1. Free Space Floor (#0d3b46)
        free_mask = (prob_grid < self.cfg.PROB_FREE_THRESH) & (~obs_bool)
        semantic_rgb[free_mask] = [13, 59, 70]

        # 2. Solid Obstacle Walls (#ff2a54 default)
        semantic_rgb[obs_bool] = [255, 42, 84]

        # 3. 2.5D Semantic Elevation Classes clipped cleanly to occupied walls
        if semantic_matrix is not None and isinstance(semantic_matrix, np.ndarray):
            semantic_rgb[obs_bool & (semantic_matrix == 2)] = [255, 183, 3]   # Low Step
            semantic_rgb[obs_bool & (semantic_matrix == 3)] = [255, 42, 84]   # Tall Wall
            semantic_rgb[obs_bool & (semantic_matrix == 4)] = [255, 109, 0]   # Overhang

        # 4. Doorway Depth Portal Markers (#e040fb)
        for p in portals:
            px = p.get("x_cm") if isinstance(p, dict) else getattr(p, "x_cm", None)
            py = p.get("y_cm") if isinstance(p, dict) else getattr(p, "y_cm", None)
            if px is not None and py is not None:
                pc = int(round(ox + (px / res)))
                pr = int(round(oy - (py / res)))
                if 0 <= pc < w and 0 <= pr < h:
                    cv2.circle(semantic_rgb, (pc, pr), 3, (224, 64, 251), -1)

        # 5. Safety Buffer Dilation Contour
        if show_dilation and np.any(obs_mask_uint8):
            dilated = self.generate_dilation_mask(obs_mask_uint8)
            contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            cv2.drawContours(semantic_rgb, contours, -1, (0, 229, 255), 1)

        # 6. Robot / Sensor Origin Crosshair (#00e676)
        cv2.circle(semantic_rgb, (ox, oy), 3, (0, 230, 118), -1)
        cv2.line(semantic_rgb, (ox - 5, oy), (ox + 5, oy), (0, 230, 118), 1)
        cv2.line(semantic_rgb, (ox, oy - 5), (ox, oy + 5), (0, 230, 118), 1)

        return semantic_rgb

    def encode_png_bytes(self, image_rgb: np.ndarray) -> bytes:
        """Convert RGB image to PNG byte stream (reverses to BGR for cv2.imencode)."""
        bgr = cv2.cvtColor(image_rgb, cv2.COLOR_RGB2BGR)
        success, encoded = cv2.imencode('.png', bgr)
        return encoded.tobytes() if success else b""

    def encode_base64_data_url(self, image_rgb: np.ndarray) -> str:
        """Encode RGB image as base64 data:image/png;base64 string."""
        png_bytes = self.encode_png_bytes(image_rgb)
        b64 = base64.b64encode(png_bytes).decode('ascii')
        return f"data:image/png;base64,{b64}"
