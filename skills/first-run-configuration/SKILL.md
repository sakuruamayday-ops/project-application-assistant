---
name: first-run-configuration
description: 为企业全生命周期助手配置当前需要的知识库、企业数据、专利、浏览器、OCR 和文档能力，检测实际连接状态，形成脱敏能力报告并管理个人偏好继承。
---

# 首次配置

按本轮工具目录、已验签清单和连接状态使用现有能力。任务需要且当前缺少的能力进入对应配置；技能数量取清单与实际发现结果。团队门户负责账号知识服务，客户端连接管理器负责客户端连接。

## 能力与配置方法

1. 团队知识服务复用 `jiaotang-kb` MCP，升级后刷新原连接工具列表。实际调用 `knowledge_service_status` 或等价工具，以返回 `connected: true` 记录连接成功；待验证、读取成功和完整流程成功分别列示。
2. Word、PDF、Excel、PPT、OCR、网络和浏览器采用当前可调用工具。历史能力报告作参考，缺少任务所需能力时给出对应配置或替代路径，其他工作继续。
3. 外部供应商及本地诊断使用 `scripts/configure.py`，凭据通过宿主安全存储，报告和日志记录脱敏状态、配置项名称及实际失败恢复经过。
4. 经验复盘、技能策展、候选演化和治理能力按任务使用；持久偏好、日志、知识库、签名、安装及发布分别按用户要求和宿主权限处理。
5. 当前执行器网络受限时参考 `references/capability-delegation-protocol.md`，检查已授权的其他执行器；记录当前通道事实，供应商数据待取项保留缺口。
6. 个人长期习惯经用户保存要求，通过偏好接口写外部覆盖层并同步。同步失败说明保存状态，本轮任务照常执行；通用质量规则转候选维护流程。
7. 升级保留技能目录快照、原连接和偏好，恢复涉及本轮变更的配置。个人习惯迁移包含地区、格式、语气、归档和写作偏好；凭据、权限、来源和获批表述交对应接口审查。

检测及一次性提示参考 `references/first-startup-protocol.md`；继承参考 `references/preference-inheritance.md`。用户请求只读诊断时以读取和报告执行；初始化、连接更新及偏好保存按该次任务范围执行。

## 常用命令

```bash
python3 scripts/configure.py --non-interactive
python3 scripts/configure.py --skip-network
python3 scripts/configure.py --config-dir <用户配置目录>
```

用户要求初始化偏好时使用：

```bash
python3 scripts/configure.py --non-interactive --initialize-preferences
```

偏好同步、查看、修改、撤销和恢复：

```bash
python3 scripts/manage_preferences.py sync
python3 scripts/manage_preferences.py show
python3 scripts/manage_preferences.py set output.detail_level concise --sync
python3 scripts/manage_preferences.py undo
python3 scripts/manage_preferences.py reset
```

升级并输出继承及偏好候选报告：

```bash
python3 scripts/upgrade_inheritance.py --source <新版解压目录> --target <Agent的Skills目录> --version <版本号>
```

迁移个人习惯按用户要求增加 `--migrate-preferences`，需要同步既有习惯时运行 `python3 scripts/migrate_skill_preferences.py --sync`。

## 报告与服务入口

生成脱敏 `capabilities.json` 和 `首次配置检测报告.md`，按实际读取内容列输入标识、覆盖范围、调用状态及待验证项。身份、权限、凭据和云端数据访问由宿主及对应服务接口执行。

完整配置示例见 `docs/user-guide/api-mcp-configuration.md`。

- 团队知识库：团队管理员提供的注册网址。
- 企查查：[智能体数据平台](https://agent.qcc.com/invitation?code=3ZRZPHF7Q5MH4&ch=LINK_COPY)。
- 企策顾问：[aiqice.cn](https://aiqice.cn/)。
- 自进化评判：采用宿主 Agent，外部兼容模型 API 按需配置。
- 中国专利：[国家知识产权局专利检索及分析系统](https://pss-system.cponline.cnipa.gov.cn/)。
- 程序化专利检索：[欧洲专利局 OPS](https://www.epo.org/en/searching-for-patents/data/web-services/ops)。
