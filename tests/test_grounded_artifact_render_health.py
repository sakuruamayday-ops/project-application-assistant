import importlib.util
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "tests" / "validate_grounded_artifacts.py"
SPEC = importlib.util.spec_from_file_location("grounded_artifact_validator", VALIDATOR)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def test_visible_pixel_ratio_rejects_blank_page(tmp_path):
    blank = tmp_path / "blank.png"
    Image.new("RGB", (200, 200), "white").save(blank)
    assert MODULE.visible_pixel_ratio(blank) == 0.0


def test_visible_pixel_ratio_accepts_rendered_content(tmp_path):
    rendered = tmp_path / "rendered.png"
    image = Image.new("RGB", (200, 200), "white")
    for x in range(20, 180):
        for y in range(80, 120):
            image.putpixel((x, y), (0, 0, 0))
    image.save(rendered)
    assert MODULE.visible_pixel_ratio(rendered) >= 0.1


def test_missing_glyph_scan_rejects_replacement_markers():
    assert MODULE.has_no_missing_glyphs("可见中文内容")
    assert not MODULE.has_no_missing_glyphs("缺字\ufffd")
    assert not MODULE.has_no_missing_glyphs("缺字\u25a1")
    assert not MODULE.has_no_missing_glyphs("缺字\u25a0")
