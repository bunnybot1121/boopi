import time
import asyncio
import subprocess

text = "Hello! I am ready to talk."
voice = "en-US-AnaNeural"

# Test 1: Subprocess method
start = time.time()
subprocess.run(
    ["python", "-m", "edge_tts", "--text", text, "--voice", voice, "--write-media", "sub.mp3"],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
)
sub_time = time.time() - start
print(f"Subprocess method took: {sub_time:.3f} seconds")

# Test 2: Native Python import method
import edge_tts
async def test_native():
    start = time.time()
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save("native.mp3")
    native_time = time.time() - start
    print(f"Native import method took: {native_time:.3f} seconds")

asyncio.run(test_native())
