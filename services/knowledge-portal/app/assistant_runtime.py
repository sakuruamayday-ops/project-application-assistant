from __future__ import annotations

import re
from pathlib import Path


QCC_PLATFORM_URL = "https://agent.qcc.com"

QUICK_GUIDE_QUESTIONS = {
    "agent_usage": "企业全生命周期助手如何导入我的Agent？",
    "api_mcp_import": "企业全生命周期助手自带的API和MCP如何导入Agent？",
    "qcc_mcp_import": "企查查MCP如何导入Agent？",
}

SKILL_PROFILES = {
    "local-knowledge-retrieval": {
        "keywords": ("名单", "认定企业", "入选企业", "通过企业", "获批企业", "列出", "查找企业", "同行企业", "首版次", "首台套", "首批次"),
        "summary": "从权威名单和知识库中检索已认定企业、产品与来源，保留覆盖边界且不把未命中写成不存在。",
    },
    "industrialization-projects": {
        "keywords": ("首台套", "首版次", "首批次", "工业新产品", "装备", "软件产品", "新材料"),
        "summary": "区分装备、软件与新材料项目类型，并核对产品级认定边界。",
    },
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
    "patent-router": {
        "keywords": ("专利", "权利要求", "侵权", "FTO", "同族", "IPC", "法律状态"),
        "summary": "统一完成公司级专利检索、权利要求分析、挖掘交底、FTO、布局和双中心预审推荐；单独核稿转申请文件检查技能。",
    },
    "legal-regulations": {
        "keywords": ("法律", "法规", "合规", "行政处罚", "法条", "监管要求"),
        "summary": "核验现行法律法规、适用地域、效力层级和时间版本，区分法律判断与业务建议。",
    },
    "manufacturing-tax-risk-analysis": {
        "keywords": ("财务", "税务", "审计报告", "金税四期", "纳税", "发票", "所得税"),
        "summary": "基于用户提供的可靠财税资料复算并筛查风险，无可靠数据时不推算企业财务。",
    },
}


