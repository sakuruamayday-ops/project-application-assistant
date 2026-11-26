"""TemporaryDirectory-compatible helper that retains all work directories."""

import tempfile
from pathlib import Path


class PersistentTemporaryDirectory:
    def __init__(self, suffix=None, prefix=None, dir=None, **_kwargs):
        self.name = tempfile.mkdtemp(suffix=suffix, prefix=prefix, dir=dir)

    def __enter__(self):
        return self.name

    def __exit__(self, exc_type, exc, tb):
        print(f"Retained temporary directory: {Path(self.name)}", file=__import__("sys").stderr)
        return False

    def cleanup(self):
        print(f"Retained temporary directory: {Path(self.name)}", file=__import__("sys").stderr)
