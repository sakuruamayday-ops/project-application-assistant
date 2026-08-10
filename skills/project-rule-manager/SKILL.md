---
name: project-rule-manager
description: 在用户本地工作区管理不同省市区县的政府项目规则、年度版本、官方来源和核验状态。用于团队成员自行录入、更新、比较、撤回或读取项目门槛、评分、材料、截止日期、主管部门和来源文件；不向团队云端知识库写入成员修改。
---

# 本地项目规则管理


<!-- BEGIN MANAGED PORTABLE SKILL RUNTIME -->
## 便携运行门禁

!`python3 "${CODEBUDDY_SKILL_DIR}/scripts/portable_skill_runtime.py" prepare`

!`if [ -f "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" ]; then python3 "${CODEBUDDY_PLUGIN_ROOT}/scripts/workbuddy_preference_bridge.py" activate --plugin-root "${CODEBUDDY_PLUGIN_ROOT}" --session "${CODEBUDDY_SESSION_ID}" --skill "project-rule-manager" --skill-dir "${CODEBUDDY_SKILL_DIR}"; fi`

每次触发先执行`prepare`并应用`active_preferences`；`fail`时停止，`limited`时按已具备能力降级。长期习惯只按协议写入，临时要求不持久化；偏好不得覆盖真实性、安全、验签和质量门禁。完整规则见[便携运行协议](references/portable-runtime-protocol.md)。
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
