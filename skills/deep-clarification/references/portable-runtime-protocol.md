# 跨平台技能运行协议

## 使用技能

通过宿主技能入口导入签名包，按当前任务读取说明、模板和脚本，直接输出当前资料可完成的内容。资料缺口和实际执行情况随稿说明。客户端在启动及安装时验证整包签名和文件完整性；通用宿主通过其安装能力或随包自检工具验证发布者身份。

需要安装诊断、升级诊断或读取已授权个人偏好时，可按技能实际路径运行：

```bash
python3 <当前技能目录>/scripts/portable_skill_runtime.py prepare
```

`prepare` 检查安装签名与完整性，并读取外置偏好和版本记录。`pass` 表示检查通过；`limited` 表示已验签副本的部分运行依赖或偏好读写受限，使用当前可用能力并说明状态；`fail` 表示发布者、签名或文件完整性异常，将该副本隔离后通过可信渠道恢复。

独立客户端使用宿主已有整包验签结果。其他宿主按实际安装机制处理，兼容状态分别记录结构检查与真实执行证据。工具权限由宿主和当前系统用户权限管理，用户停止时结束后续操作。

## 个人偏好

当前任务的修订直接应用于本轮。用户明确要求记住、保存或持续采用某项习惯时，执行：

```bash
python3 scripts/portable_skill_runtime.py remember \
  --instruction '用户明确授权的长期偏好' \
  --scope default
```

随后用 `context` 中实际返回的 `preferences` 确认保存结果。诊断返回的 `active_preferences` 可作为已生效个人覆盖层；保存受限时明确本轮已应用、跨会话尚待保存。偏好持续遵循真实性和宿主的账号、成员隔离、系统凭据、包验签及回滚保护。

用户取消习惯时，用 `list` 定位后执行 `forget --id 偏好ID`，按原备份机制保留历史。

## 数据与升级

个人配置独立于官方技能包，存放在安装目录之外：

- macOS：`~/Library/Application Support/GongchuangResearchInstituteSkills/<skill-name>/`
- Windows：`%APPDATA%\GongchuangResearchInstituteSkills\<skill-name>\`
- Linux：`$XDG_CONFIG_HOME/gongchuang-research-institute-skills/<skill-name>/`

`GONGCHUANG_SKILL_DATA_DIR` 可指定托管目录。升级保留用户资料、外置偏好和凭据，配置变化按原机制备份。安装包、技能核心和个人数据分别保存，签名清单与发布者公钥用于核对安装真实性。
