from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"
TEMPLATES = ROOT / "templates"


def _relative_luminance(hex_color: str) -> float:
    channels = [int(hex_color[index : index + 2], 16) / 255 for index in (1, 3, 5)]
    linear = [
        channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4
        for channel in channels
    ]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast_ratio(first: str, second: str) -> float:
    bright, dark = sorted((_relative_luminance(first), _relative_luminance(second)), reverse=True)
    return (bright + 0.05) / (dark + 0.05)


def test_black_gold_risk_tokens_and_three_confirmation_levels_are_present() -> None:
    base_css = (STATIC / "style.css").read_text(encoding="utf-8")
    theme_css = (STATIC / "atelier.css").read_text(encoding="utf-8")
    portal_js = (STATIC / "portal.js").read_text(encoding="utf-8")

    for token in ("--risk-caution", "--risk-confirm", "--risk-verify"):
        assert token in base_css
    assert "linear-gradient(currentColor, currentColor)" in theme_css
    assert 'data-risk-level="verify"' in theme_css
    assert "RISK_CONFIRMATIONS" in portal_js
    assert 'return "verify"' in portal_js
    assert 'return "confirm"' in portal_js


def test_base_stylesheet_is_only_foundation_not_a_second_light_theme() -> None:
    css = (STATIC / "style.css").read_text(encoding="utf-8")

    assert "color-scheme: dark" in css
    assert len(css.encode("utf-8")) < 2_500
    for retired_selector in (
        ".auth-shell",
        ".app-layout",
        ".sidebar",
        ".hero-banner",
        ".panel",
        ".metrics",
        ".download-card",
    ):
        assert retired_selector not in css
    for retired_light_token in ("--paper", "--surface", "#fff", "#f4f1ed"):
        assert retired_light_token not in css


def test_client_download_cards_use_the_shared_readable_dark_surface() -> None:
    css = (STATIC / "atelier.css").read_text(encoding="utf-8")

    assert ".client-platform-card {" in css
    assert "var(--atelier-panel);" in css
    assert "color-scheme: light;" not in css
    assert "background: #fff;" not in css
    assert ".client-platform-card .button.secondary.is-disabled" in css
    assert _contrast_ratio("#f4f0e7", "#151618") >= 4.5
    assert _contrast_ratio("#a8a39a", "#151618") >= 4.5
    assert _contrast_ratio("#caaa69", "#151618") >= 4.5
    assert _contrast_ratio("#a8a39a", "#191a1c") >= 4.5


def test_section_routes_show_their_rendered_content_without_a_page_allowlist() -> None:
    css = (STATIC / "atelier.css").read_text(encoding="utf-8")

    assert ".section-page .section-block { display: grid; }" in css
    assert ".page-overview #overview" not in css
    assert ".page-algorithms #algorithms" not in css
    assert ".page-feedback #feedback" not in css


def test_single_generic_skill_package_uses_the_full_download_width() -> None:
    css = (STATIC / "skill-center.css").read_text(encoding="utf-8")

    assert ".skill-platform-downloads { display:grid; grid-template-columns:minmax(0,1fr);" in css
    assert not re.search(
        r"\.skill-platform-downloads\s*\{[^}]*grid-template-columns:repeat\(2,minmax\(0,1fr\)\)",
        css,
    )


def test_progress_vendor_pseudo_elements_are_in_separate_rules() -> None:
    css = (STATIC / "console.css").read_text(encoding="utf-8")
    rules = re.findall(r"([^{}]+)\{[^{}]*\}", css)
    progress_rules = [selector for selector in rules if "progress-" in selector]

    assert any("::-webkit-progress-value" in selector for selector in progress_rules)
    assert any("::-moz-progress-bar" in selector for selector in progress_rules)
    assert not any(
        "::-webkit-progress-value" in selector and "::-moz-progress-bar" in selector
        for selector in progress_rules
    )


def test_skills_tabs_have_complete_relationships_and_keyboard_support() -> None:
    template = (TEMPLATES / "skill_center.html").read_text(encoding="utf-8")
    portal_js = (STATIC / "portal.js").read_text(encoding="utf-8")

    assert 'aria-controls="skills-panel-catalog"' in template
    assert 'aria-labelledby="skills-tab-catalog"' in template
    assert 'aria-controls="skill-detail-panel-preview"' in template
    assert 'aria-labelledby="skill-detail-tab-preview"' in template
    assert 'tabindex="-1"' in template
    assert 'event.key === "ArrowRight"' in portal_js
    assert 'event.key === "ArrowLeft"' in portal_js
    assert 'event.key === "Home"' in portal_js
    assert 'event.key === "End"' in portal_js


def test_generated_agent_prompts_start_clipboard_write_inside_user_gesture() -> None:
    portal_js = (STATIC / "portal.js").read_text(encoding="utf-8")

    assert "function copyGeneratedTextFromGesture(valuePromise)" in portal_js
    assert "navigator.clipboard?.write" in portal_js
    assert 'new ClipboardItem({"text/plain": textBlob})' in portal_js
    assert portal_js.count("copyGeneratedTextFromGesture(") == 4
    assert "payloadPromise.then((payload) => payload.prompt)" in portal_js
    assert "copyPrompt = false" not in portal_js
    assert "浏览器未允许复制" in portal_js


def test_generated_agent_prompts_have_inline_manual_copy_fallback() -> None:
    portal_js = (STATIC / "portal.js").read_text(encoding="utf-8")
    css = (STATIC / "atelier.css").read_text(encoding="utf-8")

    assert "function showAgentManualCopy(card, value, title)" in portal_js
    assert "function hideAgentManualCopy(card)" in portal_js
    assert 'textarea.dataset.agentManualCopyValue = ""' in portal_js
    assert 'textarea.readOnly = true' in portal_js
    assert 'retry.dataset.agentManualCopyRetry = ""' in portal_js
    assert "本次生成结果已保留，不会再次生成凭据" in portal_js
    assert portal_js.count("showAgentManualCopy(card, payload.prompt") == 3
    assert ".agent-manual-copy textarea" in css
    assert ".agent-manual-copy[hidden]" in css


def test_black_gold_sources_do_not_use_micro_text_below_11px() -> None:
    sources = ("atelier.css", "console.css", "skill-center.css", "demo.css")
    offenders: list[str] = []
    pattern = re.compile(r"(?:font-size\s*:\s*|font\s*:\s*)(8|9|10)px")
    for name in sources:
        css = (STATIC / name).read_text(encoding="utf-8")
        offenders.extend(f"{name}:{match.group(0)}" for match in pattern.finditer(css))
    assert offenders == []


def test_mobile_skills_avoids_nested_sticky_layers() -> None:
    css = (STATIC / "skill-center.css").read_text(encoding="utf-8")
    portal_js = (STATIC / "portal.js").read_text(encoding="utf-8")

    assert ".skill-section-tabs,.skill-group-switcher,.skill-catalog-controls { position:static; top:auto; }" in css
    assert "--portal-mobile-sticky-offset" not in css
    assert "updateActiveSectionLink" in portal_js
    assert 'scrollToPortalSection(initialSection, "instant")' in portal_js
