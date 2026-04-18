from dataclasses import dataclass
import os
import sys

def get_base_path():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

@dataclass
class Config:
    CHAR_SIZE: int = 140
    WINDOW_MARGIN_RIGHT: int = 80
    WINDOW_MARGIN_BOTTOM: int = 130
    DEBUG_MODE: bool = True
    ANIM_DIR: str = "assets/animations"
    ANIM_FILES: dict = None

    def __post_init__(self):
        base_dir = get_base_path()
        abs_anim_dir = os.path.join(base_dir, self.ANIM_DIR)
        self.ANIM_FILES = {
            "idle":      os.path.join(abs_anim_dir, "idle.mp4"),
            "listening": os.path.join(abs_anim_dir, "listening.mp4"),
            "thinking":  os.path.join(abs_anim_dir, "thinking.mp4"),
            "talking":   os.path.join(abs_anim_dir, "talking.mp4"),
            "error":     os.path.join(abs_anim_dir, "error.mp4"),
        }

CFG = Config()
