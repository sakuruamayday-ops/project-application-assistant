# MCP服务器配置

MCP由用户在Codex、Claude Code或Hermes中自行配置。项目申报助手只检测可用工具，不代管用户MCP凭据。

## 配置项

- 连接方式：stdio、HTTP或平台支持的其他方式。
- 启动命令和参数。
- 工作目录。
- 环境变量名。
- 超时和重启策略。

## 最小权限

企业查询、政策检索和OCR默认只开放读取能力。外部发送、提交、删除、覆盖和批量写入必须保留人工确认。

## 验证

运行平台原生MCP状态检查，再运行：

```bash
project-assistant doctor --platform codex
```

将平台参数替换为 `claude-code` 或 `hermes`。

## 降级

单个MCP失败时禁用对应工具，保留纯文本分析和其他已连接能力。

