class StreamingManager:
    def __init__(self):
        self.sessions = {}

    def get(self, session_id: str):
        return self.sessions.get(session_id)

    def create(self, session_id: str):
        s = StreamingSession(session_id)
        self.sessions[session_id] = s
        return s
