"""Persist and resume a provider's asynchronous patent search."""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Protocol
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "_runtime"))
from result_digest import digest


DEFAULT_REGISTRY = Path(__file__).resolve().parents[1] / "local-overrides" / ".async-search-tasks.json"
RETRYABLE_STATES = ("failed", "not_found")
TRANSPORT_ERRORS = (TimeoutError, ConnectionError)


class AsyncSearchProvider(Protocol):
    name: str

    def submit(self, query: str) -> str: ...

    def get_status(self, task_id: str) -> str: ...

    def resume(self, task_id: str, checkpoint: Path, progress: int) -> Iterator[int]:
        """Save results and their cursor to checkpoint before yielding each count."""
        ...


def registry_location(path: Path | None) -> Path:
    configured = os.environ.get("PATENT_ROUTER_ASYNC_REGISTRY")
    return Path(path or configured or DEFAULT_REGISTRY).expanduser().resolve()


@contextmanager
def locked_registry(path: Path):
    # Keep the lock on a separate file so replacing the registry preserves the lock.
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_name(path.name + ".lock").open("a+b") as lock:
        if os.name == "nt":
            import msvcrt

            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def load_tasks(path: Path) -> list[dict]:
    try:
        with path.open(encoding="utf-8") as source:
            tasks = json.load(source)["tasks"]
    except FileNotFoundError:
        return []
    if not isinstance(tasks, list):
        raise ValueError(f"Invalid async search registry: {path}")
    return tasks


def save_tasks(path: Path, tasks: list[dict]) -> None:
    with NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as output:
        temporary = Path(output.name)
        try:
            json.dump({"tasks": tasks}, output, ensure_ascii=False, indent=2)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
            output.close()
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)


def submit_attempt(provider, query, registry, tasks, request, previous=None) -> dict:
    record_id = uuid4().hex
    checkpoint = Path(request["checkpoint_path"])
    if previous is not None:
        original = Path(previous["checkpoint_path"])
        checkpoint = original.with_name(f"{original.stem}.{record_id}{original.suffix}")
    if checkpoint == registry or checkpoint.exists() or any(
        task["checkpoint_path"] == str(checkpoint) for task in tasks
    ):
        raise FileExistsError(f"Checkpoint path already in use: {checkpoint}")

    record = {
        **request,
        "record_id": record_id,
        "checkpoint_path": str(checkpoint),
        "remote_task_id": None,
        "progress": 0,
        "status": "unknown",
        "retry_of": previous["record_id"] if previous is not None else None,
    }
    # An interruption between remote acceptance and receipt leaves an unknown task.
    tasks.append(record)
    save_tasks(registry, tasks)
    try:
        task_id = provider.submit(query)
    except TRANSPORT_ERRORS:
        return record
    if isinstance(task_id, str) and task_id.strip():
        record.update(remote_task_id=task_id, status="submitted")
        save_tasks(registry, tasks)
    return record


def run_async_search(
    provider: AsyncSearchProvider,
    query: str,
    checkpoint: Path,
    *,
    scope: str,
    registry_path: Path | None = None,
    retry_authorized: bool = False,
) -> dict:
    if not isinstance(query, str) or not query.strip():
        raise ValueError("An asynchronous search requires a non-empty query")
    registry = registry_location(registry_path)
    identity = {"scope": scope, "provider": provider.name, "query_sha256": digest(query)}
    request = {**identity, "checkpoint_path": str(Path(checkpoint).expanduser().resolve())}

    with locked_registry(registry):
        tasks = load_tasks(registry)
        record = next(
            (task for task in reversed(tasks) if all(task[key] == value for key, value in identity.items())),
            None,
        )
        if record is None:
            return submit_attempt(provider, query, registry, tasks, request)
        task_id = record["remote_task_id"]
        checkpoint = Path(record["checkpoint_path"])
        if task_id is None or (record["status"] == "completed" and checkpoint.is_file()):
            return record

        try:
            status = provider.get_status(task_id)
            if status in ("running", "completed"):
                for progress in provider.resume(task_id, checkpoint, record["progress"]):
                    if type(progress) is not int or progress < record["progress"] or not checkpoint.is_file():
                        raise ValueError("Resume must save its checkpoint before yielding non-decreasing progress")
                    record["progress"] = progress
                    save_tasks(registry, tasks)
                if status == "completed" and not checkpoint.is_file():
                    raise ValueError("Completed search must have a saved checkpoint")
        except TRANSPORT_ERRORS:
            status = "unknown"

        if status not in ("queued", "running", "completed", *RETRYABLE_STATES):
            status = "unknown"
        record["status"] = status
        save_tasks(registry, tasks)
        if status in RETRYABLE_STATES and retry_authorized is True:
            return submit_attempt(provider, query, registry, tasks, request, previous=record)
        return record
