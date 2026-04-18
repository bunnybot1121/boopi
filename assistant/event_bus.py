from PyQt6.QtCore import QObject, pyqtSignal

class EventBus(QObject):
    state_changed     = pyqtSignal(str)
    show_message      = pyqtSignal(str)
    speech_captured   = pyqtSignal(str)
    ai_response_ready = pyqtSignal(str)
    tts_started       = pyqtSignal()
    tts_finished      = pyqtSignal()
    action_detected   = pyqtSignal(str, str)

bus = EventBus()
