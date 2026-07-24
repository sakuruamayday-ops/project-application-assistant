import importlib.util
from pathlib import Path


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "build_zhejiang_enterprise_identity_timeline.py"
)
SPEC = importlib.util.spec_from_file_location("identity_timeline", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def test_normalize_name_removes_punctuation():
    assert MODULE.normalize_name("浙江申新（原名）有限公司") == "浙江申新原名有限公司"


def test_normalize_region_keeps_recognition_layers():
    assert MODULE.normalize_region("台州市|浙江省|临海市") == ("浙江省", "台州市", "临海市")


def test_first_year_uses_earliest_explicit_year():
    assert MODULE.first_year("2025年复核2022年名单") == 2022
