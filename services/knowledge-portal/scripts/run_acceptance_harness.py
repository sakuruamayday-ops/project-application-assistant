from __future__ import annotations

import argparse
import csv
import glob
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Mapping, Sequence

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from app.acceptance_harness import AcceptanceHarness


DEFAULT_PROFILE = (
    BASE_DIR / "references" / "acceptance-harness" / "knowledge-base.json"
)
INDEX_BUILDER = BASE_DIR / "scripts" / "build_knowledge_content_index.py"
INVENTORY_BUILDER = (
    BASE_DIR / "scripts" / "build_knowledge_inventory_from_manifest.py"
)
ALLOWLIST_BUILDER = BASE_DIR / "scripts" / "build_cloud_upload_allowlist.py"
POLICY_VERSION_BUILDER = BASE_DIR / "scripts" / "build_policy_version_links.py"
HARNESS_RUNNER = Path(__file__).resolve()
HARNESS_ENGINE = BASE_DIR / "app" / "acceptance_harness.py"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="运行焦糖统一验收 Harness 的指定场景套件"
    )
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE)
    parser.add_argument(
        "--knowledge-root",
        type=Path,
        default=Path("/Users/zsh/JiaotangData/知识库"),
    )
    parser.add_argument(
        "--index-root",
        type=Path,
        default=Path("/Users/zsh/JiaotangData/索引/current"),
    )
    parser.add_argument("--suite", action="append", default=[])
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def context_path(context: Mapping[str, object], key: str) -> Path:
    value = context.get(key)
    if not value:
        raise ValueError(f"missing harness context path: {key}")
    return Path(str(value)).expanduser().resolve()


def path_glob_count(
    config: Mapping[str, object],
    context: Mapping[str, object],
) -> tuple[bool, object, Sequence[str]]:
    root = context_path(context, str(config.get("root_key") or "knowledge_root"))
    pattern = str(config.get("pattern") or "")
    kind = str(config.get("kind") or "any")
    matches = [
        Path(path)
        for path in glob.glob(str(root / pattern), recursive=True)
        if (
            kind == "any"
            or (kind == "file" and Path(path).is_file())
            or (kind == "directory" and Path(path).is_dir())
        )
    ]
    minimum = int(config.get("min_count", 0))
    maximum = int(config.get("max_count", 2**31 - 1))
    relative = sorted(
        str(path.relative_to(root))
        for path in matches
        if path != root
    )
    passed = minimum <= len(relative) <= maximum
    return (
        passed,
        {"count": len(relative), "minimum": minimum, "maximum": maximum},
        relative[:20],
    )


