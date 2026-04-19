import cv2
import imageio
import numpy as np
import os

mp4_map = {
    'fgt.mp4': 'thinking.gif',
    'ert.mp4': 'listening.gif',
    '214.mp4': 'talking.gif',
    'sedf.mp4': 'error.gif',
    'xd.mp4': 'idle.gif',
    'derftgyhj.mp4': 'angry.gif',
    '0418.mp4': 'happy.gif'
}

base_dir = r"c:\Users\Admin\minefav"
out_dir = r"c:\Users\Admin\minefav\assistant\assets\animations"

os.makedirs(out_dir, exist_ok=True)

for mp4_file, gif_file in mp4_map.items():
    in_path = os.path.join(base_dir, mp4_file)
    out_path = os.path.join(out_dir, gif_file)
    
    print(f"Processing {in_path} to {out_path}...")
    
    if not os.path.exists(in_path):
        print(f"Missing {in_path}")
        continue
        
    reader = imageio.get_reader(in_path)
    # Safely get FPS or default to 24
    meta = reader.get_meta_data()
    fps = meta.get('fps', 24)
    if fps == 0 or fps is None:
        fps = 24
        
    frames = []
    
    for idx, frame in enumerate(reader):
        # Frame is RGB numpy array
        
        # Convert to BGR for cv2
        frame_bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        
        # Resize to make processing faster and GIF smaller (assuming square)
        frame_bgr = cv2.resize(frame_bgr, (250, 250), interpolation=cv2.INTER_AREA)
        
        h, w = frame_bgr.shape[:2]
        mask = np.zeros((h+2, w+2), np.uint8)
        
        tolerance = (30, 30, 30)
        replacement_color = (255, 0, 255) # Magenta in BGR
        
        # Flood fill corners
        cv2.floodFill(frame_bgr, mask, (0,0), replacement_color, tolerance, tolerance, cv2.FLOODFILL_FIXED_RANGE)
        cv2.floodFill(frame_bgr, mask, (w-1,0), replacement_color, tolerance, tolerance, cv2.FLOODFILL_FIXED_RANGE)
        cv2.floodFill(frame_bgr, mask, (0,h-1), replacement_color, tolerance, tolerance, cv2.FLOODFILL_FIXED_RANGE)
        cv2.floodFill(frame_bgr, mask, (w-1,h-1), replacement_color, tolerance, tolerance, cv2.FLOODFILL_FIXED_RANGE)
        
        # But wait! If the character is floating and doesn't touch the edges, corners are enough.
        # Check standard coordinates just in case:
        cv2.floodFill(frame_bgr, mask, (w//2,0), replacement_color, tolerance, tolerance, cv2.FLOODFILL_FIXED_RANGE)
        cv2.floodFill(frame_bgr, mask, (w//2,h-1), replacement_color, tolerance, tolerance, cv2.FLOODFILL_FIXED_RANGE)
        
        # Convert to RGBA
        rgba = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGBA)
        
        # Make Magenta transparent
        magenta_mask = (rgba[:,:,0] == 255) & (rgba[:,:,1] == 0) & (rgba[:,:,2] == 255)
        rgba[magenta_mask] = [0, 0, 0, 0]
        
        frames.append(rgba)
        
        if len(frames) >= 75: # limit to max 75 frames
            break
            
    # Write to GIF
    duration = 1000 / fps
    imageio.mimsave(out_path, frames, format='GIF', loop=0, duration=duration)
    print(f"Saved {out_path} with {len(frames)} frames")

print("All done!")
