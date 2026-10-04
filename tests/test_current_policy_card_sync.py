import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def builder(monkeypatch):
    scripts = ROOT / "skills/project-matching/scripts"
    monkeypatch.syspath_prepend(str(scripts))
    spec = importlib.util.spec_from_file_location("current_policy_builder", scripts / "build_high_frequency_rules.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_shipped_current_cards_match_policy_sources(monkeypatch):
    module = builder(monkeypatch)
    refs = ROOT / "skills/project-matching/references"
    records = {x["project_name"]: x for x in map(json.loads, (refs / "high-frequency-project-rules.jsonl").read_text().splitlines())}
    project_map = module.load_project_map(refs / "project-map.jsonl")
    for card in [*module.sme_current_cards(), module.hangzhou_current_card()]:
        assert records[card["project_name"]] == module.relate_card(card, project_map)


def test_hangzhou_source_status_and_software_threshold_are_preserved(monkeypatch):
    card = builder(monkeypatch).hangzhou_current_card()
    requirements = {x["condition"]: x["requirement"] for x in card["requirements"]}
    assert card["rule_status"] == "current"
    assert card["verification_status"] == "user-supplied-reviewed"
    assert card["official_verification_required"] is True
    assert "农业、软件" in requirements["设备"]
    assert "50万元" in requirements["设备"]
    assert "规上工业" in requirements["主体"]
    assert "评价" not in requirements
    registry = json.loads((ROOT / "services/knowledge-portal/references/four-city-rd-platform-policy-registry.json").read_text())
    family = next(x for x in registry["project_families"] if x["family_id"] == "municipal-enterprise-rd-platform")
    city = next(x for x in family["city_variants"] if x["city"] == "杭州市")
    assert card["source_url"] == city["source_url"]
    assert card["verification_status"] == city["verification_status"]


def test_sme_cards_keep_award_period_and_research_institute_exemption(monkeypatch):
    cards = builder(monkeypatch).sme_current_cards()
    for card in cards:
        ip = next(x["requirement"] for x in card["requirements"] if x["condition"] == "I类知识产权")
        assert "近三年" in ip
        assert "已实际应用并产生经济效益" in ip
    assert "经认定省部级以上研发机构" in cards[0]["requirements"][3]["requirement"]


def test_freshness_uses_effective_date_not_publication_date():
    records = json.loads((ROOT / "skills/policy-freshness-manifest.json").read_text())["records"]
    assert next(x for x in records if x["id"] == "sme-current-policy-2026")["effective_from"] == "2026-04-01"
