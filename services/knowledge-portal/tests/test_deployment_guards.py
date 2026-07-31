from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "templates"
DEPLOY_DIR = Path(__file__).resolve().parents[1] / "deploy"


def load_script(name: str):
    path = SCRIPT_DIR / name
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_authenticated_portal_validators_accept_current_contract():
    module = load_script("verify_authenticated_portal.py")
    html = """
    <a data-section-link="feedback">留言反馈</a>
    <a data-section-link="skills">Skills 中心</a>
    <section class="skill-hero"></section>
    <nav class="skill-section-tabs"></nav>
    <div class="skill-catalog-shell">
      <div class="skill-group-switcher"></div>
      <div class="skill-catalog-controls"></div>
    </div>
    <div class="skill-catalog-footer"><button data-skill-back-to-list></button></div>
    <link rel="stylesheet" href="/static/app.css?v=abc123">
    """
    css = """
    .skill-section-tabs { position:sticky; top:0; }
    .skill-group-switcher { position:sticky; top:10px; }
    .skill-catalog-controls { position:sticky; top:20px; }
    .skill-back-to-list { display:inline-flex; }
    """
    assert module.validate_portal_html(html) == "/static/app.css?v=abc123"
    module.validate_stylesheet(css)


def test_server_managed_private_template_hooks_survive_public_deploys():
    base_html = (TEMPLATE_DIR / "base.html").read_text(encoding="utf-8")
    portal_html = (TEMPLATE_DIR / "portal.html").read_text(encoding="utf-8")
    private_nav_hook = (
        '{% include "_private_admin_nav.html" ignore missing %}'
    )

    assert "{% block head_extra %}{% endblock %}" in base_html
    assert private_nav_hook in portal_html
    assert portal_html.index('data-section-link="health-admin"') < (
        portal_html.index(private_nav_hook)
    )
    assert portal_html.index(private_nav_hook) < portal_html.index(
        'href="/admin/knowledge"'
    )


def test_deploy_refreshes_signed_release_before_restart_without_leaking_oss_credentials():
    service = (DEPLOY_DIR / "jiaotang-kb.service").read_text(encoding="utf-8")
    refresh_wrapper = (DEPLOY_DIR / "refresh-index.sh").read_text(encoding="utf-8")
    refresh_service = (
        DEPLOY_DIR / "jiaotang-kb-index-refresh.service"
    ).read_text(encoding="utf-8")
    deploy_script = (SCRIPT_DIR / "deploy_production.sh").read_text(encoding="utf-8")

    assert "EnvironmentFile=/etc/jiaotang-kb-app.env" in service
    assert "jiaotang-kb.env" not in service
    assert "jiaotang-kb-refresh-index" not in service
    writable_paths = next(
        line
        for line in service.splitlines()
        if line.startswith("ReadWritePaths=")
    )
    assert "/srv/jiaotang/skill-releases" not in writable_paths
    assert "/var/backups/jiaotang-kb" not in writable_paths
    assert "/srv/jiaotang/index-snapshots" not in writable_paths
    assert 'if [[ "${mode}" == "--if-missing" ]]' in refresh_wrapper
    assert "EnvironmentFile=/etc/jiaotang-kb-ops.env" in refresh_service
    refresh_command = "index_before="
    assert "scripts/refresh_index_from_oss.py" in deploy_script
    bootstrap_command = "scripts/publish_index_to_oss.py"
    assert bootstrap_command in deploy_script
    assert "--allow-initial-current" in deploy_script
    assert "拒绝用陈旧本地索引执行bootstrap" in deploy_script
    bootstrap_execution = deploy_script.index("bootstrap_release_id=")
    refresh_execution = deploy_script.index(refresh_command)
    restart = deploy_script.index(
        "systemctl restart jiaotang-kb",
        refresh_execution,
    )
    assert bootstrap_execution < refresh_execution < restart


def test_legacy_oss_sync_is_disabled_without_touching_historical_snapshots():
    deploy_script = (SCRIPT_DIR / "deploy_production.sh").read_text(encoding="utf-8")
    legacy_wrapper = (DEPLOY_DIR / "oss-sync.sh").read_text(encoding="utf-8")

    assert "systemctl disable --now" in deploy_script
    assert "jiaotang-kb-oss-sync.timer jiaotang-kb-oss-sync.path" in deploy_script
    assert "enable --now jiaotang-kb-oss-sync" not in deploy_script
    assert "snapshot-retention" not in deploy_script
    assert "exit 78" in legacy_wrapper


def test_deploy_rolls_back_previous_release_when_new_index_health_fails():
    deploy_script = (SCRIPT_DIR / "deploy_production.sh").read_text(encoding="utf-8")
    delta_script = (
        SCRIPT_DIR / "deploy_index_delta_to_server.sh"
    ).read_text(encoding="utf-8")

    assert "scripts/refresh_index_from_oss.py' \\\n                --rollback" in deploy_script
    assert "jiaotang-kb-refresh-index --rollback" in delta_script
    assert "rsync " not in delta_script