def quick_guide_answer(
    question: str,
    public_endpoint: str,
    skill_count: int,
) -> tuple[str, str] | None:
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
            "一、共创客户端\n"
            "登录共创研究院网站后打开“客户端下载”，选择 macOS 或 Windows 安装包。安装后使用服务器账号密码登录，官方 Skills 会由客户端完成签名校验、安装和更新，不需要手动复制目录。\n\n"
            "二、其他 Agent\n"
            "在网站 Skills 中心下载通用技能包，将 skills 文件夹导入宿主支持的 Skills 目录；知识库 MCP 使用标准 Streamable HTTP 配置。网站不再提供 WorkBuddy 专用技能包。\n\n"
            "三、日常使用\n"
            "不需要记 Skill 名称，直接说明企业名称、地区、拟申报项目、已有资料和希望输出的结果。模型、企查查、天眼查、PaddleOCR 和社区仓库统一在共创客户端 Skills 中心的“安装与连接”中管理；只有真实授权和健康检查通过后才显示已连接。",
            "first-run-configuration",
        )

    if matched == "api_mcp_import":
        return (
            "一、共创客户端不再设置独立“API 与用户”标签。登录客户端后，进入 Skills 中心的“安装与连接”。\n"
            f"二、官方{skill_count}项 Skills 由客户端自动校验和更新；共创知识库 MCP 使用当前客户端账号建立连接，不要求用户复制 WorkBuddy 安装指令。\n"
            "三、DeepSeek、OpenCode 和自定义 API 在模型设置中连接；企查查、天眼查、PaddleOCR 等第三方服务在对应技能详情点击“添加”，跳转官方注册或授权。\n"
            "四、返回客户端后必须完成 tools/list 和服务健康调用。只有真实返回成功才显示“已连接”，不能以用户点击“我已完成配置”代替校验。其他 Agent 仍可从 Skills 中心下载通用包，并在“安装与连接”复制标准知识库 MCP 配置。",
            "first-run-configuration",
        )

    return (
        "一、注册并取得官方配置\n"
        f"在共创客户端 Skills 中心打开企查查连接卡，点击“添加”后进入官方平台：{QCC_PLATFORM_URL}\n"
        "完成注册和登录。现阶段按企查查官方控制台提供的 API Key 或 MCP 配置接入；在未取得企查查官方 OAuth 合作能力前，客户端不能伪装成已自动授权。\n\n"
        "二、返回客户端连接\n"
        "将官方 API Key 粘贴到系统安全凭据窗口，或按官方 MCP 配置完成连接。API Key只进入钥匙串或 Windows 凭据管理器，不写普通配置文件；兼容宿主可使用环境变量QCC_API_KEY。\n\n"
        "三、验证\n"
        "客户端自动执行工具发现和非敏感健康检查。企查查工具真实返回后才显示“已连接”；失败时保留具体错误和重新授权入口。\n\n"
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
                "name": "enterprise_lifecycle_decision",
                "description": (
                    "对一个或多个明确项目执行确定性企业生命周期决策。多项目通过project_context.projects传入，"
                    "服务端逐项目返回且不静默截断；routing-only项目只返回待核验，不得宣称已算法判断。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "enterprise_facts": {"type": "array", "items": {"type": "object"}},
                        "project_context": {"type": "object"},
                        "requirements": {"type": "array", "items": {"type": "object"}},
                        "growth_projects": {"type": "array", "items": {"type": "object"}},
                        "deliverable": {"type": "object"},
                    },
                    "required": ["query", "enterprise_facts", "project_context", "requirements"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "recognition_search",
                "description": (
                    "统一处理认定名单反向发现：从自然语言提取全部项目、产品或行业、地区、年度和状态，"
                    "返回确切、相关、待核验三档结果及覆盖边界；政策答疑和可行性问题只返回确定性路由。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "projects": {"type": "array", "items": {"type": "string"}, "maxItems": 20},
                        "subject_terms": {"type": "array", "items": {"type": "string"}, "maxItems": 50},
                        "regions": {"type": "array", "items": {"type": "string"}, "maxItems": 20},
                        "years": {
                            "type": "array",
                            "items": {"type": "integer", "minimum": 2000, "maximum": 2100},
                            "maxItems": 20,
                        },
                        "status": {"type": "string", "default": "final_recognition"},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 200},
                    },
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "enterprise_identity_lineage_lookup",
                "description": (
                    "按企业现名、曾用名或统一社会信用代码反查共创研究院知识库身份血缘，"
                    "返回当前名、历史名、信用代码以及同名、多代码、合并主体和缺代码冲突路径。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "minLength": 1, "maxLength": 200},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 50},
                    },
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "three_first_analysis",
                "description": (
                    "统一查询首台套、首版次和首批次，可一次处理多个项目和多个地区；"
                    "按产品找企业时必须传 product_name，并检查 coverage_ledger 与各组分页状态。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "enterprise_name": {"type": "string"},
                        "product_name": {"type": "string"},
                        "industry": {"type": "string"},
                        "award_year": {"type": "integer", "minimum": 2000, "maximum": 2100},
                        "from_year": {"type": "integer", "minimum": 2000, "maximum": 2100},
                        "to_year": {"type": "integer", "minimum": 2000, "maximum": 2100},
                        "include_review_candidates": {"type": "boolean"},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 50},
                        "region": {"type": "string"},
                        "regions": {"type": "array", "items": {"type": "string"}, "maxItems": 20},
                    },
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "authoritative_list_search",
                "description": (
                    "优先查询国家小巨人、省级专精特新中小企业和三首的权威结构化事实专表，"
                    "返回命中总数、官方匹配数、来源覆盖状态与可分页结果。用户要求完整名单时，"
                    "必须按 next_offset 连续调用直至 has_more=false；coverage 不允许完整声明时必须明确报缺口。"
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
                                "小巨人",
                                "专精特新中小企业",
                                "三首",
                                "首台套",
                                "首版次",
                                "首批次",
                            ],
                        },
                        "enterprise_name": {"type": "string"},
                        "product_name": {"type": "string"},
                        "project_name": {"type": "string"},
                        "year": {"type": "integer", "minimum": 2000, "maximum": 2100},
                        "batch": {"type": "string"},
                        "region": {"type": "string"},
                        "status": {"type": "string"},
                        "event_type": {
                            "type": "string",
                            "enum": [
                                "recognition",
                                "recognition_publicity",
                                "review_passed",
                                "review_publicity"
                            ]
                        },
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
