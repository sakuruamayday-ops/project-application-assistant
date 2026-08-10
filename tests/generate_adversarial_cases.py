#!/usr/bin/env python3
"""生成21技能的第一版对抗型任务集。"""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROMPTS_PATH = ROOT / "tests" / "adversarial-prompts.jsonl"
EXPECTED_PATH = ROOT / "tests" / "adversarial-expected.json"


CATALOG = [
    {
        "skill": "agriculture-and-rural-projects",
        "base": "合作社准备申报未来农场，请核验种植基地、数字农业设施和联农带农材料。",
        "typo": "合作社想报未来农扬，主要看种植基底、数字农业和联农带农，该怎么处理？",
        "negation": "这不是食品加工产线项目，不分析制造设备投资，只判断未来农场和联农带农条件。",
        "multi": "材料同时提到基地、冷链设备和电商销售，但本次只申报未来农场，请确定处理路径。",
        "forbidden": ["industrialization-projects", "investment-subsidy-projects"],
        "policy": "未来农场",
    },
    {
        "skill": "application-version-diff",
        "base": "比较昨天和今天两版申报书中研发投入、章节和专利状态的变化。",
        "typo": "帮我比对昨夭和今天两板申报书，看研发投人和专立状态改了什么。",
        "negation": "不要评价企业是否符合条件，也不要重写材料，只比较两个版本的变化。",
        "multi": "两版材料还附有财务表和专利清单，但当前任务只是找出版本差异和联动影响。",
        "forbidden": ["project-feasibility", "application-writing"],
    },
    {
        "skill": "application-writing",
        "base": "政策和企业事实已经核验，请据此撰写主导产品和核心技术正式材料。",
        "typo": "政策和企业事买都核过了，请写主导产晶和核心技木正式材料。",
        "negation": "不用再判断能否申报，也不要补造市场数据，只按已核验事实写正式材料。",
        "multi": "现有政策、审计报告、专利和检测资料均已核验，请统一口径完成正式申报文本。",
        "forbidden": ["project-matching"],
    },
    {
        "skill": "consistency-check",
        "base": "检查已经完成的终稿中主导产品、财务数字和专利是否前后矛盾。",
        "typo": "检杳终搞里的主导产晶、财务数宇和专立是不是前后打架。",
        "negation": "不要重新撰写，也不做资格判断，只检查这份单一终稿的一致性。",
        "multi": "终稿同时包含财务、知识产权、补短板和国产替代表述，请做最终一致性检查。",
        "forbidden": ["application-version-diff", "application-writing"],
    },
    {
        "skill": "digitalization-projects",
        "base": "工厂申报智能制造项目，请核验设备联网、MES集成和质量闭环。",
        "typo": "工厂想报智造制遣，重点是设奋联网、MES和质里闭环。",
        "negation": "这不是软件研发项目，也不分析办公OA，只判断制造现场数字化条件。",
        "multi": "企业既买设备又上MES，但本次申报目标是智能工厂，不是单纯设备补助。",
        "forbidden": ["technology-innovation-projects", "investment-subsidy-projects"],
        "policy": "智能工厂",
    },
    {
        "skill": "evidence-ledger",
        "base": "把政策、审计报告和专利材料按事实、计算、推断和待核验建立台账。",
        "typo": "把政册、审记报告和专立材料按事实、汁算、推断、待核验建台帐。",
        "negation": "暂时不要判断能否申报，也不要写正文，只建立证据台账。",
        "multi": "政策、财务、专利和市场数据来源互相交叉，请先统一登记来源与冲突。",
        "forbidden": ["project-feasibility", "application-writing"],
    },
    {
        "skill": "green-development-projects",
        "base": "分析节能改造前后的单位产品能耗、用水和碳排变化。",
        "typo": "分析节能改造前后单位产晶能粍、用水和炭排有什么变化。",
        "negation": "不要查询环保处罚，也不做设备补助分析，只核验绿色绩效。",
        "multi": "项目包含锅炉设备、能源管理系统和碳核算，但本次目标是申报绿色工厂。",
        "forbidden": ["investment-subsidy-projects", "digitalization-projects"],
        "policy": "绿色工厂",
    },
    {
        "skill": "industry-positioning",
        "base": "根据目录候选，判断主导产品、收入和专利能否支撑产业链关键环节定位。",
        "typo": "根据产来链目录候选，判断主导产晶、收人和专立能不能撑住关键环节定位。",
        "negation": "不要只凭经营范围下结论，也不做项目资格评分，只判断产业定位证据。",
        "multi": "企业有多个产品和专利，但需要围绕收入最高的主导产品判断产业链位置。",
        "forbidden": ["project-feasibility"],
    },
    {
        "skill": "intellectual-property-projects",
        "base": "企业申报知识产权示范项目，请分析权利质量、管理制度和转化运用。",
        "typo": "企业想报知产示饭项目，请看权力质量、管理制渡和转化运佣。",
        "negation": "不做侵权判断，也不预测专利授权，只分析知识产权项目申报能力。",
        "multi": "材料有专利、商标、管理认证和许可收入，本次目标是知识产权示范项目。",
        "forbidden": ["patent-router"],
        "policy": "知识产权示范企业",
    },
    {
        "skill": "investment-subsidy-projects",
        "base": "核验生产设备和产线投资的合同、发票、付款、到货及资产入账。",
        "typo": "核验产线投姿的合铜、发漂、付宽、到货和固姿入账。",
        "negation": "不分析研发人员和科研任务，只核验设备投资补助证据。",
        "multi": "项目既有设备购置又有少量研发费，但补助对象明确是固定资产投资。",
        "forbidden": ["technology-innovation-projects"],
        "policy": "技术改造投资补助",
    },
    {
        "skill": "ip-assessment",
        "base": "判断企业现有专利哪些可以作为项目申报证据，并标明法律状态和产品关联。",
        "typo": "判断现有专立哪些能当申报证据，标明法绿状态和产晶关联。",
        "negation": "不做侵权分析，也不能把审中专利当授权，只评估申报证据价值。",
        "multi": "企业同时有授权、审中和受让专利，请按法律状态和主导产品关联分类。",
        "forbidden": ["patent-router"],
    },
    {
        "skill": "patent-router",
        "base": "基于现有专利和检索结果规划未来三年的专利申请方向。",
        "typo": "基于现有专立和捡索结果，规划未来三年的申请方响。",
        "negation": "不要承诺新颖性，也不要直接撰写申请文件，只做专利布局规划。",
        "multi": "企业有多个产品模块和竞争对手专利，但当前只需要形成三年布局优先级。",
        "forbidden": ["checking-patdocx-cn-single-agent"],
    },
    {
        "skill": "peer-benchmarking",
        "base": "从今年官方入选名单中寻找同类产品企业做事实对标。",
        "typo": "从今年官芳入选名丹找同类产晶企业做事实对标。",
        "negation": "不要猜专家评分，也不能因为入选就推断所有指标均满足，只做公开事实对标。",
        "multi": "名单中企业跨多个行业和地区，请仅选择同年度、同项目、同类产品的可比对象。",
        "forbidden": ["project-feasibility"],
        "policy": "当年度官方入选名单",
    },
    {
        "skill": "policy-retrieval",
        "base": "查找今年申报项目的管理办法、通知、附件、答疑和延期文件。",
        "typo": "帮我找今年项木的管里办法、申抱通知、附见和延其文件。",
        "negation": "暂时不要分析企业是否达标，也不要写申报材料，只找完整政策原文。",
        "multi": "同时搜到新闻稿、商业平台摘要和政府通知，请只确认官方完整政策链。",
        "forbidden": ["project-feasibility", "application-writing"],
        "policy": "项目申报通知",
    },
    {
        "skill": "project-memory",
        "base": "继续上次客户项目，召回确认过的政策版本、企业事实和待补材料。",
        "typo": "继读上次客户项木，只召回确人过的政策板本和待补材科。",
        "negation": "不要加载个人写作习惯，也不要保存证件和密码，只恢复项目事实。",
        "multi": "上次记录包含政策、财务、专利和材料缺口，请按已确认和待复核分开召回。",
        "forbidden": ["experience-recorder"],
    },
    {
        "skill": "quality-brand-projects",
        "base": "比较浙江制造精品和政府质量奖，并分别按产品与组织管理口径分析。",
        "typo": "比较浙江制遣精晶和政俯质里奖，分清产晶认定和组识管理。",
        "negation": "不是单项冠军，也不分析知识产权示范，只比较制造精品和质量奖。",
        "multi": "企业同时有标准、检测、市场数据和质量管理体系，请分别判断两个质量品牌项目。",
        "forbidden": ["intellectual-property-projects"],
        "policy": "浙江制造精品",
    },
    {
        "skill": "regional-special-projects",
        "base": "区里新发了现有类别无法覆盖的临时专项，请整理规则并判断企业条件。",
        "typo": "区里新发一个现有类形盖不住的临时专向，请整里规则。",
        "negation": "不要套用已有数字化或绿色项目模型，这是一项无法归类的区级临时专项。",
        "multi": "通知同时涉及研发、设备和人才，但没有固定领域模型，请先转成候选规则。",
        "forbidden": ["digitalization-projects", "green-development-projects"],
        "policy": "区级临时专项",
    },
    {
        "skill": "skill-authoring",
        "base": "根据真实失败案例修改助手技能规则，并为修改结果增加前向测试。",
        "typo": "根据真实失改案例修改助守技胀规则，再加前向测式。",
        "negation": "这不是客户项目申报任务，不分析企业资格，只修改技能规则。",
        "multi": "需要同时调整技能正文、路由边界和发布自检，但不改变客户业务数据。",
        "forbidden": ["project-feasibility", "application-writing"],
    },
    {
        "skill": "talent-projects",
        "base": "企业申报创业领军人才，请核验到岗、持股、劳动关系和项目任务。",
        "typo": "企业想报创业领军人材，请核验到岗、持服、劳动关糸和项木任务。",
        "negation": "不是普通研发团队项目，也不能仅凭学历判断，只分析创业人才申报条件。",
        "multi": "候选人既任职又持股并负责研发项目，但本次申报主体是创业人才本人。",
        "forbidden": ["technology-innovation-projects"],
        "policy": "创业领军人才",
    },
    {
        "skill": "technology-innovation-projects",
        "base": "企业申报研发机构，请核验研发人员、设备、投入、项目和成果。",
        "typo": "企业想报研収机购，请核验研収人圆、设奋、投人、项木和成果。",
        "negation": "不涉及扩产设备补助，也不是产品示范认定，只分析研发机构条件。",
        "multi": "材料中既有研发设备也有科研项目，但主要目标是认定企业研发机构。",
        "forbidden": ["investment-subsidy-projects", "industrialization-projects"],
        "policy": "企业研发机构",
    },
    {
        "skill": "trade-and-open-economy-projects",
        "base": "申报跨境电商项目，请核验境外订单、平台、物流、收汇和海关数据。",
        "typo": "申报跨竟电商，请核验境外订丹、平合、物流、收会和海观数据。",
        "negation": "不是国内电商项目，也不分析一般内销，只核验跨境业务证据。",
        "multi": "企业同时有境内外订单，但本次只申报跨境电商并核对海关与收汇口径。",
        "forbidden": ["digitalization-projects"],
        "policy": "跨境电商专项",
    },
]


