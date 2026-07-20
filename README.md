# 项目申报助手

面向政府项目申报工程师的跨平台技能包。模型API、MCP、企业数据、OCR、政策索引、知识库和飞书均由用户自行配置。

## 当前状态

项目处于首个公开开发版本。规则和技能采用原创重构，不包含受限制的第三方文档技能、客户报告、OCR归档、密钥或付费平台数据。

## 安装

```bash
./scripts/install-codex.sh
./scripts/install-claude-code.sh
./scripts/install-hermes.sh
```

首次安装后会生成详细的 `用户使用指南.md`。

## 健康检查

```bash
project-assistant doctor --platform codex
project-assistant doctor --platform claude-code
project-assistant doctor --platform hermes
```

## 配置

复制 `config/.env.example` 中需要的变量到安全的环境配置或系统钥匙串。不要把真实凭据提交到Git仓库。

供应商配置说明位于 `docs/config/`。

## 发布边界

- 不承诺企业一定符合或项目一定获批。
- 正式判断优先使用管理办法和当期官方申报通知。
- 无可靠数据时不推算企业财务。
- 不把审中专利视为授权成果。
- 外部发送、归档、规则发布和技能替换需要用户确认。

## 许可证

许可证待项目所有者在首次公开发布前确认。
