# 团队云端知识与本地规则配置

团队资料默认通过云端REST API读取，不再要求成员挂载本地知识库。成员自行增改的地区政策保存在当前工作区 `project-rules/`，不上传或覆盖团队云端资料。

## 配置

普通成员登录门户后点击“一键安装”，再把整段文字粘贴到当前 WorkBuddy。Agent 自动安装或更新 50 项 Skills、启用最小行为 Hook、只替换用户配置中的 `mcpServers.jiaotang-kb`、保留其他 MCP，并在一次重载后完成连接验证。成员不需要到其他页面寻找 Token，也不需要手工编辑 JSON。

管理员账号属于设备限制豁免账号，可继续使用门户提供的管理员 API Key。

## 索引规则

- 登录用户打开手工配置页时，网站复用已有有效个人 Token；不存在或已撤销时才生成新 Token。
- Token 只出现在当前用户的手工配置页和一键安装指令中，页面使用 `Cache-Control: private, no-store`，普通日志不得记录完整 Token。
- Token 会明文保存在当前用户的 WorkBuddy MCP 配置中；怀疑泄露时撤销旧 Token，下次打开配置页自动生成新值。
- 云端命中必须保留文档ID、原文件路径和来源。
- 本地规则必须保留来源、版本和修改审计。
- 命中政策和案例后回到原文件或政府官方来源核验。

## 验证与降级

安装后执行 `tools/list`，确认 `knowledge_search`、`knowledge_document`、`knowledge_service_status` 全部出现，再实际调用 `knowledge_service_status`；只有返回 `connected: true` 才算完成。云端不可用时使用用户本地规则、当前会话文件和政府官方来源，并明确当前检索层不可用。
