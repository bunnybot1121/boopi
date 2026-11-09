"""
OpenCV Image Processing Pipeline for BUPI Sonar DIP Tensor.
Transforms raw Bayesian occupancy grid into Grayscale, Semantic Multi-Channel, and Dilated Maps.
"""

import cv2
import base64
import numpy as np
from typing import List, Tuple
from .config import CONFIG, SonarGridConfig
from .depth_profiler import DepthPortal, VerticalFeature


class SonarCVPipeline:
    def __init__(self, cfg: SonarGridConfig = CONFIG):
        self.cfg = cfg
        self.dilation_kernel = cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE,
            (self.cfg.DILATION_KERNEL_SIZE, self.cfg.DILATION_KERNEL_SIZE)
        )

    def generate_grayscale_image(self, prob_grid: np.ndarray) -> np.ndarray:
        """
        DIP Raw Probability Map: uint8 [0..255].
        0 = Free space, 128 = Unobserved/Unknown, 255 = Occupied Obstacle.
        """
        # Linear scale from prob [0, 1] to uint8 [0, 255]
        gray = np.clip(prob_grid * 255.0, 0, 255).astype(np.uint8)
        return gray

    def generate_dilation_mask(self, prob_grid: np.ndarray) -> np.ndarray:
        """
        Binary obstacle mask dilated with structuring element representing robot collision safety buffer.
        """
        # Threshold: obstacle cells with P > 0.65
        obs_mask = (prob_grid >= self.cfg.PROB_OCC_THRESH).astype(np.uint8) * 255
        dilated = cv2.dilate(obs_mask, self.dilation_kernel, iterations=1)
        return dilated

    def generate_semantic_image(
        self,
        prob_grid: np.ndarray,
        portals: List[Any],
        semantic_matrix: Optional[np.ndarray] = None,
        points_3d: Optional[List[Dict[str, Any]]] = None,
        vertical_features: Optional[List[Any]] = None,
        show_dilation: bool = True
    ) -> np.ndarray:
        """
        Generate 3-channel RGB semantic image:
        - Free floor: Slate (#1a2332)
        - Unknown: Deep Carbon (#0b0f14)
        - Tall Solid Wall: Red (#ff3344)
        - Low Rubble / Step: Yellow (#ffb300)
        - Open Depth Corridor: Cyan (#00e5ff)
        - Hanging Overhang: Orange (#ff6d00)
        - Depth Portals: Magenta (#e040fb)
        - Safety Buffer Dilation: Translucent Neon Line
        - Robot Origin: Matrix Green (#00e676)
        """
        h, w = prob_grid.shape
        # Base canvas: dark carbon (RGB: 11, 15, 20)
        semantic_rgb = np.full((h, w, 3), [11, 15, 20], dtype=np.uint8)

        # 1. Free Space Floor (P < 0.35): Slate Blue/Gray (26, 35, 50)
        free_mask = prob_grid < self.cfg.PROB_FREE_THRESH
        semantic_rgb[free_mask] = [26, 35, 50]

        # 2. Obstacle Cells (P > 0.65): Default Coral/Red Wall (255, 51, 68)
        obs_mask = prob_grid >= self.cfg.PROB_OCC_THRESH
        semantic_rgb[obs_mask] = [255, 51, 68]

        # 3. 2.5D Semantic Matrix Overlay
        if semantic_matrix is not None:
            # Low Step / Rubble: Yellow (#ffb300)
            semantic_rgb[semantic_matrix == 2] = [255, 179, 0]
            # Tall Solid Wall: Red (#ff3344)
            semantic_rgb[semantic_matrix == 3] = [255, 51, 68]
            # Hanging Overhang: Orange (#ff6d00)
            semantic_rgb[semantic_matrix == 4] = [255, 109, 0]

        # 4. Color classified vertical features (legacy fallback)
        if vertical_features:
            for vf in vertical_features:
                col = int(round(self.cfg.ORIGIN_X + (vf.x_cm / self.cfg.RESOLUTION_CM)))
                row = int(round(self.cfg.ORIGIN_Y - (vf.y_cm / self.cfg.RESOLUTION_CM)))
                if 0 <= col < w and 0 <= row < h:
                    if vf.feature_type == "LOW_OBSTACLE":
                        cv2.circle(semantic_rgb, (col, row), 2, (255, 179, 0), -1)  # Amber Yellow
                    elif vf.feature_type == "HANGING_OVERHANG":
                        cv2.circle(semantic_rgb, (col, row), 2, (255, 109, 0), -1)  # Orange
                    elif vf.feature_type == "TALL_WALL":
                        cv2.circle(semantic_rgb, (col, row), 2, (255, 51, 68), -1)   # Red

        # 5. Exact Obstacle Scatter Points from 3D Engine
        if points_3d:
            for pt in points_3d[-200:]:
                x_val = pt.get("x")
                y_val = pt.get("y")
                if x_val is not None and y_val is not None:
                    col = int(round(self.cfg.ORIGIN_X + (x_val / self.cfg.RESOLUTION_CM)))
                    row = int(round(self.cfg.ORIGIN_Y - (y_val / self.cfg.RESOLUTION_CM)))
                    if 0 <= col < w and 0 <= row < h:
                        beam = pt.get("beam", "low")
                        if beam == "high":
                            cv2.circle(semantic_rgb, (col, row), 2, (255, 179, 0), -1)  # High beam amber
                        else:
                            cv2.circle(semantic_rgb, (col, row), 2, (255, 51, 68), -1)   # Low beam red

        # 6. Draw 3D Depth Portal Edges (Magenta markers)
        for p in portals:
            px = p.get("x_cm") if isinstance(p, dict) else getattr(p, "x_cm", None)
            py = p.get("y_cm") if isinstance(p, dict) else getattr(p, "y_cm", None)
            if px is not None and py is not None:
                pc = int(round(self.cfg.ORIGIN_X + (px / self.cfg.RESOLUTION_CM)))
                pr = int(round(self.cfg.ORIGIN_Y - (py / self.cfg.RESOLUTION_CM)))
                if 0 <= pc < w and 0 <= pr < h:
                    cv2.circle(semantic_rgb, (pc, pr), 3, (224, 64, 251), -1)

        # 7. Safety Buffer Dilation Overlay (if enabled)
        if show_dilation:
            dilated = self.generate_dilation_mask(prob_grid)
            contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            cv2.drawContours(semantic_rgb, contours, -1, (0, 229, 255), 1)

        # 8. Robot / Sensor Origin Marker at (60, 60)
        ox, oy = self.cfg.ORIGIN_X, self.cfg.ORIGIN_Y
        cv2.circle(semantic_rgb, (ox, oy), 3, (0, 230, 118), -1)  # Bright Green
        cv2.line(semantic_rgb, (ox - 4, oy), (ox + 4, oy), (0, 230, 118), 1)
        cv2.line(semantic_rgb, (ox, oy - 4), (ox, oy + 4), (0, 230, 118), 1)

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

