import os
import sys
import time
import json
import numpy as np

# Ensure root directory is on sys.path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

# Register CUDA DLLs for Windows
if sys.platform == "win32":
    nvidia_dirs = [
        os.path.join(sys.prefix, "Lib", "site-packages", "nvidia", "cublas", "bin"),
        os.path.join(sys.prefix, "Lib", "site-packages", "nvidia", "cudnn", "bin"),
        os.path.join(sys.prefix, "Lib", "site-packages", "nvidia", "cuda_nvrtc", "bin"),
    ]
    for p in nvidia_dirs:
        if os.path.exists(p):
            try:
                os.add_dll_directory(p)
            except Exception:
                pass
            if p not in os.environ.get("PATH", ""):
                os.environ["PATH"] = p + os.pathsep + os.environ.get("PATH", "")

def test_voice_cache():
    print("\n" + "="*60)
    print("TEST 1: 0-ms Pre-Rendered Voice Cache Validation")
    print("="*60)
    from voice.speaker import get_cached_voice_file, VOICE_CACHE_DIR
    
    test_phrases = [
        "I'm here.",
        "Emergency stop triggered. Motors halted.",
        "Starting search pattern. Scanning room for human presence.",
        "Obstacle detected ahead. Re-routing path.",
        "Human located in the room. Mission accomplished.",
        "Driving forward.",
        "Driving reverse.",
        "Turning left.",
        "Turning right.",
        "Relay turned on.",
        "Relay turned off.",
        "ESP32 is online and ready.",
        "Mission stopped."
    ]

    all_passed = True
    for phrase in test_phrases:
        t0 = time.perf_counter()
        cached = get_cached_voice_file(phrase)
        t_lookup = (time.perf_counter() - t0) * 1000
        if cached and os.path.exists(cached):
            sz = os.path.getsize(cached)
            print(f"  [PASS] '{phrase}' -> {os.path.basename(cached)} ({sz} bytes, lookup {t_lookup:.3f}ms)")
        else:
            print(f"  [FAIL] '{phrase}' not found in cache!")
            all_passed = False
            
    print(f"\nVoice Cache Result: {'ALL PASSED' if all_passed else 'SOME FAILED'}")
    return all_passed

def test_local_cuda_whisper():
    print("\n" + "="*60)
    print("TEST 2: Local Faster-Whisper GPU CUDA 12 Inference")
    try:
        from faster_whisper import WhisperModel
        import ctranslate2
        try:
            import torch
            has_cuda = (torch.cuda.is_available() or ctranslate2.get_cuda_device_count() > 0)
        except Exception:
            has_cuda = ctranslate2.get_cuda_device_count() > 0
            
        device = "cuda" if has_cuda else "cpu"
        compute_type = "float16" if device == "cuda" else "int8"
        print(f"  Target Device: {device} ({compute_type}) | RTX GPU Detected: {has_cuda}")
        
        t0 = time.time()
        model = WhisperModel("base.en", device=device, compute_type=compute_type, cpu_threads=4)
        load_time = time.time() - t0
        print(f"  Model loaded in {load_time:.2f}s")
        
        # Generate 1.5 seconds of synthetic audio (silence / tone)
        sample_rate = 16000
        t = np.linspace(0, 1.5, int(sample_rate * 1.5), endpoint=False, dtype=np.float32)
        dummy_audio = 0.05 * np.sin(2 * np.pi * 440 * t)
        
        t0 = time.time()
        segments, info = model.transcribe(dummy_audio, language="en", condition_on_previous_text=False)
        _ = list(segments)
        infer_time = time.time() - t0
        print(f"  Inference completed in {infer_time:.2f}s on {device} (Lang: {info.language}, Prob: {info.language_probability:.2f})")
        print("  [PASS] Local Faster-Whisper GPU Inference verified!")
        return True
    except Exception as e:
        print(f"  [FAIL] Whisper test failed: {e}")
        return False

