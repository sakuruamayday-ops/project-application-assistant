# MCP服务器配置

MCP由用户在宿主Agent平台自行配置。项目申报助手只检测可用工具，不代管用户MCP凭据。完整的stdio、HTTP、企查查、专利数据和浏览器配置步骤见 `docs/user-guide/api-mcp-configuration.md`。

## 配置项

- 连接方式：stdio、HTTP或平台支持的其他方式。
- 启动命令和参数。
- 工作目录。
- 环境变量名。
- 超时和重启策略。

## 最小权限

企业查询、政策检索和OCR默认只开放读取能力。外部发送、提交、覆盖和批量写入必须保留人工确认。成员政策规则只写用户本地 `project-rules/`，不通过MCP写入团队云端知识库。

## 验证

运行平台原生MCP状态检查，再运行项目自检。旧安装器仍可接受平台参数，但正式Skill不依赖平台专属适配：

```bash
project-assistant doctor --platform codex
```

将平台参数替换为 `claude-code` 或 `hermes`。

## 降级

单个MCP失败时禁用对应工具，保留纯文本分析和其他已连接能力。团队知识库MCP协议地址由团队网站与API配置一起生成。
