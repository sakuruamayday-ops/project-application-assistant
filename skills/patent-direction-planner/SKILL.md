---
name: patent-direction-planner
description: 根据企业真实主营业务、产品、工艺、研发资料和现有专利，规划可实施的专利方向，并动态匹配企业所在地知识产权保护中心的备案条件、产业领域、IPC分类号及优先审查路径。用户询问某客户能写哪些专利、如何匹配本地预审优审或如何挖掘专利方向时使用。
---

# 专利方向规划


<!-- BEGIN MANAGED PORTABLE SKILL RUNTIME -->
## 跨平台首次运行与个人习惯

支持CodeBuddy/WorkBuddy内联命令的宿主会在技能触发时自动执行下面的确定性门禁，并把JSON结果注入当前上下文：

!`python3 "${CODEBUDDY_SKILL_DIR}/scripts/portable_skill_runtime.py" prepare`

作为WorkBuddy插件加载时，还会把本轮实际触发的技能与当前会话和轮次绑定：

!`if [ -f "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" ]; then python3 "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" activate --plugin-root "${CODEBUDDY_PLUGIN_ROOT}" --session "${CODEBUDDY_SESSION_ID}" --skill "patent-direction-planner" --skill-dir "${CODEBUDDY_SKILL_DIR}"; fi`

每次触发本技能时，第一步必须定位当前`SKILL.md`所在的技能目录，并以该目录为工作目录运行`python3 scripts/portable_skill_runtime.py prepare`。不得因为当前任务看似简单而跳过。将返回的`active_preferences`作为用户个人习惯应用于当前任务；结果为`fail`时停止执行，不得声称安装、自检或升级成功。`capability_check`为`limited`时，只使用宿主已具备的能力，并明确未通过的依赖项，不得声称依赖完整。

用户以“以后、默认、记住、每次、别再”等措辞明确表达长期习惯时：若上下文已出现“偏好桥接轮次已建立”的WorkBuddy钩子提示，不要手动调用`remember`，由停止钩子只向本轮实际触发且已经按会话、轮次绑定的技能写入；其他宿主则在最终答复前调用`python3 scripts/portable_skill_runtime.py remember --instruction '用户原意' --scope default --source agent-confirmed`，再调用`context`确认。未取得`status: pass`和对应偏好记录时，严禁声称“已记住”或“以后会默认采用”。无法执行保存时，只能说明本次会话已理解、尚未形成跨会话偏好。“这次、本次、当前文件、临时”等要求只影响当前任务，禁止写入长期偏好。无需让用户了解或输入存储命令。发生歧义、偏好冲突或可能削弱强制质量门禁时才询问。

个人配置保存在技能目录外并自动备份。不得用个人偏好覆盖真实性、安全、验签、安装自检或本技能的强制质量门禁。完整规则见[跨平台技能运行协议](references/portable-runtime-protocol.md)。
<!-- END MANAGED PORTABLE SKILL RUNTIME -->

先使用 `patent-data-foundation` 核验企业现有专利，再使用 `patent-search-core` 检查方向拥挤度。

## 工作流

1. 收集企业真实产品、工艺、设备、材料、检测、控制和研发证据。
2. 将技术链拆成可独立实施的专利主题，不为进入预审虚构技术。
3. 读取 [preexamination-rules.md](references/preexamination-rules.md)，定位企业所在地保护中心。
4. 运行时获取最新版备案条件、产业领域和IPC分类号目录，并记录来源、生效日期和核验日期。
5. 使用最新版IPC定义核验技术方案与分类号的实质对应关系。
6. 分别评估预审、优先审查和普通申请路径。
7. 对每个方向输出真实研发基础、拟保护对象、分类候选、预审匹配度、拥挤度、取证难度和优先级。

## 目录更新

- 运行 `scripts/update_preexamination_catalogs.py` 检查官方页面和附件变化，严格校验证书，不绕过TLS错误。
- 默认登记浙江省、杭州、宁波、温州、嘉兴和绍兴保护中心；新增中心时扩展 `references/preexamination-sources.json`。
- 保存官方页面哈希、附件哈希、核验时间和可解析的IPC及洛迦诺分类号；无法读取附件时标记待人工核验，不沿用旧目录冒充最新目录。

## 不确定性处理

保护中心公开目录不能代表全部内部受理尺度。输出必须说明“公开目录匹配不等于受理”，并建立实际预审反馈记录，用脱敏后的退件原因持续校正规则，但不得把个案经验写成官方规则。