def test_deploy_injects_and_verifies_exact_build_identity():
    deploy_script = (SCRIPT_DIR / "deploy_production.sh").read_text(encoding="utf-8")

    assert 'build_commit="$(git -C "${repository_dir}" rev-parse HEAD)"' in deploy_script
    assert "JIAOTANG_BUILD_COMMIT" in deploy_script
    assert "JIAOTANG_DEPLOYMENT_ID" in deploy_script
    assert "JIAOTANG_BUILD_CREATED_AT" in deploy_script
    assert "JIAOTANG_DEPENDENCY_LOCK_SHA256" in deploy_script
    assert "JIAOTANG_DEPENDENCY_BUILD_LOCK_SHA256" in deploy_script
    assert "JIAOTANG_WHEELHOUSE_INSTALL_LOCK_SHA256" in deploy_script
    assert "JIAOTANG_WHEELHOUSE_MANIFEST_SHA256" in deploy_script
    assert "JIAOTANG_WHEELHOUSE_CONTENT_IDENTITY_SHA256" in deploy_script
    assert "JIAOTANG_DEPENDENCY_IDENTITY_SHA256" in deploy_script
    assert "JIAOTANG_DEPENDENCY_RELEASE_RECORD_SHA256" in deploy_script
    assert "JIAOTANG_PRIVATE_OVERLAY_IDENTITY_SHA256" in deploy_script
    assert "jiaotang-private-overlay/v1" in deploy_script
    assert "app/kindle_library.py" in deploy_script
    assert "static/kindle.css" in deploy_script
    assert "私有管理员启动守卫已启用" in deploy_script
    assert "/build" in deploy_script
    assert "生产/build commit与部署源不一致" in deploy_script
    assert "生产/build dependency_identity_sha256不一致" in deploy_script
    assert "生产/build private_overlay_identity_sha256不一致" in deploy_script


def test_deploy_preflights_index_and_aborts_after_rollback():
    deploy_script = (SCRIPT_DIR / "deploy_production.sh").read_text(encoding="utf-8")

    preflight = deploy_script.index("本地索引release集合不完整")
    private_guard = deploy_script.index(
        "JIAOTANG_APP_DIR='${remote_release_dir}'"
    )
    entrypoint_install = deploy_script.index("legacy_entries = runtime / 'legacy-entrypoints'")
    assert preflight < private_guard < entrypoint_install
    rollback = deploy_script.index("rollback_on_error()")
    rollback_exit = deploy_script.index("exit 1", rollback)
    bootstrap = deploy_script.index("bootstrap_release_id=")
    assert rollback < rollback_exit < bootstrap


def test_deploy_requires_main_ci_wheelhouse_and_installs_without_index():
    deploy_script = (SCRIPT_DIR / "deploy_production.sh").read_text(encoding="utf-8")

    assert "JIAOTANG_WHEELHOUSE_DIR" in deploy_script
    assert "JIAOTANG_EXPECTED_WHEELHOUSE_MANIFEST_SHA256" in deploy_script
    assert "JIAOTANG_DEPENDENCY_RELEASE_RECORD" in deploy_script
    assert '"source_event": "push"' in deploy_script
    assert '"source_ref": "refs/heads/main"' in deploy_script
    assert "portal-production-dependency-release-record.json" in deploy_script
    assert "生产主机必须提供CPython 3.12" in deploy_script
    assert "python_supply_chain.py' install" in deploy_script
    assert "PIP_NO_INDEX=1" in deploy_script
    assert "--expected-manifest-sha256" in deploy_script
    assert ".venv/bin/pip' install" not in deploy_script
    assert "-r '${remote_release_dir}/requirements.txt'" not in deploy_script


def test_deploy_uses_future_release_slots_without_historical_backup_governance():
    deploy_script = (SCRIPT_DIR / "deploy_production.sh").read_text(encoding="utf-8")

    assert "/opt/jiaotang-kb-release-slots" in deploy_script
    assert "/opt/jiaotang-kb-runtime" in deploy_script
    assert "runtime / 'current'" in deploy_script
    assert "runtime / 'previous'" in deploy_script
    assert "不可变应用release已存在，拒绝覆盖" in deploy_script
    assert "应用current已指回previous" in deploy_script
    for forbidden in (
        "runtime-transaction",
        "failed-new-state",
        "portal-predeploy",
        "REMOTE_BACKUP_DIR",
        "/opt/jiaotang-kb-backups",
    ):
        assert forbidden not in deploy_script
    assert "tar -C '${remote_release_dir}' -xf -" in deploy_script
    assert "tar -C '${legacy_app_dir}' -xf -" not in deploy_script


def test_index_sync_bootstraps_server_before_advancing_remote_current():
    sync_script = (
        SCRIPT_DIR / "sync_archived_knowledge_to_production.sh"
    ).read_text(encoding="utf-8")

    deploy = '"${script_dir}/deploy_production.sh"'
    publish = 'python3 "${script_dir}/publish_index_to_oss.py"'
    assert sync_script.index(deploy) < sync_script.index(publish)
    assert sync_script.index(publish) < sync_script.index(
        '"${script_dir}/deploy_index_delta_to_server.sh"'
    )


def test_deployment_lock_rejects_second_process(tmp_path: Path):
    lock_script = SCRIPT_DIR / "with_deployment_lock.py"
    lock_file = tmp_path / "deploy.lock"
    holder = subprocess.Popen(
        [
            sys.executable,
            str(lock_script),
            "--lock-file",
            str(lock_file),
            "--",
            sys.executable,
            "-c",
            "import time; time.sleep(3)",
        ]
    )
    try:
        for _ in range(30):
            if lock_file.exists() and lock_file.read_text(encoding="utf-8").strip():
                break
            import time

            time.sleep(0.05)
        contender = subprocess.run(
            [
                sys.executable,
                str(lock_script),
                "--lock-file",
                str(lock_file),
                "--",
                sys.executable,
                "-c",
                "print('unexpected')",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert contender.returncode == 75
        assert "其他任务锁定" in contender.stderr
    finally:
        holder.terminate()
        holder.wait(timeout=5)