def load_manifest(path: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def manifest_records(
    config: Mapping[str, object],
    context: Mapping[str, object],
) -> tuple[bool, object, Sequence[str]]:
    index_root = context_path(context, "index_root")
    manifest = context_path(
        context,
        str(config.get("manifest_context_key") or "manifest_path"),
    )
    if not manifest.is_file():
        manifest = index_root / "manifest.jsonl"
    pattern = re.compile(str(config.get("path_regex") or ".*"))
    selected = [
        row
        for row in load_manifest(manifest)
        if pattern.search(str(row.get("relative_path") or ""))
    ]
    expected = config.get("expected_fields", {})
    if not isinstance(expected, Mapping):
        raise ValueError("expected_fields must be an object")
    violations = [
        row
        for row in selected
        if any(row.get(field) != value for field, value in expected.items())
    ]
    minimum = int(config.get("min_count", 0))
    maximum_violations = int(config.get("max_violations", 0))
    passed = len(selected) >= minimum and len(violations) <= maximum_violations
    evidence = [
        f"{row.get('relative_path')} | "
        + ", ".join(
            f"{field}={row.get(field)!r} expected={value!r}"
            for field, value in expected.items()
            if row.get(field) != value
        )
        for row in violations[:20]
    ]
    return (
        passed,
        {
            "matched_records": len(selected),
            "minimum": minimum,
            "violations": len(violations),
            "maximum_violations": maximum_violations,
        },
        evidence,
    )


def csv_records(
    config: Mapping[str, object],
    context: Mapping[str, object],
) -> tuple[bool, object, Sequence[str]]:
    index_root = context_path(context, "index_root")
    path = index_root / str(config.get("path") or "")
    with path.open(encoding="utf-8-sig", newline="") as source:
        rows = list(csv.DictReader(source))
    where_field = str(config.get("where_field") or "")
    where_values = {
        str(value) for value in config.get("where_in", [])
    }
    selected = [
        row
        for row in rows
        if not where_field or str(row.get(where_field) or "") in where_values
    ]
    expected = config.get("expected_fields", {})
    if not isinstance(expected, Mapping):
        raise ValueError("expected_fields must be an object")
    violations = [
        row
        for row in selected
        if any(str(row.get(field) or "") != str(value) for field, value in expected.items())
    ]
    minimum = int(config.get("min_count", 0))
    maximum_violations = int(config.get("max_violations", 0))
    passed = len(selected) >= minimum and len(violations) <= maximum_violations
    return (
        passed,
        {
            "matched_records": len(selected),
            "minimum": minimum,
            "violations": len(violations),
            "maximum_violations": maximum_violations,
        },
        [
            f"{row.get('relative_path')} | "
            + ", ".join(
                f"{field}={row.get(field)!r} expected={value!r}"
                for field, value in expected.items()
                if str(row.get(field) or "") != str(value)
            )
            for row in violations[:20]
        ],
    )


def sqlite_rows(
    config: Mapping[str, object],
    context: Mapping[str, object],
) -> tuple[bool, object, Sequence[str]]:
    index_root = context_path(context, "index_root")
    database = index_root / str(config.get("database") or "")
    if not database.is_file():
        raise FileNotFoundError(database)
    query = str(config.get("query") or "")
    with sqlite3.connect(f"file:{database}?mode=ro", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        rows = [dict(row) for row in connection.execute(query)]
    minimum = int(config.get("min_rows", 0))
    maximum = int(config.get("max_rows", 2**31 - 1))
    passed = minimum <= len(rows) <= maximum
    return (
        passed,
        {"rows": len(rows), "minimum": minimum, "maximum": maximum},
        [json.dumps(row, ensure_ascii=False) for row in rows[:20]],
    )


def file_contains(
    config: Mapping[str, object],
    context: Mapping[str, object],
) -> tuple[bool, object, Sequence[str]]:
    root = context_path(context, str(config.get("root_key") or "knowledge_root"))
    path = root / str(config.get("path") or "")
    content = path.read_text(encoding="utf-8", errors="ignore")
    required = [str(item) for item in config.get("required_terms", [])]
    forbidden = [str(item) for item in config.get("forbidden_terms", [])]
    missing = [term for term in required if term not in content]
    present_forbidden = [term for term in forbidden if term in content]
    passed = not missing and not present_forbidden
    return (
        passed,
        {
            "required": len(required),
            "missing": len(missing),
            "forbidden_present": len(present_forbidden),
        },
        [*(f"missing: {term}" for term in missing), *(
            f"forbidden: {term}" for term in present_forbidden
        )],
    )


def rag_query(
    config: Mapping[str, object],
    context: Mapping[str, object],
) -> tuple[bool, object, Sequence[str]]:
    script = Path(
        str(context.get("rag_script") or "/Users/zsh/rag/rag-query.sh")
    )
    index_root = context_path(context, "index_root")
    query = str(config.get("query") or "")
    limit = str(int(config.get("limit", 8)))
    environment = {**os.environ, "JIAOTANG_INDEX_ROOT": str(index_root)}
    process = subprocess.run(
        ["bash", str(script), query, limit],
        capture_output=True,
        check=False,
        text=True,
        timeout=int(config.get("timeout_seconds", 45)),
        env=environment,
    )
    if process.returncode != 0:
        raise RuntimeError(process.stderr.strip() or process.stdout.strip())
    payload = json.loads(process.stdout)
    results = payload.get("results", [])
    sources = [str(result.get("source") or "") for result in results]
    joined = "\n".join(sources)
    required_any = [str(item) for item in config.get("required_source_terms_any", [])]
    forbidden = [str(item) for item in config.get("forbidden_source_terms", [])]
    has_required = not required_any or any(term in joined for term in required_any)
    forbidden_hits = [term for term in forbidden if term in joined]
    passed = has_required and not forbidden_hits
    return (
        passed,
        {
            "results": len(results),
            "required_source_hit": has_required,
            "forbidden_hits": forbidden_hits,
        },
        sources[:20],
    )


def build_harness() -> AcceptanceHarness:
    harness = AcceptanceHarness()
    harness.register("path_glob_count", path_glob_count)
    harness.register("manifest_records", manifest_records)
    harness.register("csv_records", csv_records)
    harness.register("sqlite_rows", sqlite_rows)
    harness.register("file_contains", file_contains)
    harness.register("rag_query", rag_query)
    return harness


def main() -> None:
    args = parse_args()
    profile_path = args.profile.expanduser().resolve()
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    index_root = args.index_root.expanduser().resolve()
    context = {
        "knowledge_root": str(args.knowledge_root.expanduser().resolve()),
        "index_root": str(index_root),
        "manifest_path": str(index_root / "manifest.jsonl"),
        "rag_script": "/Users/zsh/rag/rag-query.sh",
    }
    report = build_harness().run(
        profile,
        context,
        suites=args.suite,
    )
    report["receipt_schema"] = "jiaotang-acceptance-receipt/v1"
    report["target_evidence"] = {
        "profile_sha256": sha256_file(profile_path),
        "manifest_sha256": sha256_file(index_root / "manifest.jsonl"),
        "content_index_sha256": sha256_file(
            index_root / "knowledge_content.sqlite3"
        ),
        "inventory_index_sha256": sha256_file(
            index_root / "knowledge_inventory.sqlite3"
        ),
        "policy_versions_sha256": sha256_file(
            index_root / "policy_versions.sqlite3"
        ),
        "upload_allowlist_sha256": sha256_file(
            index_root / "upload_allowlist.csv"
        ),
        "index_builder_sha256": sha256_file(INDEX_BUILDER),
        "inventory_builder_sha256": sha256_file(INVENTORY_BUILDER),
        "allowlist_builder_sha256": sha256_file(ALLOWLIST_BUILDER),
        "policy_version_builder_sha256": sha256_file(
            POLICY_VERSION_BUILDER
        ),
        "harness_runner_sha256": sha256_file(HARNESS_RUNNER),
        "harness_engine_sha256": sha256_file(HARNESS_ENGINE),
    }
    output = args.output
    if output:
        output = output.expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if report["release_allowed"] else 2)


if __name__ == "__main__":
    main()
