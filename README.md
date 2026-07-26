# 企业全生命周期助手

面向政府项目申报工程师与知识产权顾问的56项 Skills。团队知识库通过统一 API 或 MCP 读取，模型、企业数据、专利数据、OCR、文档和联网能力由用户所在 Agent 提供或自行配置。

## 当前状态

当前稳定版本为 V1.2。规则和技能采用原创重构，不包含受限制的第三方文档技能、客户密钥、账号登录态或付费平台原始数据库。

产品定位、后续演进范围和路线图见 [`docs/product/`](docs/product/README.md)。V1.2 的正式能力清单以 `skills/suite-manifest.json` 为准。

## 安装

1. 登录团队门户，在 Skills 管理中心打开“安装与设备”。
2. 生成一次性安全安装计划并粘贴给本地 Agent；先审查来源、本机改动和撤销方式，再明确确认执行。
3. 回到门户查看设备登记、凭据保存、签名验证和 MCP 首次连接结果。

仍可在“版本与下载”中获取最新版 ZIP 并手工导入，但网页不会伪装成能够直接拉起所有 Agent 客户端。

如果 Agent 不能直接识别 `SKILL.md`，请使用 Agent 提供的 Skill 导入或转换能力。完整步骤见 `docs/user-guide/企业全生命周期助手用户使用手册.md`。

## 健康检查

标准发布包会自动检查首次配置、自进化、四问复盘、云端知识检索、平台元数据和本机路径。维护者可运行：

```bash
PYTHONPATH=src:. uv run --with pytest --with pyyaml pytest -q tests
python3 scripts/build_standard_package.py --version 1.2 --status stable
```

## 配置

首次安装后由 `first-run-configuration` 自动运行；需要手动执行时使用：

```bash
python3 skills/first-run-configuration/scripts/configure.py
```

向导统一检测云端知识、企查查、专利数据、浏览器或网页能力、OCR和文档能力，并按宿主平台要求完成对应配置。

首次配置、云端API、企查查、专利数据、浏览器MCP、本地OCR和文档能力的完整步骤位于 `docs/user-guide/api-mcp-configuration.md`；供应商专项说明位于 `docs/config/`。

## 发布边界

- 不承诺企业一定符合或项目一定获批。
- 正式判断优先使用管理办法和当期官方申报通知。
- 无可靠数据时不推算企业财务。
- 不把审中专利视为授权成果。
- 成员政策规则保存在本地工作区，不允许写入团队云端知识库。
- 外部发送、云端上传和技能替换需要用户确认；自动归档不得覆盖原文件。

## 许可证

许可证待项目所有者在首次公开发布前确认。
