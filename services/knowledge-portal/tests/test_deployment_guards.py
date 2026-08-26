from __future__ import annotations

import hashlib
import importlib.util
import subprocess
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
STATIC_DIR = Path(__file__).resolve().parents[1] / "static"
TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "templates"
DEPLOY_DIR = Path(__file__).resolve().parents[1] / "deploy"


def load_script(name: str):
    path = SCRIPT_DIR / name
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_generated_static_assets_match_canonical_sources():
    module = load_script("build_static_assets.py")
    sections = ["@layer base, console, theme;\n"]
    for layer, name in module.SOURCES:
        content = (STATIC_DIR / name).read_text(encoding="utf-8").strip()
        sections.append(f"@layer {layer} {{\n{content}\n}}\n")
    expected_css = "\n".join(sections)
    generated_css = (STATIC_DIR / "app.css").read_text(encoding="utf-8")
    assert generated_css == expected_css

    digest = hashlib.sha256(generated_css.encode("utf-8")).hexdigest()[:16]
    assets = (TEMPLATE_DIR / "_static_assets.html").read_text(encoding="utf-8")
    assert f'/static/app.css?v={digest}' in assets


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


def test_deploy_verifies_signed_index_binding_without_refreshing_index():
    service = (DEPLOY_DIR / "jiaotang-kb.service").read_text(encoding="utf-8")
    deployment_service = (
        DEPLOY_DIR / "jiaotang-kb-application-deploy@.service"
    ).read_text(encoding="utf-8")
    transaction = (SCRIPT_DIR / "run_application_deployment.py").read_text(
        encoding="utf-8"
    )
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
    deployment_writable_paths = next(
        line
        for line in deployment_service.splitlines()
        if line.startswith("ReadWritePaths=")
    ).split("=", 1)[1].split()
    assert "/etc" in deployment_writable_paths
    assert "/opt/jiaotang-kb-release-slots" in deployment_writable_paths
    assert "/etc/jiaotang-kb-ops.env" not in deployment_writable_paths
    assert "/etc/jiaotang-kb-app.env" not in deployment_writable_paths
    assert "replaces both environment files atomically" in deployment_service
    assert 'if [[ "${mode}" == "--if-missing" ]]' in refresh_wrapper
    assert "EnvironmentFile=/etc/jiaotang-kb-ops.env" in refresh_service
    verifier = "scripts/verify_index_release_binding.py"
    assert verifier in deploy_script
    for receipt_dependency in (
        "scripts/build_knowledge_inventory_from_manifest.py",
        "scripts/build_cloud_upload_allowlist.py",
        "scripts/run_acceptance_harness.py",
        "scripts/release_progress.py",
    ):
        assert receipt_dependency in deploy_script
    assert "JIAOTANG_RELEASE_MODE=code 或 index" in deploy_script
    assert "bootstrap_release_id=" not in deploy_script
    assert "--allow-initial-current" not in deploy_script
    assert "release_id_for(index_dir" not in deploy_script
    assert "PRAGMA quick_check" not in deploy_script
    verify_execution = deploy_script.index(verifier)
    transaction_launch = deploy_script.index(
        "jiaotang-kb-application-deploy@${deployment_id}.service"
    )
    assert verify_execution < transaction_launch
    assert '["systemctl", "restart", "jiaotang-kb.service"]' in transaction


def test_code_deploy_entrypoint_fixes_code_mode_without_index_work():
    wrapper = (SCRIPT_DIR / "deploy_code_to_production.sh").read_text(
        encoding="utf-8"
    )

    assert "export JIAOTANG_RELEASE_MODE=code" in wrapper
    assert 'JIAOTANG_RELEASE_MODE}" != "code"' in wrapper
    assert 'exec "${script_dir}/deploy_production.sh"' in wrapper
    assert "sync_archived_knowledge_to_production" not in wrapper


