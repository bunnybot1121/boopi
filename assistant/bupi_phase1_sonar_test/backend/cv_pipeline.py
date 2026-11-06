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
        portals: List[DepthPortal],
        vertical_features: List[VerticalFeature],
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

        # 3. Draw Open Depth Corridors (Cyan lines/areas behind low obstacles)
        for vf in vertical_features:
            if vf.feature_type == "LOW_OBSTACLE" and vf.corridor_end_x is not None:
                # Origin -> low obstacle -> corridor end
                c1 = int(round(self.cfg.ORIGIN_X + (vf.x_cm / self.cfg.RESOLUTION_CM)))
                r1 = int(round(self.cfg.ORIGIN_Y - (vf.y_cm / self.cfg.RESOLUTION_CM)))
                c2 = int(round(self.cfg.ORIGIN_X + (vf.corridor_end_x / self.cfg.RESOLUTION_CM)))
                r2 = int(round(self.cfg.ORIGIN_Y - (vf.corridor_end_y / self.cfg.RESOLUTION_CM)))
                cv2.line(semantic_rgb, (c1, r1), (c2, r2), (0, 229, 255), 1)

        # 4. Color classified vertical features (Tall walls, low obstacles, overhangs)
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

        # 5. Draw 3D Depth Portal Edges (Magenta markers)
        for p in portals:
            pc = int(round(self.cfg.ORIGIN_X + (p.x_cm / self.cfg.RESOLUTION_CM)))
            pr = int(round(self.cfg.ORIGIN_Y - (p.y_cm / self.cfg.RESOLUTION_CM)))
            if 0 <= pc < w and 0 <= pr < h:
                cv2.circle(semantic_rgb, (pc, pr), 3, (224, 64, 251), -1)

        # 6. Safety Buffer Dilation Overlay (if enabled)
        if show_dilation:
            dilated = self.generate_dilation_mask(prob_grid)
            # Find contours of dilated mask
            contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            cv2.drawContours(semantic_rgb, contours, -1, (0, 229, 255), 1)

        # 7. Robot / Sensor Origin Marker at (60, 60)
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

