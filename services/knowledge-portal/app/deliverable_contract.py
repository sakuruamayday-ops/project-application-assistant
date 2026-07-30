from __future__ import annotations

from typing import Mapping, Sequence


FOUR_QUESTION_KEYS = (
    "least_certain",
    "largest_omission",
    "most_valuable_innovation",
    "efficiency_improvement",
)
FOUR_QUESTION_LABELS = {
    "least_certain": "眼下最没有把握的事情",
    "largest_omission": "当前最大的遗漏",
    "most_valuable_innovation": "最有价值的创新改进",
    "efficiency_improvement": "效率改进方法",
}
REPORT_TASK_TYPES = frozenset(
    {
        "analysis-report",
        "project-feasibility-report",
        "enterprise-checkup-report",
        "formal-application-report",
    }
)
PEER_COMPARISON_TASK_TYPES = frozenset(
    {
        "analysis-report",
        "project-feasibility-report",
        "enterprise-checkup-report",
    }
)


def _strings(values: object) -> list[str]:
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
        return []
    return list(
        dict.fromkeys(
            str(value).strip() for value in values if str(value).strip()
        )
    )


def infer_task_type(query: str, deliverable: Mapping[str, object]) -> str:
    explicit = str(deliverable.get("task_type") or "").strip()
    if explicit:
        return explicit
    if any(term in query for term in ("申报书", "正式材料", "申请书")):
        return "formal-application-report"
    if any(term in query for term in ("可行性报告", "项目分析报告")):
        return "project-feasibility-report"
    if "报告" in query:
        return "analysis-report"
    if any(term in query for term in ("复杂分析", "规则变更", "基础设施迁移")):
        return "complex-analysis"
    return "general-response"


def build_delivery_contract(
    query: str,
    deliverable: Mapping[str, object] | None,
) -> dict[str, object]:
    payload = dict(deliverable or {})
    task_type = infer_task_type(query, payload)
    skill_template = payload.get("skill_template")
    if not isinstance(skill_template, Mapping):
        skill_template = {}
    required_sections = _strings(payload.get("required_sections"))
    required_sections.extend(
        section
        for section in _strings(skill_template.get("required_sections"))
        if section not in required_sections
    )
    report_task = task_type in REPORT_TASK_TYPES
    complex_task = bool(
        payload.get("complex_task")
        or payload.get("requires_four_question_review")
        or report_task
        or task_type
        in {"complex-analysis", "rule-change", "infrastructure-migration"}
    )
    peer_required = bool(
        payload.get("peer_comparison_required")
        if "peer_comparison_required" in payload
        else task_type in PEER_COMPARISON_TASK_TYPES
    )
    policy_selection_required = bool(
        payload.get("policy_selection_required")
        or task_type
        in {
            "project-feasibility-report",
            "enterprise-checkup-report",
            "formal-application-report",
            "rule-change",
        }
    )
    return {
        "schema_version": 1,
        "task_type": task_type,
        "required_sections": required_sections,
        "requires_four_question_review": complex_task,
        "requires_peer_comparison": peer_required,
        "requires_policy_selection_trace": policy_selection_required,
        "requires_skill_template_binding": bool(skill_template),
        "skill_template": dict(skill_template),
        "completion_policy": "missing-required-item-means-needs-revision",
    }


