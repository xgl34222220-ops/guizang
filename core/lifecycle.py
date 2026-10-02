"""Serialized policy/state-machine reference; adapters in this build are tests only."""
from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol


@dataclass(frozen=True)
class Identity:
    package: str
    uid: int
    pid: int
    starttime: int
    boot_id: str

    def valid(self):
        # First release deliberately rejects shared, isolated and secondary-user UIDs.
        return (10000 <= self.uid < 20000 and self.pid > 1 and self.starttime > 0
                and bool(self.boot_id) and len(self.package.split('.')) >= 2
                and all(p and p.replace('_', '').isalnum() for p in self.package.split('.')))


@dataclass(frozen=True)
class Protection:
    # None means unavailable/stale, never "safe".
    foreground: bool | None = None
    visible: bool | None = None
    foreground_service: bool | None = None
    audio: bool | None = None
    recording: bool | None = None
    call: bool | None = None
    ime: bool | None = None
    accessibility: bool | None = None
    vpn: bool | None = None
    system: bool | None = None
    device_admin: bool | None = None
    shared_uid: bool | None = None
    binder_dependency: bool | None = None
    file_lock: bool | None = None

    def reason(self):
        for name, value in vars(self).items():
            if value is None:
                return 'unknown:' + name
            if value is not False:
                return 'protected:' + name
        return ''


@dataclass(frozen=True)
class Capabilities:
    cgroup_v2_freezer: bool = False
    binder_coordinator: bool = False
    framework_lifecycle: bool = False
    verified_thaw: bool = False

    def ready(self):
        return all(v is True for v in vars(self).values())


@dataclass(frozen=True)
class Config:
    enabled: bool = False
    dry_run: bool = True
    allowlist: frozenset[str] = field(default_factory=frozenset)
    grace_ms: int = 10000


class Phase(str, Enum):
    OBSERVED = 'observed'
    ELIGIBLE = 'eligible'
    FREEZE_PENDING = 'freeze_pending'
    FROZEN = 'frozen'
    THAW_PENDING = 'thaw_pending'
    DEGRADED = 'degraded'


class Backend(Protocol):
    """Each operation must revalidate Identity atomically (e.g. pidfd), not just PID.

    The host model's checks are additional defenses, not a TOCTOU solution.
    A production implementation also needs a durable freeze ledger/watchdog.
    """
    def identity(self, pid: int) -> Identity | None: ...
    def freeze(self, identity: Identity) -> bool: ...
    def thaw(self, identity: Identity) -> bool: ...
    def is_frozen(self, identity: Identity) -> bool: ...


class Freezer:
    def __init__(self, backend: Backend, config=Config(), capabilities=Capabilities()):
        self.backend, self.config, self.capabilities = backend, config, capabilities
        self.phase = Phase.OBSERVED
        self.owned: set[Identity] = set()
        self.reason = 'disabled'
        self.blocked = False

    def _result(self, reason):
        self.reason = reason
        return reason

    def consider(self, identity: Identity, protection: Protection, background_ms: int):
        if self.blocked:
            return self._result('degraded')
        if self.config.enabled is not True:
            if self.owned:
                self.thaw_all()
            return self._result('disabled')
        if not identity.valid():
            return self._result('invalid_identity')
        if identity.package not in self.config.allowlist:
            if identity in self.owned:
                self.thaw_all()
            return self._result('not_allowlisted')
        reason = protection.reason()
        if reason:
            if identity in self.owned:
                self.thaw_all()
            return self._result(reason)
        if background_ms < max(10000, self.config.grace_ms):
            return self._result('grace_period')
        if not self.capabilities.ready():
            if self.owned:
                self.thaw_all()
            return self._result('capability_unverified')
        if identity in self.owned:
            return self._result('already_owned')
        try:
            if self.backend.identity(identity.pid) != identity:
                return self._result('identity_changed')
            # Never take ownership of a process frozen by another actor.
            observed = self.backend.is_frozen(identity)
            if type(observed) is not bool:
                raise OSError('freeze state unknown')
            if observed:
                return self._result('externally_frozen')
        except OSError:
            if self.owned:
                self.thaw_all()
            self.blocked = True
            self.phase = Phase.DEGRADED
            return self._result('observation_failed')
        self.phase = Phase.ELIGIBLE
        if self.config.dry_run is not False:
            return self._result('would_freeze')
        self.phase = Phase.FREEZE_PENDING
        self.owned.add(identity)  # retain on ambiguous failure for compensation
        try:
            success = self.backend.freeze(identity)
            if self.backend.identity(identity.pid) != identity:
                success = False
            if success is True and self.backend.is_frozen(identity) is True:
                self.phase = Phase.FROZEN
                return self._result('frozen')
        except OSError:
            pass
        self.thaw_all()
        self.phase = Phase.DEGRADED
        self.blocked = True
        return self._result('freeze_failed')

    def thaw_all(self):
        self.phase = Phase.THAW_PENDING
        for identity in tuple(self.owned):
            try:
                current = self.backend.identity(identity.pid)
                if current != identity:
                    # Gone/reused PID: never thaw an unrelated new process.
                    self.owned.remove(identity)
                    continue
                if self.backend.is_frozen(identity) is False:
                    self.owned.remove(identity)
                    continue
                if self.backend.thaw(identity) is True and self.backend.is_frozen(identity) is False:
                    self.owned.remove(identity)
            except OSError:
                pass
        self.blocked = self.blocked or bool(self.owned)
        self.phase = Phase.DEGRADED if self.blocked else Phase.OBSERVED
        return self._result('thaw_failed' if self.owned else 'thawed')

    def safety_signal(self, identity: Identity, protection: Protection):
        if identity in self.owned and protection.reason():
            return self.thaw_all()
        return self._result('unchanged')

    def stop(self):
        self.config = Config()
        return self.thaw_all()
