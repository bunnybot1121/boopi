from PIL import Image

# Open spritesheet
img = Image.open('assets/animations/spritesheet.png').convert("RGBA")
width, height = img.size

print(f"Image size: {width}x{height}")

# Make white transparent
datas = img.getdata()
newData = []
for item in datas:
    # item is (R, G, B, A)
    # If the pixel is mostly white, turn it transparent
    if item[0] > 240 and item[1] > 240 and item[2] > 240:
        newData.append((255, 255, 255, 0))
    else:
        newData.append(item)

img.putdata(newData)

# Cut into 4 frames (2x2 grid)
w, h = width // 2, height // 2
frames = []

for row in range(2):
    for col in range(2):
        left = col * w
        upper = row * h
        right = left + w
        lower = upper + h
        frame = img.crop((left, upper, right, lower))
        
        # Center crop the 250x250 out of each 512x512 frame so it perfectly aligns?
        # Actually let's just resize it to fit into 250x250
        frame.thumbnail((250, 250))
        frames.append(frame)

# Save as talking.gif (loop=0 means loop forever, duration in ms)
frames[0].save('assets/animations/talking.gif',
               save_all=True, append_images=frames[1:], optimize=False, duration=150, loop=0)

# Save others
frames[0].save('assets/animations/idle.gif', save_all=True, append_images=[frames[0]], duration=1000, loop=0)
frames[1].save('assets/animations/listening.gif', save_all=True, append_images=[frames[1]], duration=1000, loop=0)
frames[2].save('assets/animations/thinking.gif', save_all=True, append_images=[frames[2]], duration=1000, loop=0)
frames[3].save('assets/animations/error.gif', save_all=True, append_images=[frames[3]], duration=1000, loop=0)

print("GIFs Generated!")
