import os
from dotenv import load_dotenv
from logger import log

# Load environment variables
dotenv_path = os.path.join(os.path.dirname(__file__), '.env')
if os.path.exists(dotenv_path):
  load_dotenv(dotenv_path)
  log.info("Loaded configuration from .env file.")
else:
  log.warning("No .env file found, using system environment variables.")

# Provider settings
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "gemini").lower()
GROQ_LLM_MODEL = os.getenv("GROQ_LLM_MODEL", "qwen/qwen3.6-27b")
OPENROUTER_LLM_MODEL = os.getenv("OPENROUTER_LLM_MODEL", "google/gemini-3.6-flash")

# Cloud Keys
GOOGLE_AI_STUDIO_KEY = os.getenv("GOOGLE_AI_STUDIO_KEY", "")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
HF_TOKEN = os.getenv("HF_TOKEN", "")
HF_MODEL = os.getenv("HF_MODEL", "Qwen/Qwen2.5-72B-Instruct")
CALENDAR_API_KEY = os.getenv("CALENDAR_API_KEY", "")

# Expose HF_TOKEN to environment variables for huggingface hub authentication
if HF_TOKEN:
  os.environ["HF_TOKEN"] = HF_TOKEN
  os.environ["HUGGINGFACE_CO_API_KEY"] = HF_TOKEN

# Local model settings
USE_LOCAL_LLM = os.getenv("USE_LOCAL_LLM", "false").lower() == "true"
LOCAL_LLM_URL = os.getenv("LOCAL_LLM_URL", "http://127.0.0.1:11434")
LOCAL_LLM_MODEL = os.getenv("LOCAL_LLM_MODEL", "llama3.2:latest")
LOCAL_VISION_LLM_MODEL = os.getenv("LOCAL_VISION_LLM_MODEL", "qwen2.5vl:3b")

# Mic and speech processing settings
VAD_AGGRESSIVENESS = int(os.getenv("VAD_AGGRESSIVENESS", "3"))
MICROPHONE_CALIBRATION_SEC = float(os.getenv("MICROPHONE_CALIBRATION_SEC", "1.0"))
AUDIO_GAIN_BOOST = float(os.getenv("AUDIO_GAIN_BOOST", "1.5"))

# TTS Voice Setting
TTS_VOICE = os.getenv("TTS_VOICE", "en-US-AnaNeural")

# Speech Emotion classification setting (Optional, disable by default for latency optimization)
ENABLE_SPEECH_EMOTION = os.getenv("ENABLE_SPEECH_EMOTION", "false").lower() == "true"

# ElevenLabs Settings (Optional)
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "")
ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "EXAVITQu4vr4xnSDxMaL")

# STT Settings
USE_CLOUD_STT = os.getenv("USE_CLOUD_STT", "true").lower() == "true"
LOCAL_WHISPER_MODEL = os.getenv("LOCAL_WHISPER_MODEL", "base.en")
GROQ_STT_MODEL = os.getenv("GROQ_STT_MODEL", "whisper-large-v3")
SILENCE_FRAMES = int(os.getenv("SILENCE_FRAMES", "12"))


def validate_config():
  """Checks if required keys are present for the chosen provider."""
  if LLM_PROVIDER == "gemini" and not GOOGLE_AI_STUDIO_KEY:
    log.warning("GOOGLE_AI_STUDIO_KEY is missing! Gemini commands will fail.")
  elif LLM_PROVIDER == "groq" and not GROQ_API_KEY:
    log.warning("GROQ_API_KEY is missing! Groq commands will fail.")
  elif LLM_PROVIDER == "openrouter" and not OPENROUTER_API_KEY:
    log.warning("OPENROUTER_API_KEY is missing! OpenRouter commands will fail.")
  elif LLM_PROVIDER == "huggingface" and not HF_TOKEN:
    log.warning("HF_TOKEN is missing! Hugging Face commands will fail.")

validate_config()