def test_legacy_oss_sync_is_disabled_without_touching_historical_snapshots():
    deploy_script = (SCRIPT_DIR / "deploy_production.sh").read_text(encoding="utf-8")
    legacy_wrapper = (DEPLOY_DIR / "oss-sync.sh").read_text(encoding="utf-8")

    assert "systemctl disable --now" in deploy_script
    assert "jiaotang-kb-oss-sync.timer jiaotang-kb-oss-sync.path" in deploy_script
    assert "enable --now jiaotang-kb-oss-sync" not in deploy_script
    assert "snapshot-retention" not in deploy_script
    assert "exit 78" in legacy_wrapper


def test_health_monitor_restarts_only_after_consecutive_failures_with_circuit_breaker():
    health_service = (DEPLOY_DIR / "jiaotang-kb-health.service").read_text(
        encoding="utf-8"
    )
    recovery_service = (
        DEPLOY_DIR / "jiaotang-kb-health-recovery@.service"
    ).read_text(encoding="utf-8")
    recovery_wrapper = (DEPLOY_DIR / "health-recovery.sh").read_text(
        encoding="utf-8"
    )
    health_wrapper = (DEPLOY_DIR / "healthcheck.sh").read_text(
        encoding="utf-8"
    )
    timer = (DEPLOY_DIR / "jiaotang-kb-health.timer").read_text(
        encoding="utf-8"
    )
    deploy_script = (SCRIPT_DIR / "deploy_production.sh").read_text(
        encoding="utf-8"
    )

    assert "jiaotang-kb-health-recovery@%n.service" in health_service
    assert "ExecStart=/usr/local/sbin/jiaotang-kb-health-recovery %i" in recovery_service
    assert "User=root" in recovery_service
    assert "health_recovery_state.py\" failure" in recovery_wrapper
    assert 'JIAOTANG_HEALTH_FAILURE_THRESHOLD:-2' in recovery_wrapper
    assert 'JIAOTANG_HEALTH_MAX_RESTARTS:-3' in recovery_wrapper
    assert 'JIAOTANG_HEALTH_RESTART_WINDOW_SECONDS:-1800' in recovery_wrapper
    assert 'JIAOTANG_HEALTH_CIRCUIT_COOLDOWN_SECONDS:-3600' in recovery_wrapper
    assert '[[ "${action}" == "restart" ]]' in recovery_wrapper
    assert "systemctl restart jiaotang-kb.service" in recovery_wrapper
    assert "health_recovery_state.py\" success" in health_wrapper
    assert "OnUnitActiveSec=1m" in timer
    assert "AccuracySec=10s" in timer
    assert "scripts/health_recovery_state.py" in deploy_script
    assert "'jiaotang-kb-health-recovery@.service'" in deploy_script
    assert "'/usr/local/sbin/jiaotang-kb-health-recovery'" in deploy_script


def test_deploy_rolls_back_previous_release_when_new_index_health_fails():
    deploy_script = (SCRIPT_DIR / "deploy_production.sh").read_text(encoding="utf-8")
    transaction = (SCRIPT_DIR / "run_application_deployment.py").read_text(
        encoding="utf-8"
    )
    delta_script = (
        SCRIPT_DIR / "deploy_index_delta_to_server.sh"
    ).read_text(encoding="utf-8")

    assert 'request["release_mode"] == "index"' in transaction
    assert '"scripts/refresh_index_from_oss.py"' in transaction
    assert '"--rollback"' in transaction
    assert "refresh_index_from_oss.py" not in deploy_script[
        deploy_script.index("[5/8]") :
    ]
    assert "jiaotang-kb-refresh-index --rollback" in delta_script
    assert "rsync " not in delta_script


def test_index_refresh_restart_defers_to_health_check_and_rollback():
    delta_script = (
        SCRIPT_DIR / "deploy_index_delta_to_server.sh"
    ).read_text(encoding="utf-8")

    # systemd 恢复器可能接管首次启动；restart 的瞬时返回值不能跳过后续健康复检。
    assert delta_script.count("systemctl restart jiaotang-kb || true") == 2
    restart = delta_script.index("systemctl restart jiaotang-kb || true")
    health_loop = delta_script.index("for attempt in", restart)
    rollback = delta_script.index("jiaotang-kb-refresh-index --rollback", health_loop)
    assert restart < health_loop < rollback


