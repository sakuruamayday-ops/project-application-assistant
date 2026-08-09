import csv
import json
import sqlite3
import subprocess
import sys
from pathlib import Path


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "build_small_giant_identity_graph.py"
)


def test_audited_candidate_increment_collapses_former_name_and_keeps_candidate_grade(
    tmp_path: Path,
):
    database = tmp_path / "knowledge.sqlite3"
    output = tmp_path / "identity"
    candidate_dir = output / "企知道批量归档"
    registry = output / "企业信用代码权威补全.csv"
    candidate_dir.mkdir(parents=True)
    connection = sqlite3.connect(database)
    connection.executescript(
        """
        CREATE TABLE national_small_giant_master(
            id INTEGER PRIMARY KEY,
            enterprise_name TEXT NOT NULL,
            normalized_name TEXT NOT NULL,
            unified_social_credit_code TEXT NOT NULL DEFAULT '',
            qice_eid TEXT NOT NULL DEFAULT '',
            region TEXT NOT NULL,
            city TEXT NOT NULL DEFAULT '',
            recognition_year INTEGER NOT NULL,
            batch TEXT NOT NULL,
            former_names_json TEXT NOT NULL DEFAULT '[]'
        );
        INSERT INTO national_small_giant_master VALUES(
            1,'名单旧名科技有限公司','名单旧名科技有限公司','','internal-one',
            '江苏省','苏州市',2025,'第七批','[]'
        );
        """
    )
    connection.commit()
    connection.close()
    with registry.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=[
                "enterprise_name",
                "unified_social_credit_code",
                "province",
                "city",
                "former_name",
                "event_type",
                "source_url",
                "source_name",
                "verified_at",
            ],
        )
        writer.writeheader()
    candidate = {
        "recognition_name": "名单旧名科技有限公司",
        "current_name": "现名科技有限公司",
        "unified_social_credit_code": "91320594MA1R8ADQXE",
        "former_names": ["名单旧名科技有限公司"],
        "registration_status": "存续",
        "province": "江苏省",
        "city": "苏州市",
        "recognition_year": 2025,
        "recognition_batch": "第七批",
        "qizhi_captured_at": "2026-08-09T01:00:00+08:00",
        "source_validation_status": "代码锚定候选",
    }
    (candidate_dir / "企业数字身份证_企知道20260809_第01批.jsonl").write_text(
        json.dumps(candidate, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--database",
            str(database),
            "--output",
            str(output),
            "--registry",
            str(registry),
            "--candidate-dir",
            str(candidate_dir),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    connection = sqlite3.connect(database)
    assert connection.execute(
        "SELECT unified_social_credit_code FROM national_small_giant_master WHERE id=1"
    ).fetchone()[0] == "91320594MA1R8ADQXE"
    identity = connection.execute(
        "SELECT current_name,confidence FROM small_giant_enterprise_identities"
    ).fetchone()
    assert identity == ("现名科技有限公司", "audited_single_source_candidate")
    assert connection.execute(
        "SELECT verification_status,source FROM small_giant_enterprise_identity_profiles"
    ).fetchone() == ("audited_single_source_candidate", "共创研究院知识库")
    connection.close()
    public_row = json.loads(
        (output / "全国小巨人企业数字身份证.jsonl").read_text(encoding="utf-8")
    )
    assert public_row["source"] == "共创研究院知识库"
    assert "qizhi_source_file" not in public_row
    assert public_row["verification_status"] == "audited_single_source_candidate"


def test_current_name_and_recognition_time_prevent_false_identity_conflicts(
    tmp_path: Path,
):
    database = tmp_path / "knowledge.sqlite3"
    output = tmp_path / "identity"
    candidate_dir = output / "企知道批量归档"
    registry = output / "企业信用代码权威补全.csv"
    candidate_dir.mkdir(parents=True)
    connection = sqlite3.connect(database)
    connection.executescript(
        """
        CREATE TABLE national_small_giant_master(
            id INTEGER PRIMARY KEY,
            enterprise_name TEXT NOT NULL,
            normalized_name TEXT NOT NULL,
            unified_social_credit_code TEXT NOT NULL DEFAULT '',
            qice_eid TEXT NOT NULL DEFAULT '',
            region TEXT NOT NULL,
            city TEXT NOT NULL DEFAULT '',
            recognition_year INTEGER NOT NULL,
            batch TEXT NOT NULL,
            former_names_json TEXT NOT NULL DEFAULT '[]'
        );
        INSERT INTO national_small_giant_master VALUES
          (1,'北京易控智驾科技有限公司','北京易控智驾科技有限公司','','easy-old','北京市','北京市',2023,'第五批','[]'),
          (2,'易控智驾科技股份有限公司','易控智驾科技股份有限公司','','easy-main','北京市','北京市',2024,'第六批','["北京易控智驾科技有限公司"]'),
          (3,'中能智新科技产业发展有限公司','中能智新科技产业发展有限公司','','zhongneng','北京市','北京市',2025,'第七批','["北京洛斯达科技发展有限公司"]'),
          (4,'北京洛斯达科技发展有限公司','北京洛斯达科技发展有限公司','','luosida','北京市','北京市',2024,'第六批','[]');
        """
    )
    connection.commit()
    connection.close()
    with registry.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=[
                "enterprise_name", "unified_social_credit_code", "province", "city",
                "former_name", "event_type", "source_url", "source_name", "verified_at",
            ],
        )
        writer.writeheader()
    candidates = [
        {
            "recognition_name": "北京易控智驾科技有限公司",
            "current_name": "易控智驾科技股份有限公司",
            "unified_social_credit_code": "91110108MA01C3U537",
            "former_names": ["北京易控智驾科技有限公司"],
            "founded_date": "2018-05-11",
            "registration_status": "存续",
            "province": "北京市",
            "city": "北京市",
            "recognition_year": 2023,
            "recognition_batch": "第五批",
        },
        {
            "recognition_name": "北京易控智驾科技有限公司",
            "current_name": "北京易控智驾科技有限公司",
            "unified_social_credit_code": "91110400MADCG2QK35",
            "former_names": [],
            "founded_date": "2024-03-13",
            "registration_status": "存续",
            "province": "北京市",
            "city": "北京市",
            "recognition_year": 2024,
            "recognition_batch": "第六批",
        },
        {
            "recognition_name": "中能智新科技产业发展有限公司",
            "current_name": "中能智新科技产业发展有限公司",
            "unified_social_credit_code": "91110102774064956D",
            "former_names": [],
            "founded_date": "2005-04-21",
            "registration_status": "存续",
            "province": "北京市",
            "city": "北京市",
            "recognition_year": 2025,
            "recognition_batch": "第七批",
        },
        {
            "recognition_name": "北京洛斯达科技发展有限公司",
            "current_name": "北京洛斯达科技发展有限公司",
            "unified_social_credit_code": "911101087906992148",
            "former_names": [],
            "founded_date": "2006-07-12",
            "registration_status": "存续",
            "province": "北京市",
            "city": "北京市",
            "recognition_year": 2024,
            "recognition_batch": "第六批",
        },
    ]
    (candidate_dir / "企业数字身份证_冲突回归.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in candidates),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            sys.executable, str(SCRIPT), "--database", str(database),
            "--output", str(output), "--registry", str(registry),
            "--candidate-dir", str(candidate_dir),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    connection = sqlite3.connect(database)
    linked = dict(connection.execute(
        "SELECT enterprise_name,unified_social_credit_code FROM national_small_giant_master"
    ))
    assert linked["北京易控智驾科技有限公司"] == "91110108MA01C3U537"
    assert linked["易控智驾科技股份有限公司"] == "91110108MA01C3U537"
    assert linked["中能智新科技产业发展有限公司"] == "91110102774064956D"
    assert linked["北京洛斯达科技发展有限公司"] == "911101087906992148"
    assert connection.execute("SELECT COUNT(*) FROM small_giant_identity_conflicts").fetchone()[0] == 0
    zhongneng_aliases = {
        row[0] for row in connection.execute(
            "SELECT alias_name FROM small_giant_enterprise_aliases WHERE identity_key=?",
            ("91110102774064956D",),
        )
    }
    assert "北京洛斯达科技发展有限公司" not in zhongneng_aliases
    easy_aliases = {
        row[0] for row in connection.execute(
            "SELECT alias_name FROM small_giant_enterprise_aliases WHERE identity_key=?",
            ("91110108MA01C3U537",),
        )
    }
    assert "北京易控智驾科技有限公司" in easy_aliases
    connection.close()
