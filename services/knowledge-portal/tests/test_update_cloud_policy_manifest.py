from pathlib import Path

import scripts.update_cloud_policy_manifest as manifest


def test_four_city_rd_platform_is_a_formal_manifest_source():
    assert manifest.FOUR_CITY_RD_PLATFORM_ROOT == Path(
        "/Users/zsh/JiaotangData/知识库/10_政策与目录/研究院/四市研发平台"
    )
    files = manifest.four_city_rd_platform_files()
    assert files
    assert any(path.suffix.lower() == ".pdf" for path in files)
    assert any(path.suffix.lower() in {".doc", ".wps"} for path in files)
    assert any(path.name == "README.md" for path in files)
