from __future__ import annotations

import re
from pathlib import Path


QCC_INVITATION_URL = "https://agent.qcc.com/invitation?code=3ZRZPHF7Q5MH4&ch=LINK_COPY"

QUICK_GUIDE_QUESTIONS = {
    "agent_usage": "企业全生命周期助手如何导入我的Agent？",
    "api_mcp_import": "企业全生命周期助手自带的API和MCP如何导入Agent？",
    "qcc_mcp_import": "企查查MCP如何导入Agent？",
}

SKILL_PROFILES = {
    "enterprise-profile": {
        "keywords": ("企业画像", "工商", "股权", "经营风险", "企业情况", "公司情况"),
        "summary": "核验企业工商、股权、风险、资质与知识产权等事实，不使用不可靠财务推算。",
    },
    "enterprise-panorama-analysis": {
        "keywords": ("全景分析", "尽调", "同行", "竞争", "合作前", "企业分析"),
        "summary": "组织企业全景、同行竞争、风险与合作研判，并明确资料缺口。",
    },
    "project-matching": {
        "keywords": ("能报什么", "申报项目", "项目匹配", "项目推荐", "五年规划", "适合申报"),
        "summary": "结合企业、地区、年度与政策原文匹配项目，输出优先级、差距和行动计划。",
    },
    "policy-retrieval": {
        "keywords": ("政策", "申报条件", "通知", "管理办法", "截止时间", "公示", "认定名单"),
        "summary": "检索并核验政策原文、版本、时效、地域和来源，不以二手摘要代替正式依据。",
    },
    "project-feasibility": {
        "keywords": ("可行性", "符合条件", "能不能报", "差距", "研究院", "首台套", "首批次"),
        "summary": "按政策门槛、企业证据和数据缺口进行可行性分析，不承诺一定符合或获批。",
    },
    "jiaotang-patent-router": {
        "keywords": ("专利", "权利要求", "侵权", "FTO", "同族", "IPC", "法律状态"),
        "summary": "统一完成公司级专利检索、权利要求分析、挖掘交底、FTO、布局和双中心预审推荐；单独核稿转申请文件检查技能。",
    },
    "jiaotang-legal-regulations": {
        "keywords": ("法律", "法规", "合规", "行政处罚", "法条", "监管要求"),
        "summary": "核验现行法律法规、适用地域、效力层级和时间版本，区分法律判断与业务建议。",
    },
    "manufacturing-tax-risk-analysis": {
        "keywords": ("财务", "税务", "审计报告", "金税四期", "纳税", "发票", "所得税"),
        "summary": "基于用户提供的可靠财税资料复算并筛查风险，无可靠数据时不推算企业财务。",
    },
}


def quick_guide_answer(question: str, public_endpoint: str) -> tuple[str, str] | None:
    normalized = re.sub(r"\s+", "", question).lower()
    matched = None
    for guide_name, guide_question in QUICK_GUIDE_QUESTIONS.items():
        if normalized == re.sub(r"\s+", "", guide_question).lower():
            matched = guide_name
            break
    if matched is None:
        return None

    endpoint = public_endpoint.rstrip("/")
    if matched == "agent_usage":
        return (
            "一、统一安装\n"
            "1. 在网站下载最新版企业全生命周期助手 ZIP 并解压。\n"
            "2. 将包内 skills 文件夹拖入当前 Agent 的 Skills 目录或工作区。\n"
            "3. 完全重启 Agent，在对话框输入：请检查企业全生命周期助手是否安装完整，并启动首次配置向导。\n\n"
            "二、导入Agent\n"
            "将 skills 文件夹导入Agent支持的Skills目录或当前工作区，刷新技能列表并重新打开会话。\n\n"
            "三、日常使用\n"
            "不需要记 Skill 名称，直接说明企业名称、地区、拟申报项目、已有资料和希望输出的结果。首次安装应先检查并完成 jiaotang-kb 知识库连接；连接验证成功后，再输入：帮我安装OCR、PDF、Word、PPT、Excel和联网检索这几个Skills。",
            "first-run-configuration",
        )

    if matched == "api_mcp_import":
        return (
            "一、登录焦糖网站，打开“连接我的 Agent”。\n"
            "二、点击“一键安装”，把网站生成的一段完整指令粘贴给 macOS 或 Windows 上的 WorkBuddy。该指令会安装或更新49项Skills、启用最小行为Hook、只替换 mcpServers.jiaotang-kb 并保留其他MCP。\n"
            "三、WorkBuddy 重载一次后，应在 tools/list 中看到 knowledge_search、knowledge_document、knowledge_service_status，并实际调用 knowledge_service_status。只有返回 connected: true 才算完成。\n\n"
            "手工配置页面会自动复用或生成当前登录用户的个人Token，并直接填入完整远程HTTP MCP配置；不需要设备绑定、bootstrap、钥匙串、DPAPI或用户侧签名校验。个人Token不要粘贴到公共代码或聊天回复中，怀疑泄露时在网站撤销，重新打开配置页即可生成新Token。",
            "first-run-configuration",
        )

    return (
        "一、注册并取得官方配置\n"
        f"打开企查查智能体数据平台注册入口：{QCC_INVITATION_URL}\n"
        "完成注册和授权，在企查查控制台取得自己的 API Key，或复制控制台提供的官方 MCP 配置。\n\n"
        "二、导入Agent\n"
        "在Agent的MCP管理页面新增企查查服务。企查查提供HTTP地址时按远程MCP导入；提供启动命令时按stdio型MCP导入。API Key写入安全凭据或环境变量QCC_API_KEY，不要把普通REST地址当成MCP地址。\n\n"
        "三、验证\n"
        "完全重启Agent，确认企查查工具出现在工具列表。使用一家非敏感企业测试企业名称、统一社会信用代码和登记状态。随后运行 first-run-configuration，让企业全生命周期助手记录企查查能力已经可用。\n\n"
        "四、使用边界\n"
        "企查查用于工商、股权、风险、资质和知识产权事实补充；财务数据仍以客户提供的现行资料为准，政策条件仍以政府原文为准。",
        "first-run-configuration",
    )