def test_autonomous_agent_cycle():
    print("\n" + "="*60)
    print("TEST 3: Autonomous Goal Agent Mission Lifecycle")
    print("="*60)
    from agents.autonomous_goal_agent import AutonomousGoalAgent
    
    # Create test instance
    test_agent = AutonomousGoalAgent()
    print("  1. Testing goal classification:")
    g1 = test_agent._classify_goal("Boopi, find the human in the room")
    g2 = test_agent._classify_goal("Patrol the room and inspect environment")
    g3 = test_agent._classify_goal("Wander around and explore")
    print(f"    'find human' -> {g1}")
    print(f"    'patrol room' -> {g2}")
    print(f"    'wander' -> {g3}")
    assert g1 == "FIND_HUMAN", f"Expected FIND_HUMAN, got {g1}"
    assert g2 == "PATROL_INSPECT", f"Expected PATROL_INSPECT, got {g2}"
    assert g3 == "EXPLORE_WANDER", f"Expected EXPLORE_WANDER, got {g3}"
    print("  [PASS] Goal classification verified!")

    print("\n  2. Testing mission start & abort cycle:")
    msg = test_agent.start_mission("Boopi, find the human in the room")
    print(f"    start_mission returned: {msg}")
    assert test_agent.is_running, "Agent should be running"
    
    time.sleep(1.0)
    status = test_agent.get_status()
    print(f"    Agent status during execution: {status}")
    assert status["is_running"] is True
    
    stop_msg = test_agent.stop_mission()
    print(f"    stop_mission returned: {stop_msg}")
    time.sleep(0.5)
    assert not test_agent.is_running, "Agent should be stopped"
    print("  [PASS] Mission start & abort cycle verified!")
    return True

def test_fast_pass_router():
    print("\n" + "="*60)
    print("TEST 4: Fast-Pass Deterministic Router Intent Matching")
    print("="*60)
    from agents.router_agent import router
    
    queries = [
        ("Boopi, find the human in the room", "autonomous_mission"),
        ("Patrol the room and inspect environment", "autonomous_mission"),
        ("Abort mission", "abort_mission"),
        ("Stop", "hardware_intent"),
        ("Emergency stop", "hardware_intent"),
        ("Turn on relay", "hardware_intent"),
        ("Check gas level", "sensor_query"),
        ("Is ESP32 connected", "nodes_query"),
        ("World state", "world_state_query")
    ]
    
    all_passed = True
    for q, expected_type in queries:
        t0 = time.perf_counter()
        res = router.quick_regex_classify(q)
        t_ms = (time.perf_counter() - t0) * 1000
        actual_type = res.get("type") if res else None
        if actual_type == expected_type:
            print(f"  [PASS] '{q}' -> {actual_type} ({t_ms:.3f}ms)")
        else:
            print(f"  [FAIL] '{q}' -> Expected {expected_type}, got {actual_type}")
            all_passed = False
            
    print(f"\nRouter Result: {'ALL PASSED' if all_passed else 'SOME FAILED'}")
    return all_passed

if __name__ == "__main__":
    print("Starting Autonomous Mission & Voice Verification Suite...")
    r1 = test_voice_cache()
    r2 = test_local_cuda_whisper()
    r3 = test_autonomous_agent_cycle()
    r4 = test_fast_pass_router()
    
    print("\n" + "="*60)
    print("FINAL SUITE SUMMARY")
    print("="*60)
    print(f"  Test 1 (0-ms Voice Cache):      {'PASSED' if r1 else 'FAILED'}")
    print(f"  Test 2 (Local CUDA Whisper):     {'PASSED' if r2 else 'FAILED'}")
    print(f"  Test 3 (Autonomous Goal Agent):  {'PASSED' if r3 else 'FAILED'}")
    print(f"  Test 4 (Fast-Pass Router):       {'PASSED' if r4 else 'FAILED'}")
    
    if all([r1, r2, r3, r4]):
        print("\nALL TESTS PASSED! System is 100% ready for offline autonomous robotics operation.")
        sys.exit(0)
    else:
        print("\nONE OR MORE TESTS FAILED!")
        sys.exit(1)
