#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime
from pathlib import Path


DEFAULT_DB = Path("/Volumes/知识库/_云端迁移索引/cloud_package_index/knowledge_content.sqlite3")
DEFAULT_OUTPUT = Path("/Volumes/知识库/_云端迁移索引/cloud_package_index")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="仅输出本周新增的小巨人数量差额和待核验异常")
    parser.add_argument("--database", type=Path, default=DEFAULT_DB)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def snapshot(connection: sqlite3.Connection) -> dict[str, object]:
    batch_counts = {
        str(batch): int(count)
        for batch, count in connection.execute(
            "SELECT batch,COUNT(*) FROM national_small_giant_master GROUP BY batch"
        )
    }
    expected = {
        "第四批": 4357,
        "第五批": 3671,
        "第六批": 3012,
        "第七批": 3482,
    }
    fragment_pending = [
        {
            "fragment_key": str(key),
            "batch": str(batch),
            "region": str(region),
            "title": str(title),
            "reason": str(status),
        }
        for key, batch, region, title, status in connection.execute(
            """
            SELECT fragment_key,batch,region,title,verification_status
            FROM small_giant_official_fragments
            WHERE verification_status<>'official_url_recovered'
            """
        )
    ]
    coverage_pending = [
        {
            "batch": str(batch),
            "region": str(region),
            "platform_candidate_count": int(candidate_count),
            "official_fragment_enterprise_count": int(official_count),
            "count_delta": int(delta),
            "reason": str(status),
        }
        for batch, region, candidate_count, official_count, delta, status in connection.execute(
            """
            SELECT batch,region,platform_candidate_count,official_fragment_enterprise_count,
                   count_delta,closure_status
            FROM small_giant_fragment_coverage
            WHERE closure_status<>'closed_count_and_source'
            """
        )
    ]
    identity_pending = [
        {
            "master_id": int(master_id),
            "enterprise_name": str(name),
            "reason": str(reason),
        }
        for master_id, name, reason in connection.execute(
            "SELECT master_id,enterprise_name,reason FROM small_giant_identity_conflicts WHERE status='pending'"
        )
    ]
    return {
        "batch_counts": batch_counts,
        "count_deltas": {
            batch: batch_counts.get(batch, 0) - expected_count
            for batch, expected_count in expected.items()
        },
        "fragment_pending": fragment_pending,
        "coverage_pending": coverage_pending,
        "identity_pending": identity_pending,
    }


def anomaly_key(item: dict[str, object]) -> str:
    return json.dumps(item, ensure_ascii=False, sort_keys=True)


def main() -> None:
    args = parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    baseline_path = args.output / "small_giant_weekly_baseline.json"
    latest_path = args.output / "small_giant_weekly_anomalies_latest.json"
    markdown_path = args.output / "小巨人每周新增异常.md"
    connection = sqlite3.connect(args.database)
    current = snapshot(connection)
    connection.close()
    previous = {}
    if baseline_path.is_file():
        previous = json.loads(baseline_path.read_text(encoding="utf-8")).get("snapshot", {})
    previous_fragment = {anomaly_key(item) for item in previous.get("fragment_pending", [])}
    previous_identity = {anomaly_key(item) for item in previous.get("identity_pending", [])}
    previous_coverage = {anomaly_key(item) for item in previous.get("coverage_pending", [])}
    new_count_deltas = []
    for batch, delta in current["count_deltas"].items():
        old_delta = previous.get("count_deltas", {}).get(batch)
        if delta != 0 and delta != old_delta:
            new_count_deltas.append({"batch": batch, "previous_delta": old_delta, "current_delta": delta})
    new_fragment = [
        item for item in current["fragment_pending"] if anomaly_key(item) not in previous_fragment
    ]
    new_identity = [
        item for item in current["identity_pending"] if anomaly_key(item) not in previous_identity
    ]
    new_coverage = [
        item for item in current["coverage_pending"] if anomaly_key(item) not in previous_coverage
    ]
    generated_at = datetime.now().astimezone().isoformat(timespec="seconds")
    result = {
        "generated_at": generated_at,
        "new_anomaly_count": len(new_count_deltas) + len(new_fragment) + len(new_coverage) + len(new_identity),
        "new_count_deltas": new_count_deltas,
        "new_fragment_pending": new_fragment,
        "new_coverage_pending": new_coverage,
        "new_identity_pending": new_identity,
        "current_snapshot_summary": {
            "batch_counts": current["batch_counts"],
            "count_deltas": current["count_deltas"],
            "fragment_pending_count": len(current["fragment_pending"]),
            "coverage_pending_count": len(current["coverage_pending"]),
            "identity_pending_count": len(current["identity_pending"]),
        },
    }
    latest_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    baseline_path.write_text(
        json.dumps({"updated_at": generated_at, "snapshot": current}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    lines = [
        "# 小巨人每周新增异常",
        "",
        f"- 生成时间：{generated_at}",
        f"- 本周新增异常：{result['new_anomaly_count']}",
        "",
        "## 新增数量差额",
    ]
    lines.extend(
        [
            f"- {item['batch']}：上次 {item['previous_delta']}，本次 {item['current_delta']}"
            for item in new_count_deltas
        ]
        or ["- 无新增数量差额"]
    )
    lines.extend(["", "## 新增官方链接待恢复"])
    lines.extend(
        [f"- {item['batch']}｜{item['region']}｜{item['title']}" for item in new_fragment]
        or ["- 无新增待恢复链接"]
    )
    lines.extend(["", "## 新增企业身份冲突"])
    lines.extend(
        [f"- {item['enterprise_name']}｜{item['reason']}" for item in new_identity]
        or ["- 无新增身份冲突"]
    )
    lines.extend(["", "## 新增地区批次覆盖差额"])
    lines.extend(
        [
            f"- {item['batch']}｜{item['region']}｜平台候选 {item['platform_candidate_count']}｜"
            f"官方分片 {item['official_fragment_enterprise_count']}｜差额 {item['count_delta']}"
            for item in new_coverage
        ]
        or ["- 无新增地区批次覆盖差额"]
    )
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
