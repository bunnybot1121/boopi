from event_bus import bus

STATES = ["idle", "listening", "thinking", "talking", "error", "happy", "angry", "startup", "praise", "excited", "booting", "chilling", "waiting", "typing", "sleeping", "confused", "surprised", "writing", "reading", "recording", "drinking_coffee", "concerned", "cautious", "celebrating"]

class StateManager:
    def __init__(self):
        self.current = "idle"

    def transition(self, new_state: str):
        if new_state not in STATES:
            print(f"[StateManager] Unknown state: {new_state}")
            return
        if self.current == new_state:
            return
        self.current = new_state
        bus.state_changed.emit(new_state)
        print(f"[State] {new_state.upper()}")

    def force(self, state: str):
        if self.current == state:
            return
        self.current = state
        bus.state_changed.emit(state)

state_mgr = StateManager()
