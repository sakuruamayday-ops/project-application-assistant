"""Temporary workspace helper that never permanently deletes artifacts."""

import tempfile
from pathlib import Path


class PersistentTemporaryDirectory:
    """TemporaryDirectory-compatible context manager that retains its directory."""

    def __init__(self, suffix=None, prefix=None, dir=None, **_kwargs):
        self.name = tempfile.mkdtemp(suffix=suffix, prefix=prefix, dir=dir)

    def __enter__(self):
        return self.name

    def __exit__(self, exc_type, exc, tb):
        print(f"保留临时目录（未永久删除）: {Path(self.name)}")
        return False

    def cleanup(self):
        print(f"保留临时目录（未永久删除）: {Path(self.name)}")