def route_assistant_skills(question: str, limit: int = 3) -> list[str]:
    normalized = question.lower()
    scored: list[tuple[int, str]] = []
    for skill_name, profile in SKILL_PROFILES.items():
        score = sum(1 for keyword in profile["keywords"] if keyword.lower() in normalized)
        if score:
            scored.append((score, skill_name))
    scored.sort(key=lambda item: (-item[0], item[1]))
    if not scored:
        return ["project-matching", "policy-retrieval"]
    return [skill_name for _, skill_name in scored[:limit]]


def skill_guidance(skill_name: str, skill_source_dir: Path, max_chars: int = 5000) -> str:
    profile = SKILL_PROFILES.get(skill_name)
    if profile is None:
        raise ValueError("不允许加载未登记的Skill")
    skill_path = skill_source_dir / skill_name / "SKILL.md"
    if not skill_path.is_file():
        return f"{skill_name}：{profile['summary']}"
    source = skill_path.read_text(encoding="utf-8", errors="replace")
    return f"{skill_name}\n{source[:max_chars]}"


def skill_context(skill_names: list[str], skill_source_dir: Path) -> str:
    return "\n\n---\n\n".join(skill_guidance(name, skill_source_dir) for name in skill_names)


def assistant_tool_schemas() -> list[dict[str, object]]:
    return [
        {
            "type": "function",
            "function": {
                "name": "knowledge_search",
                "description": "检索团队云端知识库，对应网站POST /v1/search的只读能力。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "需要检索的关键词、企业或项目名称"},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 8},
                    },
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "knowledge_document",
                "description": "读取团队知识库指定文档，对应网站GET /v1/documents/{id}的只读能力。",
                "parameters": {
                    "type": "object",
                    "properties": {"document_id": {"type": "integer", "minimum": 1}},
                    "required": ["document_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "knowledge_case_pack",
                "description": "按项目、年度、行业、企业规模和章节读取成套历史案例及附件关系；案例事实不得复制给当前客户。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "project_id": {"type": "string"},
                        "query": {"type": "string"},
                        "year": {"type": "integer", "minimum": 2000, "maximum": 2100},
                        "industry": {"type": "string"},
                        "enterprise_scale": {"type": "string"},
                        "section": {"type": "string"},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 10},
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "authoritative_list_search",
                "description": (
                    "优先查询国家小巨人、省级专精特新中小企业和三首的权威结构化事实专表，"
                    "返回完整命中总数、官方匹配数、来源等级与可分页结果。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "list_type": {
                            "type": "string",
                            "enum": [
                                "national_small_giant",
                                "provincial_specialized_sme",
                                "three_first",
                            ],
                        },
                        "enterprise_name": {"type": "string"},
                        "product_name": {"type": "string"},
                        "project_name": {"type": "string"},
                        "year": {"type": "integer", "minimum": 2000, "maximum": 2100},
                        "batch": {"type": "string"},
                        "region": {"type": "string"},
                        "status": {"type": "string"},
                        "verified_only": {"type": "boolean"},
                        "offset": {"type": "integer", "minimum": 0, "maximum": 1000000},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 200},
                    },
                    "required": ["list_type"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "public_list_search",
                "description": (
                    "查询通用政府名单实体。国家小巨人、省级专精特新中小企业和三首必须优先使用"
                    " authoritative_list_search；命中专表项目时服务端也会自动安全路由。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "enterprise_name": {"type": "string"},
                        "project_name": {"type": "string"},
                        "year": {"type": "integer", "minimum": 2000, "maximum": 2100},
                        "batch": {"type": "string"},
                        "region": {"type": "string"},
                        "offset": {"type": "integer", "minimum": 0, "maximum": 1000000},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 50},
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "policy_search",
                "description": "按标准项目名称、地区、文件阶段、有效性和年度查询政策文档。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "project_name": {"type": "string"},
                        "region": {"type": "string"},
                        "document_stage": {"type": "string"},
                        "validity_status": {"type": "string"},
                        "year": {"type": "integer", "minimum": 2000, "maximum": 2100},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 20},
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "project_catalog_match",
                "description": "按地区和企业关键词匹配项目地图，仅返回理论候选项目，不表示当期开放或企业符合。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "regions": {"type": "array", "items": {"type": "string"}},
                        "keywords": {"type": "array", "items": {"type": "string"}},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 50},
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "skill_guidance",
                "description": "读取已登记专业Skill的工作规则。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "skill_name": {"type": "string", "enum": sorted(SKILL_PROFILES)},
                    },
                    "required": ["skill_name"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "policy_evidence_select",
                "description": (
                    "按发文机关原文、下级政府官网明确引用、现行管理办法"
                    "三级证据链选择政策，并限制各证据层可生成的年度结论。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "target_year": {"type": "integer"},
                        "requested_claims": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "candidates": {
                            "type": "array",
                            "items": {"type": "object"},
                            "description": (
                                "候选政策，需包含source_url、source_role、"
                                "retrieval_channel、year和verification_status"
                            ),
                        },
                    },
                    "required": [
                        "target_year",
                        "requested_claims",
                        "candidates",
                    ],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "policy_transition_resolve",
                "description": (
                    "解析杭州、宁波、绍兴、金华研发平台或企业技术中心的"
                    "属地版本；发现征求意见稿时，自动区分正式判断与前瞻准备，"
                    "并返回该城市可执行的阈值轨道。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "family_id": {
                            "type": "string",
                            "enum": [
                                "municipal-enterprise-technology-center",
                                "municipal-enterprise-rd-platform",
                            ],
                        },
                        "city": {
                            "type": "string",
                            "enum": ["杭州市", "宁波市", "绍兴市", "金华市"],
                        },
                        "evaluation_mode": {
                            "type": "string",
                            "enum": [
                                "current-assessment",
                                "current-year-preparation",
                                "future-preparation",
                                "forecast",
                                "historical-fact",
                            ],
                        },
                    },
                    "required": ["family_id", "city", "evaluation_mode"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "policy_threshold_evaluate",
                "description": (
                    "按四市研发平台评分附件或备案办法的叶节点规则评估企业事实。"
                    "宁波、绍兴逐叶评分，金华只判断硬门槛与材料，不虚构分值；"
                    "杭州转交现有正式或征求意见稿规则层。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "city": {
                            "type": "string",
                            "enum": ["杭州市", "宁波市", "绍兴市", "金华市"],
                        },
                        "track_id": {
                            "type": "string",
                            "enum": [
                                "hangzhou-current-rd-center",
                                "hangzhou-prospective-enterprise-institute",
                                "ningbo-key-enterprise-institute",
                                "ningbo-enterprise-technology-rd-center",
                                "shaoxing-enterprise-rd-center",
                                "jinhua-science-technology-rd-center",
                            ],
                        },
                        "facts": {
                            "type": "object",
                            "description": (
                                "企业事实字段。缺失字段会形成待补证清单，"
                                "不得猜测评分或资格。"
                            ),
                        },
                    },
                    "required": ["city", "track_id", "facts"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "delivery_contract_audit",
                "description": (
                    "在完成分析报告或复杂任务前检查交付profile、模板章节、"
                    "政策选择链、来源与证据台账、同行对比、内置表格、"
                    "产物哈希与验证器、品牌审计和四问复盘；失败时直接返回"
                    "含补写位置、证据、来源、重跑验证器和验收条件的repair_plan。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "deliverable": {
                            "type": "object",
                            "description": (
                                "结构化交付内容，包含task_type、sections、"
                                "skill_template、policy_selection、"
                                "peer_comparison、sources、evidence_items、"
                                "tables、artifacts、branding_audits和"
                                "four_question_review"
                            ),
                        },
                    },
                    "required": ["query", "deliverable"],
                },
            },
        },
    ]
