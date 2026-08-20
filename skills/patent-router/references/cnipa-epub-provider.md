# 国知局公布公告首轮检索提供器

## 定位

`scripts/cnipa_epub_search.py` 是中国专利首轮发现适配器。它通过受控 Chromium 打开国家知识产权局专利公布公告查询入口，按短技术词检索并输出 `cnipa-epub-discovery/v1`。它不是全文、法律状态或查新结论提供器。

中国专利检索的提供器顺序固定为：

1. 国知局公布公告适配器：发现题名、公开号、结果页摘要及页面提供的公布日线索。
2. 国知局详情页或其他对应法域官方原文：复核公开日、说明书、权利要求、附图和著录项目。
3. 必要时使用 Google Patents、WIPO、EPO 或商业数据库做外国文献、同族、引证和全文补全；不得把它们写成中国专利首轮默认入口。

## 使用

先从 `patent-search-plan/v2` 选择 1 至 8 个脱敏短技术词，再运行：

```bash
python3 scripts/cnipa_epub_search.py --type invention 知识图谱 图数据库
```

默认每个词在交互失败后重试一次，并在 `browser_policy` 中记录 `attempts_total` 与 `retry_failures`。可用 `--retry-count` 和 `--retry-delay-seconds` 调整；重试耗尽仍返回 `INTERACTION_REQUIRED`，不能降格为零命中。

可选类型为 `all`、`invention`、`utility_model`、`design`。安装可选运行依赖：

```bash
python3 -m pip install -r requirements-cnipa.txt
python3 -m playwright install chromium
```

本机已安装正式 Chrome 时可尝试 `--browser-channel chrome`。默认 `--browser-mode cnipa-compatible` 与经审计的上游实现一致，设置桌面浏览器 UA，并启动 Chromium 参数 `--disable-blink-features=AutomationControlled`，用于通过国知局对普通浏览器能力的前置识别。运行回执必须公开记录该模式。需要诊断时可用 `--browser-mode strict` 禁用这两项兼容设置。

离线解析已保存的结果页用于回归：

```bash
python3 scripts/cnipa_epub_search.py --input-html <结果页.html> 离线样例
```

## 证据边界

- 所有记录默认 `evidence_stage=discovery`、`prior_art_eligible=false`、`legal_status=无法确认`。
- 结果页摘要即使完整显示，也不代替说明书、权利要求和附图原文。
- 公开日、优先权日、申请人、权利人和法律状态必须按任务基准日回到对应官方原文复核。
- 未完成原文定位前，不得把题名、摘要或语义相似写成“已公开全部必要技术特征”。
- 零结果只表示本次词项、类型、时间和页面可达范围内未命中。

## 安全与降级

- 当前入口为 HTTP，只发送脱敏短技术词；不得发送未公开交底、整段权利要求、实施例参数、客户名称、联系人、手机号、身份号码或商业秘密。
- 国知局兼容模式会设置桌面浏览器 UA 并关闭 `AutomationControlled` 标记，这是实现自动检索的显式兼容条件；输出中的 `browser_policy` 必须记录实际模式。
- 脚本始终保留 Chromium 沙箱，不复用用户日常浏览器配置，不破解图形、滑块、短信或登录验证。
- 出现验证码、交互门禁、页面结构变化或超时，返回 `INTERACTION_REQUIRED`；可用 `--headed` 让用户在官方页面自行交互，或转人工官方检索，不得绕过。
- 缺少 Playwright 或浏览器时返回 `PROVIDER_UNAVAILABLE`，不把依赖缺失写成“无结果”。

## 上游来源与许可

页面路由、复选框映射、新版 `div.item` 结果结构、桌面 UA 和 `AutomationControlled` 兼容参数参考 `Abluecat/patent-disclosure-skill` 的国知局 ePub 模块，固定审计提交为 `ff43eb798c3fbde5fd22a532aed8fb62930851ce`，许可证为 MIT。候选实现已重写并移除该项目中的 `--no-sandbox`、Google PDF 默认链路、明文配置和壳层执行。完整署名见 `THIRD_PARTY_NOTICES.md`。
