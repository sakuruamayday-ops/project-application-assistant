# Skills 原子升级与部署后审计

状态：正式执行

更新日期：2026 年 7 月 30 日

## 目标

本门禁解决五类发布后不可追溯问题：

1. 安装程序无论安装、覆盖、跳过还是回滚，都必须记录真实执行命令和逐项原因。
2. 正式提升前，本机 Codex Skills 必须与本次通用正式包一致。
3. 升级必须先暂存、验签，再整体替换；任一替换后步骤失败时恢复旧安装。
4. 开发目录、正式发布源和实际安装目录必须分离，并形成一份三方审计报告。
5. GitHub、知识门户和本机安装必须属于同一个签名发布事务；同一版本在任一时刻
   只能由一个 Codex 任务写入。

## 全局发布事务与跨任务租约

每次发布先生成规范化 JSON 清单，并用正式发布者 Ed25519 私钥签名。清单固定绑定：

- 版本、Git 标签、Git 提交和代码仓库；
- GitHub 必须出现的发布资产及 SHA-256；
- 门户通用包、WorkBuddy 包及 SHA-256；
- 安装端通用包 SHA-256、Skill 数量、发布者指纹和必须通过的三方审计结果。

门户 SQLite 是租约协调点，按版本保存事务哈希、持有任务、不可逆状态、到期时间和
各阶段证据。任务身份优先采用 `CODEX_THREAD_ID`，租约令牌只保存在权限为 `0600`
的本地凭证文件中，门户只保存令牌哈希。

同一版本已有有效租约时，其他任务不会上传、安装或提升，只返回
`read-only-monitor`。租约过期后，只允许另一任务接管完全相同的签名事务哈希；
版本相同但清单或包发生变化时直接阻断。已完成事务不可重新取得写权限。

状态只能按以下顺序推进：

```text
leased
  → github_staged
  → portal_staged
  → installing
  → installed
  → portal_published
  → github_published
  → completed
```

失败会记入 `failed` 状态与错误证据。持有同一签名事务的任务可重试；不得以同一
版本静默换包。原“同版本单独补发某一通道”的命令行入口已封闭，新增产物必须发布
新的补丁版本。

## 三层目录

| 层级 | 允许动作 | 禁止动作 |
|---|---|---|
| 开发目录 | 编辑、测试、重签前准备 | 作为实际运行安装目录 |
| 正式发布源 | 从签名通用 ZIP 解压到单次证据目录，只读验证 | 继续编辑或复用旧解压目录 |
| 实际安装目录 | 由原子升级器整体替换并供 Codex 运行 | 直接开发、局部手工覆盖、符号链接到开发目录 |

正式部署只能消费已签名通用包。WorkBuddy 包仍用于 WorkBuddy 插件市场，不作为
`~/.codex/skills` 的升级源。

## 门禁顺序

```text
签名通用包安全解压
  → 套件级 Ed25519 验签和逐文件 SHA-256
  → 以开发仓库公钥指纹作为信任锚
  → 正式包内全部 Skill 逐项验签
  → 开发源与正式包内容比对
  → 全套内容暂存并再次验签
  → 旧安装整体移动到备份目录
  → 暂存内容整体切换为当前安装
  → 安装目录全部 Skill 再次验签
  → 开发源、正式包、实际安装目录三方比对
  → 生成单一审计报告
```

任一步失败即返回非零退出码。替换事务尚未提交时发生异常，当前新安装会移动到
回滚证据目录，旧安装恢复原位；不永久删除任何文件。

## 防止在签名安装目录开发

成功安装后，签名 Skill 的文件和非可变目录会移除写权限。发布清单明确声明的
`mutable_paths` 会预先创建并保留写权限。安装器同时拒绝：

- 以 `~/.codex/skills` 或 `~/.agents/skills` 下的目录作为开发源或发布源；
- 开发源与安装目录相同或相互嵌套；
- 对已签名 Skill 使用符号链接安装；
- 正式部署源中出现未签名 Skill。

## 审计产物

默认审计位置：

- 安装执行流水：`~/.config/project-assistant/install-executions.jsonl`
- 单次升级报告：`~/.config/project-assistant/upgrade-reports/`
- 安装备份：`~/.config/project-assistant/install-backups/`
- 回滚证据：`~/.config/project-assistant/install-rollbacks/`
- 三方审计：`~/.config/project-assistant/deployment-audits/`

安装执行流水至少记录进程号、工作目录、完整参数数组、开发或发布源、安装目标、
是否强制覆盖、逐项跳过原因、事务终态及对应报告路径。参数以数组保存，不依赖
Shell 文本还原。

## 受控发布挂载点

`scripts/controlled_release.py --promote` 在主人独立确认后、网站正式提升和 GitHub
Latest 切换前，自动调用 `scripts/post_release_skill_gate.py`。受控发布必须同时
提供通用签名包；只有 WorkBuddy 包时不得正式提升。所有写操作还必须携带相同的
事务清单、签名、公钥和租约凭证。

只读监控命令：

```bash
python3 scripts/controlled_release.py \
  --version 1.4.1 \
  --monitor
```

该模式只读取门户事务和 GitHub Release，不要求发布包或私钥，也不会获取租约。

单独复核命令：

```bash
python3 scripts/post_release_skill_gate.py \
  --development-root skills \
  --release-archive dist/正式通用包.zip \
  --install-root ~/.codex/skills
```

该命令会执行真实升级，不是只读检查。正式发布预检和 `--stage` 阶段不会修改本机
Skills；只有带独立确认文字的 `--promote` 阶段执行。
