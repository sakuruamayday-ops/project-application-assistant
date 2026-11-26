# 团队云端与本地法规检索

## 检索顺序

1. **优先已连接知识库 MCP**：若宿主已连接知识库 MCP，优先调用 `policy_search`、`knowledge_search` 检索法规与政策，关键条目务必调用 `knowledge_document` 回读完整原文；核验企业身份与历史认定调用 `enterprise_identity_lineage_lookup`、`authoritative_list_search`、`public_list_search`、`recognition_search`。
2. **本机只读库兜底**：未连 MCP 但本机存在本地法规/企业库时，通过 `scripts/check_company_law.py search-law` 或本地库脚本直接查询。
3. **直连 API 或公开官方来源**：上述均不可用时，若用户自行配置了安全环境变量 `KB_API_ENDPOINT`、`KB_API_TOKEN`，可按 `GET /v1/me` 与 `POST /v1/search` 调用；零配置单机环境下直接查制定机关官方公开来源。
4. 关键命中须核对完整原文与来源路径，未命中如实写“当前检索层未命中”并继续可完成部分。

## 云端调用

- 直接使用原生知识工具，按实际状态处理具体缺项。
- 原生知识能力受限时，复用用户已配置并授权的直接 API；从安全环境变量读取 `KB_API_ENDPOINT`、`KB_API_TOKEN`，以 `GET /v1/me` 核验连接，再用 `POST /v1/search`。
- Token 由安全配置和本地鉴权机制管理，输出使用脱敏结果。
- 未命中如实写“当前检索层未命中”，继续查适用官方来源。

## 版本纪律

- 云端命中仍须读取完整文档并确认来源；关键法律结论继续回到制定机关官方原文。
- 仅命中文件名或摘要时打开完整文档。
- 正式现行文件作为结论依据，历史申报书、培训和评分参考表用于线索及比较。
- 含失效、废止、取消、历史版本字样的材料作为沿革参考。
