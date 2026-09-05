from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import textwrap
from pathlib import Path


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "deploy_policy_increment_to_server.sh"
)


def write_executable(path: Path, body: str) -> None:
    path.write_text(textwrap.dedent(body).lstrip(), encoding="utf-8")
    path.chmod(0o755)


def fake_remote_commands(tmp_path: Path) -> Path:
    commands = tmp_path / "commands"
    commands.mkdir()
    write_executable(
        commands / "ssh",
        """
        #!/usr/bin/env python3
        import os
        import sys

        os.execve("/bin/bash", ["/bin/bash", "-c", sys.argv[-1]], os.environ)
        """,
    )
    write_executable(
        commands / "readlink",
        """
        #!/usr/bin/env python3
        import os
        import sys

        if len(sys.argv) == 3 and sys.argv[1] == "-f":
            print(os.path.realpath(sys.argv[2]))
        else:
            print(os.readlink(sys.argv[-1]))
        """,
    )
    write_executable(
        commands / "mv",
        """
        #!/usr/bin/env python3
        import os
        import sys

        args = [arg for arg in sys.argv[1:] if arg not in {"-f", "-T", "-Tf", "-fT"}]
        os.replace(args[-2], args[-1])
        """,
    )
    write_executable(
        commands / "rsync",
        """
        #!/usr/bin/env python3
        import os
        import shutil
        import sys
        from pathlib import Path

        if os.environ.get("FAKE_RSYNC_FAIL") == "1":
            raise SystemExit(23)
        source = Path(sys.argv[-2].rstrip("/"))
        destination = Path(sys.argv[-1].split(":", 1)[1])
        destination.mkdir(parents=True, exist_ok=True)
        for child in source.iterdir():
            target = destination / child.name
            if child.is_dir():
                shutil.copytree(child, target, dirs_exist_ok=True, symlinks=True)
            else:
                shutil.copy2(child, target, follow_symlinks=False)
        print("Literal data: 64")
        print("Total bytes sent: 128")
        print("Total bytes received: 32")
        """,
    )
    write_executable(
        commands / "curl",
        """
        #!/bin/sh
        if [ "${FAKE_CURL_FAIL:-0}" = 1 ]; then exit 22; fi
        exit 0
        """,
    )
    for name in ("systemctl", "chown", "find", "sleep"):
        write_executable(commands / name, "#!/bin/sh\nexit 0\n")
    return commands


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_fixture(tmp_path: Path) -> tuple[Path, Path, Path, str]:
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    database = candidate / "knowledge_content.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE sample(value TEXT)")
        connection.execute("INSERT INTO sample VALUES ('candidate')")
    manifest = candidate / "manifest.jsonl"
    manifest.write_text('{"candidate":true}\n', encoding="utf-8")
    release_id = "policy-" + "ab" * 20
    release = {
        "release_id": release_id,
        "files": [
            {"name": database.name, "size": database.stat().st_size, "sha256": sha256(database)},
            {"name": manifest.name, "size": manifest.stat().st_size, "sha256": sha256(manifest)},
        ],
    }
    (candidate / "release.json").write_text(json.dumps(release), encoding="utf-8")

    prepared = tmp_path / "prepared-release.json"
    prepared.write_text(
        json.dumps(
            {
                "candidate_index_dir": str(candidate),
                "release_id": release_id,
                "previous_release_id": "index-base",
                "chain_sha256": "cd" * 32,
                "candidate_index_sha256": sha256(database),
                "candidate_manifest_sha256": sha256(manifest),
            }
        ),
        encoding="utf-8",
    )

    remote = tmp_path / "remote"
    base = remote / "releases" / "index-base"
    base.mkdir(parents=True)
    (base / "base-marker.txt").write_text("base\n", encoding="utf-8")
    (remote / "current").symlink_to(Path("releases") / base.name)
    return prepared, remote, candidate, release_id


def deploy(
    tmp_path: Path,
    prepared: Path,
    remote: Path,
    **overrides: str,
) -> subprocess.CompletedProcess[str]:
    commands = fake_remote_commands(tmp_path)
    receipt = tmp_path / "server-deploy-receipt.json"
    environment = os.environ.copy()
    environment.update(
        {
            "PATH": f"{commands}{os.pathsep}{environment['PATH']}",
            "JIAOTANG_DEPLOY_HOST": "fake-server",
            "JIAOTANG_DEPLOY_KEY": str(tmp_path / "unused-key"),
            "JIAOTANG_POLICY_PREPARED_RELEASE": str(prepared),
            "JIAOTANG_POLICY_DEPLOY_RECEIPT": str(receipt),
            "JIAOTANG_REMOTE_INDEX_ROOT": str(remote),
            **overrides,
        }
    )
    return subprocess.run(
        ["bash", str(SCRIPT), "deploy"],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )


def test_current_only_creates_real_previous_after_healthy_switch(tmp_path: Path) -> None:
    prepared, remote, _, release_id = build_fixture(tmp_path)

    result = deploy(tmp_path, prepared, remote)

    assert result.returncode == 0, result.stderr
    assert (remote / "current").resolve().name == release_id
    assert (remote / "previous").resolve().name == "index-base"
    receipt = json.loads((tmp_path / "server-deploy-receipt.json").read_text())
    assert receipt["deployment_action"] == "switched"
    assert receipt["server_status"] == "healthy"


def test_existing_previous_outside_releases_is_rejected(tmp_path: Path) -> None:
    prepared, remote, _, _ = build_fixture(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (remote / "previous").symlink_to(outside)

    result = deploy(tmp_path, prepared, remote)

    assert result.returncode != 0
    assert "服务器previous路径越界" in result.stderr
    assert (remote / "current").resolve().name == "index-base"


def test_current_only_rsync_failure_keeps_current_and_previous_absent(tmp_path: Path) -> None:
    prepared, remote, _, release_id = build_fixture(tmp_path)

    result = deploy(tmp_path, prepared, remote, FAKE_RSYNC_FAIL="1")

    assert result.returncode != 0
    assert (remote / "current").resolve().name == "index-base"
    assert not (remote / "previous").exists()
    assert not (remote / "releases" / release_id).exists()


def test_current_only_health_failure_restores_original_current(tmp_path: Path) -> None:
    prepared, remote, _, release_id = build_fixture(tmp_path)

    result = deploy(tmp_path, prepared, remote, FAKE_CURL_FAIL="1")

    assert result.returncode != 0
    assert "已恢复切换前current" in result.stderr
    assert (remote / "current").resolve().name == "index-base"
    assert (remote / "previous").resolve().name == release_id


def test_existing_double_slot_still_switches_normally(tmp_path: Path) -> None:
    prepared, remote, _, release_id = build_fixture(tmp_path)
    inactive = remote / "releases" / "index-older"
    inactive.mkdir()
    (inactive / "older-marker.txt").write_text("older\n", encoding="utf-8")
    (remote / "previous").symlink_to(Path("releases") / inactive.name)

    result = deploy(tmp_path, prepared, remote)

    assert result.returncode == 0, result.stderr
    assert (remote / "current").resolve().name == release_id
    assert (remote / "previous").resolve().name == "index-base"
