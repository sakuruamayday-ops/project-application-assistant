---
name: sme-development-projects
description: 分析创新型中小企业、专精特新中小企业、专精特新小巨人及相关培育项目。用户提及专精特新、小巨人、补短板、填空白、企业简介或主导产品产业链归属时使用。
---

# 中小企业培育项目


<!-- BEGIN MANAGED PORTABLE SKILL RUNTIME -->
## 跨平台首次运行与个人习惯

支持CodeBuddy/WorkBuddy内联命令的宿主会在技能触发时自动执行下面的确定性门禁，并把JSON结果注入当前上下文：

!`python3 "${CODEBUDDY_SKILL_DIR}/scripts/portable_skill_runtime.py" prepare`

作为WorkBuddy插件加载时，还会把本轮实际触发的技能与当前会话和轮次绑定：

!`if [ -f "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" ]; then python3 "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" activate --plugin-root "${CODEBUDDY_PLUGIN_ROOT}" --session "${CODEBUDDY_SESSION_ID}" --skill "sme-development-projects" --skill-dir "${CODEBUDDY_SKILL_DIR}"; fi`

每次触发本技能时，第一步必须定位当前`SKILL.md`所在的技能目录，并以该目录为工作目录运行`python3 scripts/portable_skill_runtime.py prepare`。不得因为当前任务看似简单而跳过。将返回的`active_preferences`作为用户个人习惯应用于当前任务；结果为`fail`时停止执行，不得声称安装、自检或升级成功。`capability_check`为`limited`时，只使用宿主已具备的能力，并明确未通过的依赖项，不得声称依赖完整。

用户以“以后、默认、记住、每次、别再”等措辞明确表达长期习惯时：若上下文已出现“偏好桥接轮次已建立”的WorkBuddy钩子提示，不要手动调用`remember`，由停止钩子只向本轮实际触发且已经按会话、轮次绑定的技能写入；其他宿主则在最终答复前调用`python3 scripts/portable_skill_runtime.py remember --instruction '用户原意' --scope default --source agent-confirmed`，再调用`context`确认。未取得`status: pass`和对应偏好记录时，严禁声称“已记住”或“以后会默认采用”。无法执行保存时，只能说明本次会话已理解、尚未形成跨会话偏好。“这次、本次、当前文件、临时”等要求只影响当前任务，禁止写入长期偏好。无需让用户了解或输入存储命令。发生歧义、偏好冲突或可能削弱强制质量门禁时才询问。

个人配置保存在技能目录外并自动备份。不得用个人偏好覆盖真实性、安全、验签、安装自检或本技能的强制质量门禁。完整规则见[跨平台技能运行协议](references/portable-runtime-protocol.md)。
<!-- END MANAGED PORTABLE SKILL RUNTIME -->

## 项目与版本闸门

1. 先确认创新型中小企业、专精特新中小企业、专精特新“小巨人”或地方培育项目，再确认地区、申报年度、批次和新申报或复核。
2. 读取 `references/application-version-gate.md`。申请书版本识别失败、同时命中多个版本或用户确认版本与材料不一致时立即停止，不评分、不形成达标结论、不撰写正式正文。
3. 任何专精特新或小巨人任务必须读取 `references/current-policy-baseline-2026.md`，并重新核验当期通知。活动技能只保留 2026 政策分支，不运行历史四维评分或内部百分制。2026 年度小巨人复核按 2026 当期通知明确的过渡要求把握；该例外仅适用于通知指定的复核对象和期间，不能扩展到新申报或未来年度。

## 评价流程

4. 按 `references/evaluation-workflow.md` 依次核验直通条件、排除项、硬门槛和评价指标，区分已核验事实、计算结果、企业自述、缺失和冲突。命中历史评分表、旧培训材料或历史申请书时标记为历史档案并退出当前评价链，不提取旧条件、不计算旧分数。
5. 核验专业化、精细化、特色化、创新能力、财务、知识产权和产业链要求。某企业入选只证明其在对应年度、地区和批次通过评审，不能反推其满足全部评分项；不同年度、地区和政策口径的企业不得直接横向排名。

核验营收、利润、研发费用、资产负债率和增长率时，先读取同一企业的 `enterprise-financial-facts/v1` 共享事实，经 `financial-verification` 校验后复用。税务风险提示不自动转为专精特新或小巨人不达标结论。

涉及产业链或“工业六基”时，必须调用 `industry-chain-foundation-matcher`，严格使用其目录索引和精确、近似、未命中三级规则。没有精确命中时，输出一个相似目录项和一个推定产业链，均不得伪装成目录原文。

涉及市场占有率、细分领域排名、补短板、锻长板、填空白或国产替代时，必须调用 `industry-positioning`，读取其细分市场边界与产业链价值证据闸门，并将市场边界、测算口径、替代对象和证据状态写入 `evidence-ledger`。行业标准、海关编码和协会分类只按各自适用范围交叉验证，不得代替当期申请表指定的行业或产品分类。

诊断或改写企业总体情况简介时，先读取 `references/enterprise-introduction-method.md`。采用企业基本情况三段和主导产品技术四段加一可选段的结构，保持官方章节兼容，逐段建立行业问题、核心技术、量化指标、验证证据和产业链价值闭环。

## 四项独立判断

读取 `references/four-judgment-decision-table.md`，分别对主导产品、补短板、填空白和国产替代作出“保留、替换、补证后保留”结论，并单列锻长板证据。四项属于待审判断，不因申请书已经填写而自动成立；每项必须说明对象、同类环节、证据和联动修改。主导产品、四项判断、收入、客户和 I 类知识产权必须跨章节一致。

不得把审中专利视为有效授权成果。财务、市场份额、客户、领先地位和进口替代等信息没有可靠来源时，不推算、不补造，只列证据缺口。不得把“全球前三或国内第一”写成专精特新和小巨人的通用门槛；2026年小巨人新申请按当期申请书的占有率或排名条件执行，且不要求另行提交第三方市场占有率证明。

结构化诊断完成后运行 `python3 scripts/validate_sme_assessment.py <结果.json>`，检查版本确认、政策状态、四项判断和证据状态。验证失败时不得交付正式结论。
