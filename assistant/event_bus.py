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

class HackathonEventBus:
    def emit(self, event_name, *args, **kwargs):
        import json
        if event_name == 'speak':
            print(json.dumps({"type": "speak", "value": args[0]}), flush=True)
        elif event_name == 'set_state':
            print(json.dumps({"type": "state", "value": args[0]}), flush=True)

event_bus = HackathonEventBus()
