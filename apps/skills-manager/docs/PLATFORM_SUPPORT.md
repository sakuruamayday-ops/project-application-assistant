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

## 远程适配器更新

管理器 `0.2.0` 起会在连接焦糖门户时读取平台适配器清单。清单只允许声明平台名称、能力等级、扫描路径、托管目录和固定导入模式，不允许携带命令、脚本、URL 或动态执行字段。

- 远程清单必须使用固定的 `jiaotang-skills-manager-platform-adapters` namespace 完成 Ed25519 验签。
- 公钥及 SHA-256 指纹固定在客户端内；签名、schema、最低管理器版本或字段白名单任一失败，立即回退到内置适配器。
- 每个已验签版本按 revision 保留在本地缓存，不覆盖历史版本。
- 扫描、适配器更新、导入和回滚结果追加到本机审计日志；令牌、bootstrap 和设备私钥字段自动脱敏。

这使平台安装目录发生变化时可以只更新适配器数据，无需重新发布整个客户端；如果平台要求新增可执行逻辑或超出既有导入模式，仍必须发布新客户端并重新走双端门禁。
