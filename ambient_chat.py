"""Bounded channel context and conservative participation gates."""
import time
from collections import OrderedDict, deque
from dataclasses import dataclass, field

COOLDOWN = 30 * 60
PARTICIPATION_CHANCE = 0.05
CONTEXT_TTL = 5 * 60
SKIP = "__SKIP__"
SERIOUS = ("相談", "真剣", "深刻", "つらい", "辛い", "死", "病", "事故", "災害", "訃報", "助けて", "喧嘩", "けんか", "仕事", "政治", "戦争")


@dataclass
class ChannelState:
    messages: deque = field(default_factory=lambda: deque(maxlen=8))
    next_attempt: float = 0
    busy: bool = False


class AmbientChat:
    def __init__(self):
        self.states = OrderedDict()

    def observe(self, channel_id, author_id, text, directed=False, now=None):
        now = time.monotonic() if now is None else now
        if channel_id not in self.states:
            if len(self.states) >= 128:
                for old_id, state in list(self.states.items()):
                    if not state.busy:
                        del self.states[old_id]
                        break
                else:
                    return None
            self.states[channel_id] = ChannelState()
        state = self.states[channel_id]
        self.states.move_to_end(channel_id)
        while state.messages and now - state.messages[0][0] > CONTEXT_TTL:
            state.messages.popleft()
        if directed or not text.strip() or text.startswith(("/", "!", "?")):
            state.messages.clear()
            return None
        state.messages.append((now, author_id, text[:500]))
        if state.busy or now < state.next_attempt:
            return None
        if len(state.messages) < 3 or len({m[1] for m in state.messages}) < 2:
            return None
        if any(word in m[2] for m in state.messages for word in SERIOUS):
            return None
        return state

    def reserve(self, state, now=None):
        state.busy = True
        state.next_attempt = (time.monotonic() if now is None else now) + COOLDOWN

    def note_reply(self, channel_id):
        state = self.states.get(channel_id)
        if state:
            state.next_attempt = time.monotonic() + COOLDOWN
            state.messages.clear()

    def still_current(self, channel_id, state):
        return self.states.get(channel_id) is state
