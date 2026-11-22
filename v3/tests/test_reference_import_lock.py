"""The Windows byte-range lock must not race during empty-file creation."""
import os
from pathlib import Path
from threading import Barrier, Event, Lock, Thread, current_thread

import pytest

from anima_prompt_studio_v3.storage.reference_import import _import_lock


@pytest.mark.skipif(os.name != "nt", reason="Windows byte-range locking semantics")
def test_concurrent_empty_lock_initialization_cannot_write_under_another_holder(tmp_path, monkeypatch):
    import msvcrt

    lock_path = tmp_path / "reference-import.lock"
    both_saw_empty, first_entered, second_attempted = Barrier(2), Event(), Event()
    original_open, original_locking = Path.open, msvcrt.locking

    class Stream:
        def __init__(self, stream):
            self.stream, self.first_tell = stream, True
        def __getattr__(self, name): return getattr(self.stream, name)
        def __enter__(self): return self
        def __exit__(self, *args): return self.stream.__exit__(*args)
        def tell(self):
            value = self.stream.tell()
            if self.first_tell:
                self.first_tell = False
                assert value == 0
                both_saw_empty.wait(2)
                if current_thread().name == "second":
                    assert first_entered.wait(2)
            return value

    def opened(path, *args, **kwargs):
        stream = original_open(path, *args, **kwargs)
        return Stream(stream) if path == lock_path else stream

    def locking(fd, mode, size):
        if mode == msvcrt.LK_NBLCK and current_thread().name == "second":
            assert first_entered.wait(2)
            second_attempted.set()
        return original_locking(fd, mode, size)

    monkeypatch.setattr(Path, "open", opened)
    monkeypatch.setattr(msvcrt, "locking", locking)
    errors, entries = [], []
    guard = Lock()
    active = maximum = 0

    def run():
        nonlocal active, maximum
        try:
            with _import_lock(tmp_path / "examples.db"):
                with guard:
                    active += 1
                    maximum = max(maximum, active)
                    entries.append(current_thread().name)
                if current_thread().name == "first":
                    first_entered.set()
                    # Old code fails while flushing initialization, before its
                    # first lock attempt; still release the successful holder.
                    second_attempted.wait(.3)
                with guard: active -= 1
        except BaseException as exc:
            errors.append(exc)

    threads = [Thread(target=run, name=name) for name in ("first", "second")]
    for thread in threads: thread.start()
    for thread in threads: thread.join(3)
    assert not any(thread.is_alive() for thread in threads)
    assert not errors
    assert entries == ["first", "second"] and maximum == 1
    assert lock_path.stat().st_size == 0
