"""Small, process-local window for optional consecutive-draw comments."""
import time
from collections import OrderedDict, deque


class DrawActivity:
    WINDOW = 120
    MAX_USERS = 1024

    def __init__(self):
        self.users = OrderedDict()

    def record(self, user_id, interaction_id, now=None):
        now = time.monotonic() if now is None else now
        if user_id not in self.users:
            if len(self.users) >= self.MAX_USERS:
                self.users.popitem(last=False)
            self.users[user_id] = deque(maxlen=30)
        entries = self.users[user_id]
        self.users.move_to_end(user_id)
        while entries and now - entries[0][1] > self.WINDOW:
            entries.popleft()
        if not any(key == interaction_id for key, _ in entries):
            entries.append((interaction_id, now))
        return len(entries)
