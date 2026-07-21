#!/usr/bin/env python3
import argparse
import json
import re
from pathlib import Path


CATEGORY_RULES = [
    ("small-business", "中小企业与梯度培育", r"专精特新|小巨人|单项冠军|中小企业|小微企业|隐形冠军|独角兽|瞪羚"),
    ("technology", "科技创新与研发", r"高新技术|科技型|研究院|研发中心|实验室|技术中心|科技计划|科学技术|研发费用|创新联合体|众创空间|孵化器|星创天地"),
    ("industrialization", "工业化与产品", r"首台.?套|首批次|首版次|工业新产品|制造业|工业设计|重大技术装备|新材料|产业基础"),
    ("digitalization", "数字化与软件", r"数字|软件|信息化|云平台|工业互联网|智能工厂|未来工厂|人工智能|数据要素|5g|信息消费|电子信息"),
    ("green", "绿色发展与节能", r"绿色|节能|降碳|低碳|循环经济|清洁生产|环保|生态环境|能效|碳达峰|碳中和"),
    ("quality-brand", "质量品牌与标准", r"品牌|质量|标准|品字标|浙江制造|老字号|政府质量奖|守合同重信用|名牌"),
    ("intellectual-property", "知识产权", r"知识产权|专利|商标|版权|地理标志"),
    ("trade", "商务外贸与开放经济", r"外贸|出口|进口|跨境电商|电子商务|服务贸易|商贸|开放发展|国际市场|境外"),
    ("talent", "人才与团队", r"人才|领军|团队|院士|技能大师|工匠|职称|博士后|青年文明号"),
    ("agriculture", "农业农村", r"农业|农村|乡村|农产品|农民|渔业|林业|粮食|农机"),
    ("investment", "投资技改与资金补助", r"技术改造|技改|投资|补助|补贴|专项资金|贷款贴息|保险补偿|财政奖励"),
]

KNOWN_REGIONS = [
    "浙江省",
    "杭州市",
    "宁波市",
    "温州市",
    "嘉兴市",
    "湖州市",
    "绍兴市",
    "金华市",
    "衢州市",
    "舟山市",
    "台州市",
    "丽水市",
    "余杭区",
    "临平区",
    "西湖区",
    "萧山区",
    "钱塘区",
    "拱墅区",
    "滨江区",
    "上城区",
    "临安区",
    "富阳区",
    "建德市",
    "桐庐县",
    "淳安县",
]

HANGZHOU_DISTRICTS = {
    "余杭区",
    "临平区",
    "西湖区",
    "萧山区",
    "钱塘区",
    "拱墅区",
    "滨江区",
    "上城区",
    "临安区",
    "富阳区",
    "建德市",
    "桐庐县",
    "淳安县",
}


def extract(text, pattern):
    match = re.search(pattern, text, re.MULTILINE)
    return match.group(1).strip() if match else ""


def classify(title):
    lowered = title.lower()
    for code, label, pattern in CATEGORY_RULES:
        if re.search(pattern, lowered, re.IGNORECASE):
            return code, label
    return "other", "其他政府项目"


def infer_regions(title, level="", authority=""):
    text = f"{title} {authority}"
    explicit = [region for region in KNOWN_REGIONS if region in text]
    regions = []
    if level == "国家级":
        regions.append("全国")
    elif level == "省级":
        regions.append("浙江省")
    elif level == "市级" and not explicit:
        regions.append("杭州市")
    for region in explicit:
        if region not in regions:
            regions.append(region)
    if any(region in HANGZHOU_DISTRICTS for region in regions):
        for parent in ("杭州市", "浙江省"):
            if parent not in regions:
                regions.append(parent)
    elif any(region.endswith("市") and region != "建德市" for region in regions):
        if "浙江省" not in regions:
            regions.append("浙江省")
    regions = regions or ["待确认"]
    def specificity(region):
        if region in HANGZHOU_DISTRICTS or region.endswith(("区", "县")):
            return 0
        if region.endswith("市"):
            return 1
        if region.endswith("省"):
            return 2
        if region == "全国":
            return 3
        return 4
    return sorted(set(regions), key=lambda region: (specificity(region), regions.index(region)))


def build_record(path):
    text = path.read_text(encoding="utf-8", errors="ignore")
    title = extract(text, r"^#\s+(.+?)\s*$") or path.stem
    level = extract(text, r"^level:[ \t]*(.*)$")
    authority = extract(text, r"^- 📐 归口:[ \t]*(.*)$")
    category, category_label = classify(title)
    return {
        "title": title,
        "level": level,
        "authority": authority,
        "category": category,
        "category_label": category_label,
        "regions": infer_regions(title, level, authority),
        "primary_region": infer_regions(title, level, authority)[0],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    records = [build_record(path) for path in sorted(args.source.glob("*.md"))]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    print(f"wrote {len(records)} records to {args.output}")


if __name__ == "__main__":
    main()