def validate_delivery_contract(
    deliverable: Mapping[str, object] | None,
    contract: Mapping[str, object],
) -> dict[str, object]:
    payload = dict(deliverable or {})
    failures: list[dict[str, object]] = []
    warnings: list[str] = []
    sections = payload.get("sections")
    if isinstance(sections, Mapping):
        present_sections = {
            str(name)
            for name, content in sections.items()
            if str(content or "").strip()
        }
    else:
        present_sections = set(_strings(sections))
    for section in _strings(contract.get("required_sections")):
        if section not in present_sections:
            failures.append(
                {
                    "code": "missing-required-section",
                    "item": section,
                    "message": f"缺少必填章节：{section}",
                }
            )

    if contract.get("requires_skill_template_binding"):
        skill_template = payload.get("skill_template")
        if not isinstance(skill_template, Mapping):
            skill_template = {}
        for key, label in (
            ("skill_id", "Skill标识"),
            ("template_id", "模板底稿标识"),
            ("template_version", "模板版本"),
            ("template_hash", "模板内容哈希"),
        ):
            if not str(skill_template.get(key) or "").strip():
                failures.append(
                    {
                        "code": "missing-template-binding",
                        "item": key,
                        "message": f"模板底稿未绑定{label}",
                    }
                )

    if contract.get("requires_policy_selection_trace"):
        selection = payload.get("policy_selection")
        if not isinstance(selection, Mapping):
            selection = {}
        status = str(selection.get("status") or "")
        selected_documents = selection.get("selected_documents")
        if status not in {
            "official-original",
            "official-citation-fallback",
            "management-baseline-only",
        } or not isinstance(selected_documents, list) or not selected_documents:
            failures.append(
                {
                    "code": "missing-policy-selection",
                    "item": "policy_selection",
                    "message": "缺少可追溯的政策选择与降级链记录",
                }
            )
        if selection.get("prohibited_claims"):
            failures.append(
                {
                    "code": "policy-scope-overreach",
                    "item": "prohibited_claims",
                    "message": "报告仍包含当前证据层禁止生成的年度政策结论",
                    "details": list(selection.get("prohibited_claims") or []),
                }
            )

    if contract.get("requires_peer_comparison"):
        comparison = payload.get("peer_comparison")
        if not isinstance(comparison, Mapping):
            comparison = {}
        peers = comparison.get("peers")
        dimensions = _strings(comparison.get("dimensions"))
        sourced_peers = [
            peer
            for peer in peers or []
            if isinstance(peer, Mapping)
            and str(peer.get("name") or "").strip()
            and str(peer.get("source") or peer.get("source_url") or "").strip()
        ]
        if not sourced_peers:
            failures.append(
                {
                    "code": "missing-peer-evidence",
                    "item": "peer_comparison.peers",
                    "message": "同行对比缺少至少一家有来源的同类企业",
                }
            )
        if not dimensions:
            failures.append(
                {
                    "code": "missing-peer-dimensions",
                    "item": "peer_comparison.dimensions",
                    "message": "同行对比缺少明确比较维度",
                }
            )

    if contract.get("requires_four_question_review"):
        review = payload.get("four_question_review")
        if not isinstance(review, Mapping):
            review = {}
        for key in FOUR_QUESTION_KEYS:
            answer = str(review.get(key) or "").strip()
            if not answer:
                failures.append(
                    {
                        "code": "missing-four-question-answer",
                        "item": key,
                        "message": f"四问复盘未回答：{FOUR_QUESTION_LABELS[key]}",
                    }
                )
            elif answer in {
                FOUR_QUESTION_LABELS[key],
                f"{FOUR_QUESTION_LABELS[key]}是什么？",
            }:
                failures.append(
                    {
                        "code": "empty-four-question-answer",
                        "item": key,
                        "message": (
                            "四问复盘只复述问题、没有实际回答："
                            f"{FOUR_QUESTION_LABELS[key]}"
                        ),
                    }
                )

    status = "passed" if not failures else "needs-revision"
    audit = {
        "status": status,
        "failures": failures,
        "warnings": warnings,
        "missing_items": [str(item["item"]) for item in failures],
        "repair_instructions": [str(item["message"]) for item in failures],
        "completion_allowed": not failures,
    }
    audit["repair_plan"] = build_delivery_repair_plan(payload, contract, failures)
    return audit


def _repair_task(
    failure: Mapping[str, object],
    *,
    target_path: str,
    action: str,
    required_inputs: Sequence[str],
    preferred_sources: Sequence[str],
    acceptance_criteria: Sequence[str],
    priority: str = "blocking",
) -> dict[str, object]:
    code = str(failure.get("code") or "delivery-contract-failure")
    item = str(failure.get("item") or "")
    return {
        "task_id": f"repair-{code}-{item}".replace("_", "-").replace(".", "-"),
        "failure_code": code,
        "target_path": target_path,
        "action": action,
        "required_inputs": list(required_inputs),
        "preferred_sources": list(preferred_sources),
        "acceptance_criteria": list(acceptance_criteria),
        "priority": priority,
        "blocking": priority == "blocking",
        "status": "pending",
    }


