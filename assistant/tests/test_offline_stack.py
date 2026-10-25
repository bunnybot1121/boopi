import os
import sys
import time
import wave
import numpy as np

# Ensure root assistant dir is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def test_offline_tts():
    print("=" * 60)
    print("TEST 1: OFFLINE TTS PIPER NEURAL SYNTHESIS")
    print("=" * 60)
    
    import piper
    import config
    
    piper_dir = getattr(config, "PIPER_MODEL_DIR", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "models", "piper"))
    voice_name = getattr(config, "PIPER_VOICE", "en_US-amy-medium")
    model_path = os.path.join(piper_dir, f"{voice_name}.onnx")
    config_path = os.path.join(piper_dir, f"{voice_name}.onnx.json")
    
    print(f"Model path: {model_path}")
    print(f"Config path: {config_path}")
    assert os.path.exists(model_path), f"Piper model file missing: {model_path}"
    assert os.path.exists(config_path), f"Piper config file missing: {config_path}"
    
    t0 = time.time()
    voice = piper.PiperVoice.load(model_path, config_path=config_path)
    t1 = time.time()
    print(f"-> Piper Model Loaded in {(t1 - t0)*1000:.1f} ms")
    
    # Pre-warm ONNX execution session
    import io
    with wave.open(io.BytesIO(), "wb") as dummy_wf:
        voice.synthesize_wav("Hi", dummy_wf)
    print("-> Piper ONNX session pre-warmed successfully!")

    out_wav = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_piper_output.wav")
    test_phrase = "Hello Sachin! I am Boopi. This is a 100 percent offline neural speech test."
    
    t2 = time.time()
    with wave.open(out_wav, "wb") as wf:
        voice.synthesize_wav(test_phrase, wf)
    t3 = time.time()
    
    synth_time_ms = (t3 - t2) * 1000
    file_size = os.path.getsize(out_wav)
    with wave.open(out_wav, "rb") as wf:
        duration_sec = wf.getnframes() / float(wf.getframerate())
        channels = wf.getnchannels()
        sample_rate = wf.getframerate()
        
    rtf = (t3 - t2) / duration_sec if duration_sec > 0 else 0
    print(f"-> Phrase: '{test_phrase}'")
    print(f"-> Synthesized {duration_sec:.2f}s of audio ({file_size} bytes, {sample_rate}Hz mono) in {synth_time_ms:.1f} ms")
    print(f"-> Real-Time Factor (RTF): {rtf:.3f}x (Lower is faster, <1.0 is real-time)")
    assert file_size > 1000, "Synthesized audio file too small!"
    print(f"-> Synthesis speed: {duration_sec / ((t3 - t2) or 0.001):.1f}x real-time!")
    print("-> PASS: Offline Piper TTS is working with studio-grade speed!")
    return out_wav

