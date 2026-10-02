"""Observation-only scene selector and backend-independent write-ahead transactions."""
from dataclasses import dataclass
from typing import Protocol


def scene(*, screen_on: bool | None, interactive: bool | None,
          audio: bool | None, thermal: str | None):
    if thermal not in {'normal', 'warm', 'hot'} or None in (screen_on, interactive, audio):
        return 'unknown'
    if thermal == 'hot':
        return 'thermal_guard'
    if audio:
        return 'media'
    if not screen_on:
        return 'standby'
    return 'interactive' if interactive else 'balanced'


@dataclass(frozen=True)
class Change:
    key: str
    before: str
    after: str


class Store(Protocol):
    def read(self, key: str) -> str: ...
    def write(self, key: str, value: str) -> None: ...


class Journal(Protocol):
    # A production save must fsync/atomically publish before returning.
    def load(self) -> list[Change]: ...
    def save(self, changes: list[Change]) -> None: ...


class Transaction:
    """No sysfs backend exists. Test adapters supply an audited key/value allowlist.

    A real adapter needs exclusive ownership or CAS semantics to close read/write races.
    Restoring an overwritten value is deliberately blocked; unresolved entries survive.
    """
    def __init__(self, store: Store, journal: Journal, allowed: dict[str, frozenset[str]]):
        self.store, self.journal, self.allowed = store, journal, allowed

    def apply(self, desired: dict[str, str], *, enabled=False, dry_run=True):
        if self.journal.load():
            return 'pending_recovery'
        if any(k not in self.allowed or v not in self.allowed[k] for k, v in desired.items()):
            return 'unsupported'
        if enabled is not True or dry_run is not False:
            return 'observe_only'
        changes = []
        for key, value in desired.items():
            current = self.store.read(key)
            if current != value:
                changes.append(Change(key, current, value))
        if not changes:
            return 'unchanged'
        self.journal.save(changes)  # durable intent before the FIRST mutation
        try:
            for change in changes:
                if self.store.read(change.key) != change.before:
                    raise OSError('ownership changed before write')
                self.store.write(change.key, change.after)
                if self.store.read(change.key) != change.after:
                    raise OSError('readback mismatch')
        except OSError:
            return 'rolled_back' if self.restore() else 'recovery_required'
        return 'applied'

    def restore(self):
        pending = self.journal.load()
        remaining = list(pending)
        for change in reversed(pending):
            try:
                current = self.store.read(change.key)
                if current == change.before:
                    remaining.remove(change)
                elif current == change.after:
                    self.store.write(change.key, change.before)
                    if self.store.read(change.key) == change.before:
                        remaining.remove(change)
                # A different value belongs to an unknown actor; never overwrite it.
            except OSError:
                pass
        self.journal.save(remaining)
        return not remaining
