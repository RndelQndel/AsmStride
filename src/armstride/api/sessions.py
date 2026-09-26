"""Bounded ephemeral sessions with per-session serialization and idle cleanup."""

from contextlib import contextmanager
from dataclasses import dataclass, field
from secrets import token_urlsafe
from threading import Event, Lock
from time import monotonic

from armstride.domain.models import DomainError
from armstride.simulation import SimulationSession

MAX_SESSIONS = 8
IDLE_SECONDS = 30 * 60


@dataclass
class SessionEntry:
    session: SimulationSession
    last_access: float
    lock: object = field(default_factory=Lock)
    users: int = 0
    stack: dict | None = None
    stop_event: Event = field(default_factory=Event)


class SessionRegistry:
    def __init__(self, session_factory=SimulationSession, *, clock=monotonic):
        self._factory = session_factory
        self._clock = clock
        self._entries = {}
        self._lock = Lock()
        self._closed = False

    def create(self):
        self.sweep()
        with self._lock:
            if self._closed:
                raise DomainError('backend_unavailable', 'The application is shutting down.')
            if len(self._entries) >= MAX_SESSIONS:
                raise DomainError('session_limit', 'Close a session before creating another.', limit=MAX_SESSIONS)
            session_id = token_urlsafe(24)
            self._entries[session_id] = SessionEntry(self._factory(), self._clock())
            return session_id

    def signal_stop(self, session_id: str) -> bool:
        with self._lock:
            entry = self._entries.get(session_id)
            if entry is None:
                raise DomainError('session_not_found', 'Session missing or expired. Create a new session.')
            entry.stop_event.set()
            return True

    @contextmanager
    def access(self, session_id):
        self.sweep()
        with self._lock:
            entry = self._entries.get(session_id)
            if entry is None:
                raise DomainError('session_not_found', 'Session missing or expired. Create a new session.')
            # Queued operations count as active, so expiry cannot overtake them.
            entry.users += 1
        try:
            with entry.lock:
                with self._lock:
                    if self._entries.get(session_id) is not entry:
                        raise DomainError('session_not_found', 'Session has been deleted.')
                yield entry
        finally:
            with self._lock:
                entry.users -= 1
                entry.last_access = self._clock()

    def delete(self, session_id):
        with self.access(session_id) as entry:
            with self._lock:
                self._entries.pop(session_id, None)
            entry.session.close()

    def sweep(self):
        with self._lock:
            now = self._clock()
            expired = [key for key, entry in self._entries.items()
                       if entry.users == 0 and now - entry.last_access >= IDLE_SECONDS]
            entries = [self._entries.pop(key) for key in expired]
        for entry in entries:
            entry.session.close()

    def close(self):
        with self._lock:
            self._closed = True
            entries = list(self._entries.values())
            self._entries.clear()
        for entry in entries:
            with entry.lock:
                entry.session.close()