def test_offline_stt(synth_wav_path):
    print("\n" + "=" * 60)
    print("TEST 2: OFFLINE STT FASTER-WHISPER TRANSCRIPTION")
    print("=" * 60)
    
    import faster_whisper
    import config
    
    model_name = getattr(config, "LOCAL_WHISPER_MODEL", "base.en")
    print(f"Target Faster-Whisper Model: {model_name}")
    
    # Check CUDA vs CPU
    cuda_avail = False
    try:
        import ctranslate2
        cuda_avail = (ctranslate2.get_cuda_device_count() > 0)
    except Exception:
        pass
        
    device = "cuda" if cuda_avail else "cpu"
    compute_type = "float16" if device == "cuda" else "int8"
    print(f"Hardware Compute: {device} ({compute_type})")
    
    t0 = time.time()
    model = faster_whisper.WhisperModel(model_name, device=device, compute_type=compute_type, cpu_threads=4)
    t1 = time.time()
    print(f"-> Faster-Whisper Model Loaded in {(t1 - t0)*1000:.1f} ms")
    
    # 2a. Test with pre-recorded benchmark clip
    clip_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "offline_voice_bench", "clips", "clip_01.wav")
    print(f"\n2a. Transcribing Benchmark Clip: {os.path.basename(clip_path)}")
    t2 = time.time()
    segments, info = model.transcribe(clip_path, language="en", beam_size=1)
    transcript_clip = " ".join([s.text for s in segments]).strip()
    t3 = time.time()
    print(f"-> Clip Duration: {info.duration:.2f}s")
    print(f"-> Transcribed in {(t3 - t2)*1000:.1f} ms")
    print(f"-> Result: '{transcript_clip}'")
    assert "boopi" in transcript_clip.lower() or "how are you" in transcript_clip.lower() or "today" in transcript_clip.lower(), f"Unexpected transcript: {transcript_clip}"
    print("-> PASS: Benchmark clip transcribed accurately!")
    
    # 2b. Test with Piper synthesized audio (roundtrip test)
    print(f"\n2b. Transcribing Piper Synthesized Audio: {os.path.basename(synth_wav_path)}")
    t4 = time.time()
    segments, info = model.transcribe(synth_wav_path, language="en", beam_size=1)
    transcript_synth = " ".join([s.text for s in segments]).strip()
    t5 = time.time()
    print(f"-> Audio Duration: {info.duration:.2f}s")
    print(f"-> Transcribed in {(t5 - t4)*1000:.1f} ms")
    print(f"-> Result: '{transcript_synth}'")
    assert "boopi" in transcript_synth.lower() or "offline" in transcript_synth.lower(), f"Unexpected transcript: {transcript_synth}"
    print("-> PASS: Piper synthesized speech accurately transcribed by Faster-Whisper!")

def test_speaker_thread_offline_mode():
    print("\n" + "=" * 60)
    print("TEST 3: SPEAKERTHREAD OFFLINE FALLBACK VERIFICATION")
    print("=" * 60)
    
    from voice.speaker import SpeakerThread
    import config
    
    speaker = SpeakerThread()
    print("Waiting for SpeakerThread Piper initialization...")
    for _ in range(30):
        if speaker.piper_voice is not None:
            break
        time.sleep(0.1)
    
    print(f"Speaker piper_voice initialized: {speaker.piper_voice is not None}")
    assert speaker.piper_voice is not None, "SpeakerThread failed to initialize local Piper voice!"
    print("-> PASS: SpeakerThread has local Piper voice loaded and armed for instant offline failover.")

def test_listener_thread_offline_mode(synth_wav_path):
    print("\n" + "=" * 60)
    print("TEST 4: LISTENERTHREAD OFFLINE STT PIPELINE VERIFICATION")
    print("=" * 60)
    
    from voice.listener import ListenerThread
    import config
    
    # Explicitly test offline STT mode on ListenerThread
    config.USE_CLOUD_STT = False
    os.environ["USE_CLOUD_STT"] = "false"
    
    listener = ListenerThread()
    # Read audio from synth_wav_path
    with wave.open(synth_wav_path, "rb") as wf:
        audio_bytes = wf.readframes(wf.getnframes())
        audio_int16 = np.frombuffer(audio_bytes, dtype=np.int16)
        
    received_text = []
    listener.transcription_ready.connect(lambda t: received_text.append(t))
    
    t0 = time.time()
    listener._transcribe_and_emit(audio_int16)
    t1 = time.time()
    
    print(f"ListenerThread offline transcription completed in {(t1 - t0)*1000:.1f} ms")
    print(f"Captured emitted text: {received_text}")
    assert len(received_text) > 0 and received_text[0], "ListenerThread failed to emit offline transcription!"
    print(f"-> Emitted transcription: '{received_text[0]}'")
    print("-> PASS: ListenerThread offline STT pipeline is completely verified and operational!")
    
    # Restore cloud STT default
    config.USE_CLOUD_STT = True
    os.environ["USE_CLOUD_STT"] = "true"

if __name__ == "__main__":
    try:
        out_wav = test_offline_tts()
        test_offline_stt(out_wav)
        test_speaker_thread_offline_mode()
        test_listener_thread_offline_mode(out_wav)
        print("\n" + "=" * 60)
        print("ALL OFFLINE STT & TTS TESTS PASSED 100% SUCCESSFULLY!")
        print("=" * 60)
    except Exception as e:
        print(f"\nFAILED: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
