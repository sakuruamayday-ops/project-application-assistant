from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "templates"


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
