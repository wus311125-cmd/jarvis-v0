from collections import deque
from typing import List, Dict


class ConversationMemory:
    """FIFO per-user conversation buffer.

    Stores alternating user/assistant messages as dicts: {'role': 'user'|'assistant', 'content': str}
    """

    def __init__(self, max_turns: int = 10, max_chars: int = 4000):
        self.max_turns = max_turns
        # max_chars is soft cap for total characters across returned messages
        self.max_chars = max_chars
        # buffers keyed by user_id -> deque of messages
        self._buffers: Dict[str, deque] = {}

    def _get_buffer(self, user_id: str) -> deque:
        if user_id not in self._buffers:
            # each turn = user+assistant => maxlen = max_turns * 2
            self._buffers[user_id] = deque(maxlen=self.max_turns * 2)
        return self._buffers[user_id]

    def add_user_message(self, user_id: str, text: str):
        buf = self._get_buffer(user_id)
        buf.append({"role": "user", "content": text})

    def add_assistant_message(self, user_id: str, text: str):
        buf = self._get_buffer(user_id)
        buf.append({"role": "assistant", "content": text})

    def get_messages(self, user_id: str) -> List[Dict[str, str]]:
        """Return messages trimmed to max_chars (oldest removed first).

        Returns list of {'role','content'} ordered oldest->newest.
        """
        buf = self._get_buffer(user_id)
        messages = list(buf)
        total = sum(len(m.get("content", "")) for m in messages)
        # Trim oldest messages until under budget
        while messages and total > self.max_chars:
            removed = messages.pop(0)
            total -= len(removed.get("content", ""))
        return messages

    def clear(self, user_id: str):
        if user_id in self._buffers:
            self._buffers[user_id].clear()


# singleton instance for simple import
memory = ConversationMemory()