def test_deploy_transfers_release_retention_dependency():
    deploy_script = (SCRIPT_DIR / "deploy_production.sh").read_text(encoding="utf-8")

    assert "scripts/refresh_index_from_oss.py scripts/publish_index_to_oss.py" in deploy_script
    assert "scripts/release_retention.py" in deploy_script


def test_code_preflight_selects_the_active_index_verifier():
    deploy_script = (SCRIPT_DIR / "deploy_production.sh").read_text(encoding="utf-8")
    transaction = (SCRIPT_DIR / "run_application_deployment.py").read_text(
        encoding="utf-8"
    )

    assert "scripts/verify_policy_increment_server.py" in deploy_script
    assert "'/usr/local/libexec/release_retention.py'" in deploy_script
    assert "signed-policy-delta-chain-v1" in deploy_script
    assert "configure_index_verifier(app_env)" in transaction
    assert "jiaotang-kb-policy-increment-verify.timer" in transaction
    assert 'desired.removesuffix(".timer") + ".service"' in transaction
    configure_at = transaction.index("configure_index_verifier(app_env)")
    explicit_health_at = transaction.index(
        'run_checked(["systemctl", "start", "jiaotang-kb-health.service"])',
        configure_at,
    )
    health_timer_at = transaction.index(
        '["systemctl", "enable", "--now", "jiaotang-kb-health.timer"]',
        explicit_health_at,
    )
    assert configure_at < explicit_health_at < health_timer_at
    policy_service = (
        DEPLOY_DIR / "jiaotang-kb-policy-increment-verify.service"
    ).read_text(encoding="utf-8")
    assert "User=root" in policy_service
    assert "Group=jiaotang" in policy_service


def test_deploy_injects_and_verifies_exact_build_identity():
    deploy_script = (SCRIPT_DIR / "deploy_production.sh").read_text(encoding="utf-8")
    transaction = (SCRIPT_DIR / "run_application_deployment.py").read_text(
        encoding="utf-8"
    )

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
    assert "生产/build {key}与部署请求不一致" in transaction
    assert 'verify_build(request["expected_build"])' in transaction


def test_deploy_preflights_signed_binding_before_detached_transaction():
    deploy_script = (SCRIPT_DIR / "deploy_production.sh").read_text(encoding="utf-8")

    assert "scripts/oss_reconciliation.py" in deploy_script
    assert "scripts/stream_to_command.py" in deploy_script
    assert deploy_script.count('python3 "${script_dir}/stream_to_command.py"') == 3
    assert "--exclude='*/__pycache__' --exclude='*.pyc'" in deploy_script
    assert "JIAOTANG_DEPLOY_TRANSFER_STALL_TIMEOUT_SECONDS" in deploy_script
    assert "JIAOTANG_DEPLOY_TRANSFER_COMPLETION_TIMEOUT_SECONDS" in deploy_script
    preflight = deploy_script.index("verify_index_release_binding.py")
    private_guard = deploy_script.index(
        "JIAOTANG_APP_DIR='${remote_release_dir}'"
    )
    entrypoint_install = deploy_script.index("legacy_entries = runtime / 'legacy-entrypoints'")
    assert preflight < private_guard < entrypoint_install
    stable_worker = deploy_script.index(
        "'/usr/local/libexec/jiaotang-kb-application-deploy'"
    )
    transaction_launch = deploy_script.index(
        "systemctl start --no-block 'jiaotang-kb-application-deploy@"
    )
    assert preflight < private_guard < entrypoint_install < stable_worker
    assert stable_worker < transaction_launch


def test_index_release_emits_exact_oss_cleanup_plan_with_object_versions():
    release_script = (
        SCRIPT_DIR / "sync_archived_knowledge_to_production.sh"
    ).read_text(encoding="utf-8")
    reconciliation = release_script.index("oss_reconciliation.py")
    refresh = release_script.index("deploy_index_delta_to_server.sh", reconciliation)
    command = release_script[reconciliation:refresh]

    assert "--include-history" in command
    assert "--include-version-ids" in command
    assert "--require-current-complete" in command


