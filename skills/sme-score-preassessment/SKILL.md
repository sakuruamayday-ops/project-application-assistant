---
name: sme-score-preassessment
description: 按2026年现行政策执行专精特新中小企业与专精特新“小巨人”申报前门槛预评估、质量分核验和差距诊断；不再使用历史四维评分表或内部100分估算器。
---

# 2026年专精特新申报前预评估


<!-- BEGIN MANAGED PORTABLE SKILL RUNTIME -->
## 便携运行门禁

!`python3 "${CODEBUDDY_SKILL_DIR}/scripts/portable_skill_runtime.py" prepare`

!`if [ -f "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" ]; then python3 "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" activate --plugin-root "${CODEBUDDY_PLUGIN_ROOT}" --session "${CODEBUDDY_SESSION_ID}" --skill "sme-score-preassessment" --skill-dir "${CODEBUDDY_SKILL_DIR}"; fi`

每次触发先执行 `prepare` 并应用 `active_preferences`；失败时停止，受限时明确能力边界。长期偏好不能覆盖真实性、安全和质量门禁。完整规则见[便携运行协议](references/portable-runtime-protocol.md)。
<!-- END MANAGED PORTABLE SKILL RUNTIME -->

!`python3 "${CODEBUDDY_SKILL_DIR}/scripts/preflight.py" --task-type explanation`

## 目标与边界

本技能只处理 2026 年政策下的申报前预评估：核对硬门槛、梳理质量评价输入、记录主管部门平台质量分，并给出差距和行动。没有平台实际分数时，质量分必须写为“待平台评价”，不得生成估算总分、区间分、保守分、条件分或通过概率。

历史四维评分、内部二十二项百分制、统计局对标折算和三档总分已经退出活动技能包。用户要求“按旧表测分”时，说明该模型已停用，改为 2026 门槛预评估。

已形成完整申请书的后期体检改用 `sme-development-projects`。同时要求前期预评估与后期体检时，以后者为主并附本技能的门槛和平台质量分状态，不并行运行两套结论。

## 前置门禁

每次先完整读取[2026年政策基线](references/current-policy-baseline-2026.md)，再按当前任务运行：

```bash
python3 "${CODEBUDDY_SKILL_DIR}/scripts/preflight.py" \
  --task-type quality-preassessment \
  --project-level "省级专精特新中小企业" \
  --application-type "新申报"
```

- 项目层级和申请类型必须来自本轮材料。缺失会改变规则时，只提出一次最小确认并暂停结论。
- 新申报按 2026 新办法执行。省级质量分门槛为 50 分，小巨人质量分门槛为 60 分。
- 2026 年小巨人复核属于 2026 当期通知明确的过渡分支，只能在当期复核任务中使用；不得把该分支扩展到新申报或未来年度。
- 质量分只能来自主管部门平台或用户提供且可回指平台的记录。任何内部模型都不得冒充平台质量分。

## 数据边界

1. 企业身份、资质、专利和荣誉优先用当前可用的企业信息工具核验；未命中写“当前检索层未命中”。
2. 财务、经营、研发、人员、主导产品、客户、产能和市场占有率只使用用户材料或明确陈述，不用第三方旧财务补造。
3. 事实分为已核验、用户提供、计算、冲突和待补。每个硬门槛记录规则来源、企业值、证据状态和结论。
4. 平台质量分未提供时保持 `pending-platform-evaluation`，不得用行业均值、统计局数据或经验权重填补。
5. 主导产品、补短板、填空白和国产替代允许依据企业自述成立，但要审查产品边界、技术因果、产业环节和跨章节一致性。国外具体型号、客户证明或第三方检测只能增强可信度，不能被设为成立前提。

## 工作流

1. 确认项目层级、申请类型、地域、年度、申请书版本和当前通知。
2. 先列硬门槛。每项只能为通过、不通过、待补数据、待补证或待系统判断。
3. 建立 2026 质量评价输入清单，只判断资料是否完整、口径是否自洽，不自行赋分。
4. 记录平台质量分：
   - 已取得平台分数：写明分值、抓取或截图日期、来源定位和门槛比较。
   - 未取得：写“待平台评价”，总体结论只能为条件性或未确定。
5. 给出差距行动，按硬门槛、数据冲突、质量评价输入缺口、材料一致性排序。
6. 需要后期材料体检时交给 `sme-development-projects`，避免把预评估写成正式评审结论。

## 交付结构

默认交付结构化预评估表和聊天摘要：

1. 项目与政策版本；
2. 总体结论；
3. 硬门槛表；
4. 2026 质量评价输入清单；
5. 平台质量分状态；
6. 四项独立判断；
7. 数据冲突与证据缺口；
8. 优先行动。

结构化 `evaluation.quality_score` 必须使用以下二选一状态：

```json
{"status":"verified-platform-score","value":58,"source":"平台截图或导出记录"}
```

```json
{"status":"pending-platform-evaluation","value":null}
```

## 完成门禁

- 项目层级、申请类型、政策年份和表单版本已锁定；
- 新申报只使用 2026 规则，复核例外只按 2026 当期通知使用；
- 没有历史四维评分、内部百分制、三档总分或无来源估分；
- 平台质量分可回指来源，或明确保持待平台评价；
- 平台质量分待评价时没有给出“符合”“稳过”等确定性结论；
- 财务与经营数字均来自用户资料；
- 外部证明没有被设为进口替代主张成立的强制前提；
- 未承诺获批。
