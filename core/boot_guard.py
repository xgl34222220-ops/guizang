"""Host reference for a single-module boot guard; not installed on Android.

State is transactionally persisted, locked and scoped to one caller-owned directory.
No boot partition, other module, device setting or application data is accessed.
"""
import fcntl
import json
import os
from pathlib import Path
import tempfile
from contextlib import contextmanager


class BootGuard:
    def __init__(self, directory: Path, failure_limit=3):
        if not 2 <= failure_limit <= 5:
            raise ValueError('failure limit must be 2..5')
        self.directory = directory
        self.limit = failure_limit
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)

    @contextmanager
    def lock(self):
        fd = os.open(self.directory / 'lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            os.close(fd)

    def _load(self):
        path = self.directory / 'state.json'
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(fd) as stream:
                state = json.load(stream)
            if (set(state) != {'schema', 'boot', 'status', 'failures', 'disabled'}
                    or state['schema'] != 1 or not isinstance(state['boot'], str)
                    or state['status'] not in {'pending', 'healthy', 'failed'}
                    or type(state['failures']) is not int or not 0 <= state['failures'] <= 5
                    or type(state['disabled']) is not bool):
                raise ValueError('invalid schema')
            return state
        except FileNotFoundError:
            return dict(schema=1, boot='', status='healthy', failures=0, disabled=False)
        except (ValueError, TypeError, OSError):
            # Corruption fails closed, rather than deleting evidence or re-enabling.
            return dict(schema=1, boot='', status='failed', failures=self.limit, disabled=True)

    def _save(self, state):
        fd, name = tempfile.mkstemp(prefix='.state-', dir=self.directory)
        try:
            with os.fdopen(fd, 'w') as stream:
                json.dump(state, stream, sort_keys=True)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, self.directory / 'state.json')
            directory_fd = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            if os.path.exists(name):
                os.unlink(name)

    def begin(self, boot_id):
        if not isinstance(boot_id, str) or not boot_id or len(boot_id) > 128:
            raise ValueError('invalid boot identity')
        with self.lock():
            state = self._load()
            if state['disabled'] or state['boot'] == boot_id:
                return state
            if state['status'] == 'pending':
                state['failures'] += 1
            state.update(boot=boot_id, status='pending')
            state['disabled'] = state['failures'] >= self.limit
            self._save(state)
            return state

    def finish(self, boot_id, *, healthy):
        if type(healthy) is not bool:
            raise ValueError('healthy must be a boolean')
        with self.lock():
            state = self._load()
            if state['disabled'] or state['boot'] != boot_id or state['status'] != 'pending':
                return state
            state['status'] = 'healthy' if healthy else 'failed'
            state['failures'] = 0 if healthy else min(self.limit, state['failures'] + 1)
            state['disabled'] = state['failures'] >= self.limit
            self._save(state)
            return state
