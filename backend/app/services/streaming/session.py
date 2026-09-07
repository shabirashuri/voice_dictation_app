class StreamingSession:
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.report_state = None

    def update_state(self, state):
        self.report_state = state
