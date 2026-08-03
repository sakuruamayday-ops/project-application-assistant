from scripts.recognized_subject_derivation import (
    derive_industry_subject,
    derive_product_subject,
)


def test_product_subject_derivation_keeps_semantic_head_and_attributes():
    material = derive_product_subject("软包锂电池用铝塑复合膜")
    assert material is not None
    assert material.canonical_subject == "铝塑复合膜"
    assert "软包锂电池用" in material.attributes

    control = derive_product_subject("1000MW火电机组数字化一体化控制系统")
    assert control is not None
    assert control.canonical_subject == "火电机组控制系统"
    assert set(control.attributes) >= {"1000MW", "数字化", "一体化"}

    software = derive_product_subject("智能用电管理系统V1.0")
    assert software is not None
    assert software.canonical_subject == "用电管理系统"
    assert set(software.attributes) >= {"智能", "V1.0"}


def test_industry_subject_derivation_uses_controlled_chinese_normalization():
    cases = {
        "汽车零部件及配件制造": "汽车零部件",
        "阀门和旋塞制造": "阀门",
        "应用软件开发": "应用软件",
        "工业自动控制系统装置制造": "工业自动控制系统",
        "配电开关控制设备制造": "配电开关设备",
    }
    for raw, expected in cases.items():
        subject = derive_industry_subject(raw)
        assert subject is not None
        assert subject.canonical_subject == expected


def test_broad_industry_labels_do_not_become_exact_topics():
    assert derive_industry_subject("其他未列明制造业") is None
    assert derive_industry_subject("科技推广服务") is None
    assert derive_industry_subject("研究和试验发展") is None
    assert derive_industry_subject("其他技术推广服务") is None
    assert derive_industry_subject("其他软件开发") is None
