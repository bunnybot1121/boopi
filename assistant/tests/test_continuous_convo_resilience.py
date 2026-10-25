import unittest
import os
import sys
import numpy as np
import time

class TestContinuousConvoResilience(unittest.TestCase):
    def test_01_speaker_interrupt_thread_safety(self):
        """Verifies that calling interrupt() repeatedly from any thread does not crash with PortAudio access violations."""
        from voice.speaker import SpeakerThread
        speaker = SpeakerThread()
        
        # Test rapid interrupts
        for _ in range(10):
            speaker.interrupt()
            self.assertFalse(speaker.is_playing())

    def test_02_analyze_sentiment_never_returns_startup(self):
        """Verifies that mid-conversation greetings/waving return 'happy', never 'startup'."""
        from main import analyze_sentiment
        
        test_phrases = [
            "Hey, how are you?",
            "Hello there!",
            "Hi Boopi!",
            "Goodbye for now!",
            "Welcome back!"
        ]
        for phrase in test_phrases:
            sentiment = analyze_sentiment(phrase)
            self.assertNotEqual(sentiment, "startup", f"Phrase '{phrase}' must not return 'startup' state!")

    def test_03_conversation_mode_retention_on_multi_turn(self):
        """Verifies that typical follow-up conversational utterances do not disable conversation mode."""
        import main
        
        main.conversation_mode = True
        
        follow_ups = [
            "how are you doing",
            "what's up",
            "can you hear me",
            "who are you",
            "tell me a joke",
            "what can you do"
        ]
        
        for text in follow_ups:
            main.on_transcription(text)
            self.assertTrue(main.conversation_mode, f"Turn '{text}' prematurely turned off conversation mode!")

    def test_04_listener_lazy_whisper_does_not_crash(self):
        """Verifies listener initializes without eager background whisper loading thread."""
        from voice.listener import ListenerThread
        listener = ListenerThread()
        self.assertIsNone(listener.whisper_model, "Whisper model must be lazily loaded, not eager at init.")
        self.assertFalse(listener.is_speaking)

if __name__ == "__main__":
    unittest.main()