def build_delivery_repair_plan(
    deliverable: Mapping[str, object] | None,
    contract: Mapping[str, object],
    failures: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    payload = dict(deliverable or {})
    tasks: list[dict[str, object]] = []
    for failure in failures:
        code = str(failure.get("code") or "")
        item = str(failure.get("item") or "")
        if code == "missing-required-section":
            tasks.append(
                _repair_task(
                    failure,
                    target_path=f"sections.{item}",
                    action=(
                        f"按已绑定模板在正确顺序插入“{item}”章节，"
                        "从现有事实、判断和来源中回填内容；无证据的字段明确标为待补。"
                    ),
                    required_inputs=[
                        "模板中该章节的字段定义与顺序",
                        "本次任务已核验事实",
                        "对应结论的政策或材料来源",
                    ],
                    preferred_sources=[
                        "已绑定Skill模板底稿",
                        "用户提供材料",
                        "政府官网原文或已审计官方附件",
                    ],
                    acceptance_criteria=[
                        f"sections.{item}存在且正文非空",
                        "章节内事实、判断与来源可逐项追溯",
                    ],
                )
            )
        elif code == "missing-template-binding":
            labels = {
                "skill_id": "Skill标识",
                "template_id": "模板底稿标识",
                "template_version": "模板版本",
                "template_hash": "模板内容哈希",
            }
            tasks.append(
                _repair_task(
                    failure,
                    target_path=f"skill_template.{item}",
                    action=(
                        f"从实际读取的Skill和模板底稿写入{labels.get(item, item)}，"
                        "禁止凭名称猜测版本或哈希。"
                    ),
                    required_inputs=["实际Skill清单", "实际模板文件元数据"],
                    preferred_sources=["本次运行已读取的SKILL.md", "模板原文件"],
                    acceptance_criteria=[
                        f"skill_template.{item}为非空真实值",
                        "模板内容哈希可由模板原文件复算",
                    ],
                )
            )
        elif code == "missing-policy-selection":
            tasks.append(
                _repair_task(
                    failure,
                    target_path="policy_selection",
                    action=(
                        "重新执行政策选择降级链：发文机关原文→下级政府官网明确引用"
                        "→最近一次申报采用的管理办法；记录每级命中或未命中结果。"
                    ),
                    required_inputs=[
                        "目标项目、地区、判断年度和查询日",
                        "候选政策标题、文号、发布日期、状态与URL",
                    ],
                    preferred_sources=[
                        "发文机关政府官网",
                        "下级政府官网的上级文件引用",
                        "政府公报或已审计官方附件",
                    ],
                    acceptance_criteria=[
                        "policy_selection.status属于允许状态",
                        "selected_documents至少一份且含可验证来源",
                        "征求意见稿与正式政策状态分开标注",
                    ],
                )
            )
        elif code == "policy-scope-overreach":
            tasks.append(
                _repair_task(
                    failure,
                    target_path="policy_selection.prohibited_claims",
                    action=(
                        "逐条定位越界结论：删除、改为预测或改为“当前检索层未命中”；"
                        "征求意见稿不得写成已生效，但可作为前瞻准备主基线。"
                    ),
                    required_inputs=[
                        "prohibited_claims明细",
                        "每条结论对应的证据层和政策状态",
                    ],
                    preferred_sources=["政策选择审计轨迹", "政策时间类型检查结果"],
                    acceptance_criteria=[
                        "prohibited_claims为空",
                        "预测、历史事实与当前正式判断具有不同标签",
                    ],
                )
            )
        elif code == "missing-peer-evidence":
            tasks.append(
                _repair_task(
                    failure,
                    target_path="peer_comparison.peers",
                    action=(
                        "从同一项目公示名单中选择至少一家同地区、同项目或同细分领域企业，"
                        "补入企业名称、可比理由、名单年度和来源URL。"
                    ),
                    required_inputs=["目标企业所属行业与项目", "同项目政府公示名单"],
                    preferred_sources=[
                        "政府认定或公示名单",
                        "政府官网企业案例",
                        "企业官网仅作辅助",
                    ],
                    acceptance_criteria=[
                        "至少一家同行同时含name与source_url",
                        "可比理由没有跨项目或跨产业环节",
                    ],
                )
            )
        elif code == "missing-peer-dimensions":
            tasks.append(
                _repair_task(
                    failure,
                    target_path="peer_comparison.dimensions",
                    action=(
                        "按项目门槛和报告目标补齐比较维度；至少覆盖资格门槛、"
                        "研发创新、市场或产业链位置，并说明统一口径。"
                    ),
                    required_inputs=["项目门槛字段", "企业事实字段", "同行公开字段"],
                    preferred_sources=["正式管理办法", "同一批次名单附件", "企业申报材料"],
                    acceptance_criteria=[
                        "dimensions为非空列表",
                        "每个维度在目标企业和同行间使用同一口径",
                    ],
                )
            )
        elif code in {
            "missing-four-question-answer",
            "empty-four-question-answer",
        }:
            label = FOUR_QUESTION_LABELS.get(item, item)
            tasks.append(
                _repair_task(
                    failure,
                    target_path=f"four_question_review.{item}",
                    action=(
                        f"结合本次实际证据、缺口和实现结果，写出“{label}”的具体答案；"
                        "不得只复述问题。"
                    ),
                    required_inputs=[
                        "本次未核验或存在冲突的事实",
                        "尚未完成的覆盖单元",
                        "已实施的改进与测试结果",
                    ],
                    preferred_sources=["本次审计结果", "测试日志", "政策覆盖矩阵"],
                    acceptance_criteria=[
                        f"four_question_review.{item}为非空具体回答",
                        "答案包含本次任务特有对象或证据，不是通用套话",
                    ],
                )
            )
        else:
            tasks.append(
                _repair_task(
                    failure,
                    target_path=item,
                    action=str(failure.get("message") or "修复交付契约失败项"),
                    required_inputs=["失败项对应的原始内容与证据"],
                    preferred_sources=["本次任务已核验来源"],
                    acceptance_criteria=[f"门禁失败项{code}不再出现"],
                )
            )
    return {
        "schema_version": 1,
        "status": "not-needed" if not tasks else "repair-required",
        "task_count": len(tasks),
        "blocking_task_count": sum(task["blocking"] for task in tasks),
        "tasks": tasks,
        "rerun": {
            "required": bool(tasks),
            "action": "完成全部阻断任务后重新执行delivery_contract_audit",
            "pass_condition": "completion_allowed=true",
        },
        "context": {
            "task_type": contract.get("task_type"),
            "template_bound": bool(payload.get("skill_template")),
        },
    }
