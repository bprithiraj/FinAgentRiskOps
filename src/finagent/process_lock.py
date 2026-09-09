import os


class ProcessLock:
    """Reject a second service process for the same SQLite data directory."""

    def __init__(self, path):
        self.file = path.open("a+b")
        if self.file.seek(0, 2) == 0:
            self.file.write(b"\0")
            self.file.flush()
        self.file.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.file.close()
            raise RuntimeError(
                "This data directory is already served. Run exactly one worker."
            ) from exc

    def close(self):
        self.file.close()
