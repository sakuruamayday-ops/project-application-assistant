# 项目申报助手

面向政府项目申报工程师的 53 项平台无关 Skills。团队知识库通过统一 API 或 MCP 读取，模型、企业数据、专利数据、OCR、文档和联网能力由用户所在 Agent 提供或自行配置。

## 当前状态

当前稳定版本为 2.2.0。规则和技能采用原创重构，不包含受限制的第三方文档技能、客户密钥、账号登录态或付费平台原始数据库。

## 安装

1. 从团队管理员提供的下载地址获取最新版 ZIP。
2. 解压后，将 `skills` 文件夹拖入当前 Agent 支持的 Skills 目录或工作区。
3. 输入“请检查项目申报助手是否安装完整，并启动首次配置向导”。

项目不提供平台专属适配文件；不能直接识别 `SKILL.md` 的平台，应使用自身的 Skill 导入或转换能力。完整步骤见 `docs/user-guide/项目申报助手用户使用手册.md`。

## 健康检查

标准发布包会自动检查首次配置、自进化、四问复盘、云端知识检索、平台元数据和本机路径。维护者可运行：

```bash
PYTHONPATH=src:. uv run --with pytest --with pyyaml pytest -q tests
python3 scripts/build_standard_package.py --version 2.2.0 --status stable
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
