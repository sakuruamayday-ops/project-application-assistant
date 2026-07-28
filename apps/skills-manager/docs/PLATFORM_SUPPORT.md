# 平台适配依据

核对日期：2026-07-27。平台能力会变化，正式发布前需要重新核对。

| 平台 | 当前等级 | 管理方式 | 依据与边界 |
|---|---|---|---|
| WorkBuddy | 适配导入 | WorkBuddy 应用内插件市场 | 下载并验签跨平台本地市场 ZIP，解压后在 WorkBuddy 内用 `/plugin marketplace add` 添加，再安装 `jiaotang-workbuddy-skills@jiaotang`；不调用外部 CLI。 |
| TRAE中国版 | 完整同步 | `~/.trae-cn/skills` | TRAE官方中文社区技术支持说明项目级`.trae/skills`与全局`~/.trae-cn/skills`。国际版保留`~/.trae/skills`候选路径。 |
| Kimi Code | 完整同步 | `~/.agents/skills` | Kimi Code官方文档明确把`~/.agents/skills`列为用户级扫描目录，也支持`$KIMI_CODE_HOME/skills`。 |
| 通义灵码 | 引导导入 | 已验签包与人工指引 | 当前公开官方资料确认Agent和MCP能力，但本轮没有找到稳定的用户级`SKILL.md`目录或外部安装API，因此不自动写内部目录。 |
| Qoder | 适配导入 | 已验签包与平台复验 | 社区工具列出`.qoder/skills`，但本轮没有取得足以作为自动写入依据的官方稳定接口，暂不直接修改。 |
| Cherry Studio | 引导导入 | 官方界面选择已验签包 | 管理器只定位下载包，不写平台内部数据库或私有配置。 |

可核对来源：

- [Kimi Code Agent Skills](https://www.kimi.com/code/docs/en/kimi-code-cli/customization/skills.html)
- [Kimi Code Data locations](https://www.kimi.com/code/docs/en/kimi-code-cli/configuration/data-locations.html)
- [TRAE官方中文社区：Skills目录说明](https://forum.trae.cn/t/topic/67755)
- [TRAE Skills正式版说明](https://developer.volcengine.com/articles/7599882163568017451)
- [通义灵码官方帮助：规划智能体](https://help.aliyun.com/document_detail/3031471.html)
- [通义灵码官方更新：Agent与MCP](https://help.aliyun.com/zh/lingma/changelogs-of-202504)

“完整同步”只表示管理器有稳定、可审查的Skills安装入口，不表示不同平台的聊天记录、模型记忆、账号、MCP授权或私有设置可以互通。每次更新后仍需按平台新建会话，执行49项目录扫描与抽样调用验收。
