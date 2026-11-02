"""One owning process per data directory, including during startup restore and migrations."""
import os
from contextlib import contextmanager
from pathlib import Path

from ..domain.errors import InvalidInput
from ..i18n import _

if os.name == "nt":
    import ctypes
    import msvcrt
    from ctypes import wintypes

    class _Overlapped(ctypes.Structure):
        _fields_ = [("Internal", ctypes.c_void_p), ("InternalHigh", ctypes.c_void_p),
                    ("Offset", wintypes.DWORD), ("OffsetHigh", wintypes.DWORD), ("hEvent", wintypes.HANDLE)]

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _kernel32.LockFileEx.argtypes = (wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
                                     ctypes.POINTER(_Overlapped))
    _kernel32.UnlockFileEx.argtypes = (wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
                                       ctypes.POINTER(_Overlapped))
    _EXCLUSIVE, _FAIL_IMMEDIATELY, _LOCK_VIOLATION = 0x2, 0x1, 33

    def _lock(stream, exclusive, wait=False):
        # Byte 0 of the lock file stands in for the whole library, like flock() on a file.
        flags = (_EXCLUSIVE if exclusive else 0) | (0 if wait else _FAIL_IMMEDIATELY)
        if not _kernel32.LockFileEx(msvcrt.get_osfhandle(stream.fileno()), flags, 0, 1, 0, ctypes.byref(_Overlapped())):
            error = ctypes.get_last_error()
            if error == _LOCK_VIOLATION:
                raise BlockingIOError(error, "library is locked")
            raise ctypes.WinError(error)

    def _unlock(stream):
        _kernel32.UnlockFileEx(msvcrt.get_osfhandle(stream.fileno()), 0, 1, 0, ctypes.byref(_Overlapped()))

    def downgrade_lock(stream):
        """Exclusive -> shared with no gap: a handle may hold both, and the first unlock drops the exclusive one."""
        _lock(stream, exclusive=False, wait=True)
        _unlock(stream)
else:
    import fcntl  # macOS and the Linux development shell

    def _lock(stream, exclusive, wait=False):
        fcntl.flock(stream.fileno(), (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | (0 if wait else fcntl.LOCK_NB))

    def _unlock(stream):
        fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

    def downgrade_lock(stream):
        """Exclusive -> shared; flock converts the lock in place."""
        fcntl.flock(stream.fileno(), fcntl.LOCK_SH)


class LibraryInUse(InvalidInput):
    """Another process owns the library: usually the app itself, opened a second time."""


@contextmanager
def library_lock(root: Path):
    root = root.resolve()
    root.parent.mkdir(parents=True, exist_ok=True)
    with root.with_name('.'+root.name+'.lock').open('a') as stream:
        try:
            _lock(stream, exclusive=True)
        except BlockingIOError as error:
            raise LibraryInUse(_("이 서재를 사용하는 앱이 이미 실행 중이에요. 먼저 앱을 종료해 주세요.")) from error
        try:
            yield
        finally:
            _unlock(stream)


@contextmanager
def library_access(root: Path, *, exclusive: bool = False):
    """Hold shared access for a process lifetime, or exclusive access while swapping directories."""
    root = root.resolve()
    root.parent.mkdir(parents=True, exist_ok=True)
    with root.with_name('.'+root.name+'.access.lock').open('a') as stream:
        try:
            _lock(stream, exclusive=exclusive)
        except BlockingIOError as error:
            raise InvalidInput(_("이 서재를 사용하는 앱이 이미 실행 중이에요. 먼저 앱을 종료해 주세요.")) from error
        try:
            yield stream
        finally:
            _unlock(stream)
