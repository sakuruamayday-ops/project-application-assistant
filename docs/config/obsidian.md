# Obsidian配置

用途：按用户确认将政策、企业分析、申报报告、模板和项目记录归档到Obsidian Vault。

官方帮助：[Obsidian Help](https://help.obsidian.md/)。

## 配置

在 `config/common.yaml` 设置：

```yaml
providers:
  obsidian:
    enabled: true
    vault_path: /absolute/path/to/your/vault
    require_archive_confirmation: true
```

建议目录：

```text
项目申报/
├── 企业/
├── 项目/
├── 政策/
├── 报告/
└── 模板/
```

## 验证

检查Vault路径存在且可写，再创建一个不含客户数据的测试笔记。未经用户确认不得归档真实任务。

## 冲突与撤销

同名文件使用日期或版本后缀，不覆盖用户个人备注。停用时将 `enabled` 改为 `false`；不自动删除已有笔记。

