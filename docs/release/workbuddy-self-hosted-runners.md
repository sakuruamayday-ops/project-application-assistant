# WorkBuddy 双宿主 Runner 运维要求

正式发布必须同时取得 macOS 与 Windows 的真实 WorkBuddy 安装证据。GitHub 仓库没有两台在线 Runner 时，受控发布命令会在创建预发布前失败，不会留下永久排队任务。

## 固定标签

| 宿主 | 必需标签 |
|---|---|
| macOS | `self-hosted`、`workbuddy`、`macos` |
| Windows | `self-hosted`、`workbuddy`、`windows` |

每组标签只登记一台空闲在线 Runner。受控发布会拒绝零台、多台、离线或忙碌状态。

## 宿主前提

- 安装当前支持版本的 WorkBuddy，并完成专用发布验收账号登录。
- 安装 Python 3、Git 与 GitHub CLI。
- Runner 以当前用户服务长期运行，开机自动启动。
- 不在 Runner 保存技能签名私钥；实机只验证 GitHub 预发布中的已签名成品。
- 不复制或上传 WorkBuddy 登录凭据。门禁只上传安装日志和不含密钥的宿主证据。
- Runner 使用专用操作系统账号，不承载客户资料。

## 登记与常驻

在 GitHub 仓库的 Settings → Actions → Runners 中分别创建两台自托管 Runner，严格使用上表标签。GitHub 生成的登记令牌是短期敏感值，只在对应宿主本机输入，不写入仓库、脚本、截图或日志。

完成官方登记步骤后：

- macOS 使用 GitHub Runner 自带的 `svc.sh install` 与 `svc.sh start`。
- Windows 使用配置向导安装为 Windows Service，并确认服务启动类型为自动。

维护者每天至少检查一次：

```bash
gh api repos/sakuruamayday-ops/project-application-assistant/actions/runners \
  --jq '.runners[] | {name,os,status,busy,labels:[.labels[].name]}'
```

## 发布时序

```text
版本与签名包一致性检查
  → 两台 Runner 在线且空闲
  → 创建 GitHub 预发布
  → macOS 真实 marketplace add → install → enable → Skill 触发
  → Windows 真实 marketplace add → install → enable → Skill 触发
  → 网站登记同一批文件与宿主证据
  → GitHub 预发布提升为正式 Latest
```

任一步失败时，网站不得登记新版本，GitHub 只保留预发布供排查，不得提升为正式版。
