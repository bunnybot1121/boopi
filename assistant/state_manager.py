from event_bus import bus

STATES = ["idle", "listening", "thinking", "talking", "error"]

VALID_TRANSITIONS = {
    "idle":      ["listening"],
    "listening": ["thinking", "idle"],
    "thinking":  ["talking", "idle", "error"],
    "talking":   ["idle"],
    "error":     ["idle"],
}

class StateManager:
    def __init__(self):
        self.current = "idle"

    def transition(self, new_state: str):
        if new_state not in STATES:
            print(f"[StateManager] Unknown state: {new_state}")
            return
        if new_state not in VALID_TRANSITIONS.get(self.current, []):
            print(f"[StateManager] Invalid transition: {self.current} → {new_state}")
            return
        self.current = new_state
        bus.state_changed.emit(new_state)
        print(f"[State] {new_state.upper()}")

    def force(self, state: str):
        self.current = state
        bus.state_changed.emit(state)

state_mgr = StateManager()
