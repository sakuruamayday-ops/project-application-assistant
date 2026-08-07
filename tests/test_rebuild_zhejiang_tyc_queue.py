import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/rebuild_zhejiang_tyc_queue.py"
SPEC = importlib.util.spec_from_file_location("rebuild_zhejiang_tyc_queue", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def test_invalid_name_reason_blocks_ambiguous_source_names() -> None:
    assert MODULE.invalid_name_reason("t杭州示例有限公司")
    assert MODULE.invalid_name_reason("杭州示例公 司")
    assert MODULE.invalid_name_reason("钱潮轴承有限公司-1005600")
    assert MODULE.invalid_name_reason("杭州示例 A 科技有限公司")
    assert MODULE.invalid_name_reason("杭州示例科技有限公司") == ""


def test_corrected_manual_name_only_repairs_confirmed_artifacts() -> None:
    assert MODULE.corrected_manual_name("t杭州示例有限公司") == "杭州示例有限公司"
    assert MODULE.corrected_manual_name("钱潮轴承有限公司-1005600") == "钱潮轴承有限公司"
    assert MODULE.corrected_manual_name("Tesla China") == "Tesla China"