def test_admin_disk_detail_exposes_physical_release_cleanup_debt():
    application = (SCRIPT_DIR.parent / "app" / "main.py").read_text(
        encoding="utf-8"
    )
    template = (TEMPLATE_DIR / "admin_health_detail.html").read_text(
        encoding="utf-8"
    )

    assert "def release_cleanup_backlog()" in application
    assert "gongchuang-server-release-cleanup-plan/v1" in application
    assert '"cleanup_pending": release_cleanup_backlog()' in application
    assert "发布后待清理" in template
    assert "cleanup_pending.plan_sha256" in template
    assert "不再把“已移入回收区”误报为已经释放空间" in template


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
    assert "不可变应用release已存在，拒绝覆盖" in deploy_script
    transaction = (SCRIPT_DIR / "run_application_deployment.py").read_text(
        encoding="utf-8"
    )
    assert 'runtime / "previous"' in transaction
    assert "atomic_symlink(previous, current)" in transaction
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


def test_index_sync_publishes_and_switches_index_before_application():
    sync_script = (
        SCRIPT_DIR / "sync_archived_knowledge_to_production.sh"
    ).read_text(encoding="utf-8")

    deploy = '"${script_dir}/deploy_production.sh"'
    publish = 'python3 "${script_dir}/publish_index_to_oss.py"'
    delta = '"${script_dir}/deploy_index_delta_to_server.sh"'
    assert sync_script.index(publish) < sync_script.index(delta)
    assert sync_script.index(delta) < sync_script.index(deploy)
    assert "JIAOTANG_RELEASE_MODE=index" in sync_script
    assert "JIAOTANG_INDEX_ALREADY_DEPLOYED" not in sync_script
    assert "verify_acceptance_receipt.py" in sync_script
    assert "release-timings" in sync_script
    assert "[release-stage]" in sync_script
    assert 'stage_mark "signed-index-release" "started"' in sync_script
    assert 'stage_mark "server-index-refresh" "started"' in sync_script
    assert '"${script_dir}/build_enterprise_identity_lineage.py"' in sync_script
    assert '--knowledge-identities' in sync_script


def test_index_refresh_streams_transfer_progress_and_has_a_bounded_runtime():
    delta_script = (
        SCRIPT_DIR / "deploy_index_delta_to_server.sh"
    ).read_text(encoding="utf-8")
    refresh = (SCRIPT_DIR / "refresh_index_from_oss.py").read_text(
        encoding="utf-8"
    )
    service = (
        DEPLOY_DIR / "jiaotang-kb-index-refresh.service"
    ).read_text(encoding="utf-8")

    assert "systemctl start --no-block" in delta_script
    assert "[index-refresh] elapsed_seconds=" in delta_script
    assert "release-progress" in delta_script
    assert "progress_callback=reporter" in refresh
    assert 'stage="download-verify"' in refresh
    assert "TimeoutStartSec=45min" in service


def test_lightweight_oss_verification_and_backup_timer_survive_deploys():
    deploy_script = (SCRIPT_DIR / "deploy_production.sh").read_text(
        encoding="utf-8"
    )
    refresh_wrapper = (DEPLOY_DIR / "refresh-index.sh").read_text(
        encoding="utf-8"
    )
    refresh = (SCRIPT_DIR / "refresh_index_from_oss.py").read_text(
        encoding="utf-8"
    )
    verify_service = (
        DEPLOY_DIR / "jiaotang-kb-oss-verify.service"
    ).read_text(encoding="utf-8")
    verify_timer = (
        DEPLOY_DIR / "jiaotang-kb-oss-verify.timer"
    ).read_text(encoding="utf-8")
    transaction = (SCRIPT_DIR / "run_application_deployment.py").read_text(
        encoding="utf-8"
    )

    assert '"--verify-only"' in refresh_wrapper
    assert "args.verify_only" in refresh
    assert 'verification_mode": "metadata-only"' in refresh
    assert "ExecStart=/usr/local/sbin/jiaotang-kb-refresh-index --verify-only" in verify_service
    assert "OnUnitActiveSec=1h" in verify_timer
    assert '"jiaotang-kb-backup.timer"' in transaction
    assert '"jiaotang-kb-oss-verify.timer"' in transaction