POLICY_SKILLS = {
    "agriculture-and-rural-projects",
    "digitalization-projects",
    "green-development-projects",
    "intellectual-property-projects",
    "investment-subsidy-projects",
    "peer-benchmarking",
    "policy-retrieval",
    "quality-brand-projects",
    "regional-special-projects",
    "talent-projects",
    "technology-innovation-projects",
    "trade-and-open-economy-projects",
}


def expected_record(case_id: str, entry: dict, category: str) -> dict:
    if category == "stale-policy":
        primary_skill = "policy-retrieval"
        required = ["policy-retrieval"]
        forbidden = sorted(
            set(entry.get("forbidden", []))
            | {"project-feasibility", "application-writing"}
        )
    else:
        primary_skill = entry["skill"]
        required = [entry["skill"]]
        forbidden = entry.get("forbidden", [])
    return {
        "case_id": case_id,
        "category": category,
        "expected_primary_skill": primary_skill,
        "required_skills": required,
        "forbidden_skills": forbidden,
        "clarification_required": False,
        "expected_policy_status": "stale" if category == "stale-policy" else "not-applicable",
        "claims_must_be_limited": category == "stale-policy",
    }


def main() -> int:
    prompts = []
    expected = []
    categories = [
        ("base", "base"),
        ("typo", "typo"),
        ("negation", "negation"),
        ("multi-domain", "multi"),
    ]
    for index, entry in enumerate(CATALOG, start=1):
        prefix = f"ADV-{index:02d}"
        for suffix, key in categories:
            case_id = f"{prefix}-{suffix.upper()}"
            prompts.append(
                {
                    "case_id": case_id,
                    "category": suffix,
                    "prompt": entry[key],
                }
            )
            expected.append(expected_record(case_id, entry, suffix))
        if entry["skill"] in POLICY_SKILLS:
            stale_prompts = [
                f"我只有2022年的{entry['policy']}通知，想用于2026年申报。请先核验它是否仍有效以及当前完整文件链，暂时不要判断企业条件。",
                f"企业拿着已经截止的2023年{entry['policy']}通知，想作为当前批次依据。请先核验政策版本和效力，暂时不要形成资格结论。",
            ]
            for stale_index, prompt in enumerate(stale_prompts, start=1):
                case_id = f"{prefix}-STALE-{stale_index}"
                prompts.append(
                    {
                        "case_id": case_id,
                        "category": "stale-policy",
                        "prompt": prompt,
                    }
                )
                expected.append(expected_record(case_id, entry, "stale-policy"))

    PROMPTS_PATH.write_text(
        "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in prompts),
        encoding="utf-8",
    )
    EXPECTED_PATH.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "case_count": len(expected),
                "answers": expected,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    report = {
        "status": "pass",
        "prompt_count": len(prompts),
        "expected_count": len(expected),
        "policy_skills": len(POLICY_SKILLS),
        "paths": [str(PROMPTS_PATH), str(EXPECTED_PATH)],
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
