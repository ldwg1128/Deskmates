"""Small persisted bread stacks; wall-clock decay also covers time offline."""
from dataclasses import dataclass
import math

BREAD_LIMIT = 5
DIGEST_SECONDS = 60.0
DIGEST_INTERVALS = (60, 180, 300)


def normalize_digest_seconds(value):
    return float(value) if type(value) in (int, float) and value in DIGEST_INTERVALS else DIGEST_SECONDS


@dataclass
class Appetite:
    stacks: int
    updated_at: float
    digest_seconds: float = DIGEST_SECONDS

    def __post_init__(self):
        self.digest_seconds = normalize_digest_seconds(self.digest_seconds)

    @classmethod
    def restore(cls, data, now, digest_seconds=DIGEST_SECONDS):
        if not isinstance(data, dict):
            return cls(0, now, digest_seconds)
        stacks = data.get("stacks", 0)
        timestamp = data.get("updated_at", now)
        if type(stacks) is not int:
            stacks = 0
        if (type(timestamp) not in (int, float) or timestamp < 0 or timestamp > now
                or not math.isfinite(timestamp)):
            timestamp = now
        appetite = cls(max(0, min(BREAD_LIMIT, stacks)), timestamp, digest_seconds)
        appetite.digest(now)
        return appetite

    def digest(self, now):
        if now < self.updated_at or not self.stacks:
            self.updated_at = now
            return False
        elapsed = int((now-self.updated_at)//self.digest_seconds)
        if not elapsed:
            return False
        self.stacks = max(0, self.stacks-elapsed)
        self.updated_at = self.updated_at+elapsed*self.digest_seconds if self.stacks else now
        return True

    def set_digest_seconds(self, seconds, now):
        seconds = normalize_digest_seconds(seconds)
        if seconds == self.digest_seconds:
            return
        self.digest(now)
        # Keep the current cycle's progress when switching presets. Switching
        # must neither instantly consume stacks nor restart the whole cycle.
        if self.stacks:
            progress = (now-self.updated_at)/self.digest_seconds
            self.updated_at = now-progress*seconds
        self.digest_seconds = seconds

    def eat(self, now):
        self.digest(now)
        if self.stacks >= BREAD_LIMIT:
            return False
        if not self.stacks:
            self.updated_at = now
        self.stacks += 1
        return True

    @property
    def label(self):
        if not self.stacks:
            return "배고픔"
        if self.stacks <= 2:
            return "보통"
        return "배부름" if self.stacks < BREAD_LIMIT else "너무 배부름"

    def as_dict(self):
        return {"stacks": self.stacks, "updated_at": self.updated_at}