def test_application_deploy_is_resumable_and_shutdown_is_bounded():
    deploy_script = (SCRIPT_DIR / "deploy_production.sh").read_text(
        encoding="utf-8"
    )
    service = (DEPLOY_DIR / "jiaotang-kb.service").read_text(encoding="utf-8")
    transaction_unit = (
        DEPLOY_DIR / "jiaotang-kb-application-deploy@.service"
    ).read_text(encoding="utf-8")
    waiter = (SCRIPT_DIR / "wait_for_application_deployment.py").read_text(
        encoding="utf-8"
    )
    resume = (SCRIPT_DIR / "resume_application_deployment.sh").read_text(
        encoding="utf-8"
    )

    assert "systemctl start --no-block" in deploy_script
    assert "wait_for_application_deployment.py" in deploy_script
    assert "不直接判定生产失败" in deploy_script
    assert "transport_retry" in waiter
    assert "jiaotang-application-deployment-state/v1" in waiter
    assert "systemctl start --no-block" in resume
    assert "wait_for_application_deployment.py" in resume
    assert "Type=oneshot" in transaction_unit
    assert "TimeoutStartSec=7min" in transaction_unit
    assert (
        "Environment=JIAOTANG_RELEASE_TRASH_ROOT="
        "/opt/jiaotang-kb-release-slots/.Trash/files"
    ) in transaction_unit
    assert "ProtectHome=true" in transaction_unit
    assert "--timeout-graceful-shutdown 20" in service
    assert "TimeoutStopSec=30s" in service
    assert "ExecStartPost=/usr/local/sbin/jiaotang-kb-wait-ready" in service


def test_index_sync_uses_one_canonical_manifest_and_candidate_root():
    sync_script = (
        SCRIPT_DIR / "sync_archived_knowledge_to_production.sh"
    ).read_text(encoding="utf-8")
    updater = (SCRIPT_DIR / "update_cloud_policy_manifest.py").read_text(
        encoding="utf-8"
    )

    assert 'export JIAOTANG_MANIFEST_PATH="${manifest}"' in sync_script
    assert 'export JIAOTANG_KNOWLEDGE_MANIFEST_PATH="${manifest}"' in sync_script
    assert "JIAOTANG_CANDIDATE_ROOT/index" in sync_script
    assert "候选发布不得指向可变current目录" in sync_script
    assert "全量发布拒绝原位改写签名链current" in sync_script
    assert "rebase-full-release" in sync_script
    assert "local_release_sync.py" in sync_script
    assert sync_script.index("rebase-full-release") < sync_script.index(
        "local_release_sync.py"
    )
    assert 'os.environ.get("JIAOTANG_MANIFEST_PATH"' in updater
    assert "JIAOTANG_MANIFEST_PATH与JIAOTANG_KNOWLEDGE_MANIFEST_PATH不一致" in updater


def test_full_release_rebuilds_target_twins_after_policy_versions():
    sync_script = (
        SCRIPT_DIR / "sync_archived_knowledge_to_production.sh"
    ).read_text(encoding="utf-8")

    policy_at = sync_script.index("build_policy_version_links.py")
    twin_at = sync_script.index("rebuild_target_project_identity_twins.py")
    verify_at = sync_script.index("verify_target_project_twin_closure.py", twin_at)
    validation_at = sync_script.index('stage_mark "validation-and-tests" "started"')
    assert policy_at < twin_at < verify_at < validation_at
    assert "三首产品补充证据_20260812.json" in sync_script
    assert '--knowledge-root "${knowledge_root}"' in sync_script


def test_index_convergence_accepts_expected_nonzero_status_before_restoring_err_trap():
    sync_script = (
        SCRIPT_DIR / "sync_archived_knowledge_to_production.sh"
    ).read_text(encoding="utf-8")

    check_start = sync_script.index('echo "[5/10] 校验manifest与本轮提取报告是否收敛"')
    branch_start = sync_script.index("if (( convergence_status == 2 )); then")
    check_block = sync_script[check_start:branch_start]

    assert check_block.index("trap - ERR") < check_block.index("set +e")
    assert check_block.index('convergence_status="$?"') < check_block.index("set -e")
    assert check_block.index("set -e") < check_block.index("trap record_stage_failure ERR")


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
