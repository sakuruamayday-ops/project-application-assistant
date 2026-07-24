---
name: project-rule-manager
description: 在用户本地工作区管理不同省市区县的政府项目规则、年度版本、官方来源和核验状态。用于团队成员自行录入、更新、比较、撤回或读取项目门槛、评分、材料、截止日期、主管部门和来源文件；不向团队云端知识库写入成员修改。
---

# 本地项目规则管理


<!-- BEGIN MANAGED PORTABLE SKILL RUNTIME -->
## 跨平台首次运行与个人习惯

支持CodeBuddy/WorkBuddy内联命令的宿主会在技能触发时自动执行下面的确定性门禁，并把JSON结果注入当前上下文：

!`python3 "${CODEBUDDY_SKILL_DIR}/scripts/portable_skill_runtime.py" prepare`

作为WorkBuddy插件加载时，还会把本轮实际触发的技能与当前会话和轮次绑定：

!`if [ -f "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" ]; then python3 "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" activate --plugin-root "${CODEBUDDY_PLUGIN_ROOT}" --session "${CODEBUDDY_SESSION_ID}" --skill "project-rule-manager" --skill-dir "${CODEBUDDY_SKILL_DIR}"; fi`

每次触发本技能时，第一步必须定位当前`SKILL.md`所在的技能目录，并以该目录为工作目录运行`python3 scripts/portable_skill_runtime.py prepare`。不得因为当前任务看似简单而跳过。将返回的`active_preferences`作为用户个人习惯应用于当前任务；结果为`fail`时停止执行，不得声称安装、自检或升级成功。`capability_check`为`limited`时，只使用宿主已具备的能力，并明确未通过的依赖项，不得声称依赖完整。

用户以“以后、默认、记住、每次、别再”等措辞明确表达长期习惯时：若上下文已出现“偏好桥接轮次已建立”的WorkBuddy钩子提示，不要手动调用`remember`，由停止钩子只向本轮实际触发且已经按会话、轮次绑定的技能写入；其他宿主则在最终答复前调用`python3 scripts/portable_skill_runtime.py remember --instruction '用户原意' --scope default --source agent-confirmed`，再调用`context`确认。未取得`status: pass`和对应偏好记录时，严禁声称“已记住”或“以后会默认采用”。无法执行保存时，只能说明本次会话已理解、尚未形成跨会话偏好。“这次、本次、当前文件、临时”等要求只影响当前任务，禁止写入长期偏好。无需让用户了解或输入存储命令。发生歧义、偏好冲突或可能削弱强制质量门禁时才询问。

个人配置保存在技能目录外并自动备份。不得用个人偏好覆盖真实性、安全、验签、安装自检或本技能的强制质量门禁。完整规则见[跨平台技能运行协议](references/portable-runtime-protocol.md)。
<!-- END MANAGED PORTABLE SKILL RUNTIME -->

将每位用户维护的规则保存到当前工作区 `project-rules/`，区分 `draft`、`candidate`、`verified`、`stale`、`superseded` 和 `withdrawn`。团队云端知识服务对普通成员保持只读；本地规则不会自动上传、共享或覆盖云端资料。

## 本地目录

```text
project-rules/
└── <省>/<市>/<区县或省级>/
    └── <项目标准名称>/
        ├── rule.yaml
        ├── sources/
        ├── versions/
        └── audit.jsonl
```

- `rule.yaml` 保存当前结构化规则、适用地区、年度、文号和核验状态。
- `sources/` 保存用户提供的政策原文、官方链接清单或可验证网页存档。
- `versions/` 保存每次变更前的规则与来源快照。
- `audit.jsonl` 追加记录修改时间、修改字段、旧值、新值和来源变化，不记录密码、Cookie或Token。

## 规则

1. 管理办法、实施细则、当期通知、公示名单和废止依据分别记录并建立关联。
2. 每条门槛保留来源文件、官方URL、页码或原文位置；用户可以更换来源，但旧来源必须进入版本快照。
3. 数字、日期、主管部门、适用地区和口径变化生成差异，不静默覆盖。
4. 用户新增或模型提取的内容先保存为 `candidate`；用户对照政府原文确认后才能标记 `verified`。
5. 用户要求删除时改为 `withdrawn` 并移动到本地撤回区，不永久删除原文、历史版本或审计记录。
6. 新文件替代旧文件时记录替代依据、旧文件状态和新旧规则差异。
7. 正式项目判断优先读取用户当前地区的本地 `verified` 规则，再查询团队云端知识和政府官方来源；发生冲突时保留差异并以最新官方原文为准。
8. 普通成员不得调用管理员上传接口，也不得通过本Skill修改团队云端知识库。

## 地区配置

首次使用时要求用户设置一个或多个默认地区，例如 `江苏省/苏州市/吴中区`。检索顺序为区县、市、省、国家，不加载无关兄弟区县。用户切换地区时只切换当前检索范围，不删除其他地区规则。

## 降级处理

- 宿主允许文件写入时直接维护上述目录。
- 宿主不允许文件写入时生成完整的 `rule.yaml`、来源清单和变更记录供用户下载，不声称已完成本地保存。
- 云端API不可用时仍可读取本地规则，但动态日期、申报状态和废止情况必须回政府官方来源核验。
