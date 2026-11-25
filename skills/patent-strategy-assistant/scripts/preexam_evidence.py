"""Keep caller input and independently recorded pre-examination evidence distinct."""

import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "_runtime"))
from policy_original_text import read_policy_text


LOCATION_SOURCES = {"api": "接口返回", "public": "公开来源"}
RECORD_SOURCES = {**LOCATION_SOURCES, "receipt": "备案回执"}
RECORD_LABEL = {"yes": "已备案", "no": "未备案", "unknown": "未核实"}
CENTER_NAMES = {"zhejiang": "浙江省知识产权保护中心", "hangzhou": "杭州市知识产权保护中心"}
CENTER_KEYS = tuple(CENTER_NAMES)
FILING_TEXT = {"yes": re.compile(r"已备案|备案成功|备案(?:审核)?通过"),
               "no": re.compile(r"未备案|备案(?:审核)?未通过")}


def add_evidence_arguments(parser):
    parser.add_argument("--applicant-evidence", type=Path, help="本案主体、住所及双中心备案的证据记录 JSON")
    for center in CENTER_KEYS:
        parser.add_argument(f"--{center}-record", choices=tuple(RECORD_LABEL),
                            help="调用者提供的备案状态，使用证据记录核验")


def _reference(entry, sources, manifest, anchors, filing=None):
    if not isinstance(entry, dict):
        raise ValueError("证据记录须为对象")
    source = entry.get("source")
    reference = entry.get("reference")
    if not isinstance(source, str) or source not in sources or not isinstance(reference, str) or not reference.strip():
        raise ValueError("证据记录缺可识别的来源类型或原件定位")
    artifact = entry.get("artifact")
    if not isinstance(artifact, str) or not artifact.strip():
        raise ValueError("证据记录缺原件 artifact")
    path = (manifest.parent / Path(artifact).expanduser()).resolve()
    if path == manifest:
        raise ValueError("证据记录与原件须为两个文件")
    text = path.read_text(encoding="utf-8-sig") if path.suffix.lower() == ".json" else read_policy_text(path)
    normalized = "".join(text.split())
    if any("".join(value.split()) not in normalized for value in anchors):
        raise ValueError(f"证据原件 {path.name} 缺本案主体、住所或中心")
    if filing and (not FILING_TEXT[filing].search(normalized)
                   or any(pattern.search(normalized) for status, pattern in FILING_TEXT.items() if status != filing)):
        raise ValueError(f"证据原件 {path.name} 缺与登记状态一致的备案结果")
    return sources[source], reference.strip()


def applicant_evidence(args):
    payload = {}
    manifest = args.applicant_evidence.expanduser().resolve() if args.applicant_evidence else None
    if manifest:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or not args.company.strip() or payload.get("company") != args.company.strip():
            raise ValueError("证据记录的申请主体与本案公司不一致")
    result = {
        "company": args.company or None,
        "registered_location": args.applicant_location,
        "location_source": "企业提供",
    }
    location = payload.get("location")
    if location is not None:
        if not isinstance(location, dict) or location.get("value") != args.applicant_location:
            raise ValueError("登记住所证据与输入住所不一致")
        source, reference = _reference(location, LOCATION_SOURCES, manifest, (args.company, args.applicant_location))
        result.update(location_source=source, location_reference=reference)

    records = payload.get("records", {})
    if not isinstance(records, dict) or records.keys() - set(CENTER_KEYS):
        raise ValueError("备案证据须按 zhejiang、hangzhou 分别登记")
    evidence = {}
    for center in CENTER_KEYS:
        entry = records.get(center)
        claimed = getattr(args, f"{center}_record")
        status = "unknown"
        source = "企业提供" if claimed in {"yes", "no"} else None
        reference = None
        if entry is not None:
            status = entry.get("status") if isinstance(entry, dict) else None
            if not isinstance(status, str) or status not in FILING_TEXT:
                raise ValueError(f"{center} 备案证据须给出明确状态")
            source, reference = _reference(entry, RECORD_SOURCES, manifest, (args.company, CENTER_NAMES[center]), status)
            if claimed in {"yes", "no"} and status != claimed:
                raise ValueError(f"{center} 备案证据与企业提供的状态不一致")
        result[f"{center}_record_status"] = status
        evidence[center] = {"status": RECORD_LABEL[status], "source": source, "reference": reference}
    result["record_evidence"] = evidence
    result["record_basis"] = "逐中心核对本案证据；缺证据的中心为未核实"
    return result
