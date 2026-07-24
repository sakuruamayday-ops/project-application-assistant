# 跨平台技能运行协议

## 用户体验

用户只执行两类自然动作：

1. 在宿主平台的技能上传入口导入或覆盖新版技能包。
2. 用自然语言说明长期习惯或当前任务要求。

不得要求普通用户输入`local-overrides`、哈希、签名或迁移命令。

## 首次运行与升级

每次技能触发时先运行：

```bash
python3 scripts/portable_skill_runtime.py prepare
```

对于支持Skill内联Shell命令的CodeBuddy/WorkBuddy，统一发布组件同时注入以下宿主适配门禁，使检查在技能内容交给模型前确定性执行：

```markdown
!`python3 "${CODEBUDDY_SKILL_DIR}/scripts/portable_skill_runtime.py" prepare`
```

其他宿主继续由Agent按技能首步指令调用同一脚本。内联命令属于宿主适配方式，不改变跨平台运行时、外置个人配置和签名核心。

统一发布器采用双产物模式：通用技能ZIP用于支持完整技能目录的宿主；WorkBuddy插件包额外包含插件描述、`SessionStart`、`UserPromptSubmit`、`Stop`钩子和偏好桥接器。两类产物独立签名，不能用通用ZIP的签名替代插件包验签。

该命令幂等执行安装完整性检查、识别版本变化、初始化或迁移外置个人配置、备份旧配置，并返回当前有效偏好。若结果为`fail`，停止使用该安装副本。

发布包内置签名清单和发布公钥。首次成功运行时记录发布公钥指纹，后续升级自动要求发布者指纹一致；签名或指纹不一致时停止使用新版。该机制采用首次使用信任，首次安装仍应来自发布者确认的官方渠道。

宿主平台不允许执行Python时，明确标记为受限模式：可以使用`SKILL.md`、参考文件和资产，但不得声称已经完成自动自检、偏好持久化或版本迁移。

## 自然语言偏好

将以下表达视为明确的长期偏好信号：

- 以后、今后、默认、记住、每次、一律、以后都；
- 别再、不要再、始终、固定采用；
- 用户明确说明“这是我的习惯”。

将以下表达视为仅对当前任务生效：

- 这次、本次、这一份、当前文件、临时、先；
- 仅针对当前客户、当前材料或当前版本的修改。

在通用技能ZIP模式下，明确属于长期偏好时，在完成当前任务后自动运行：

```bash
python3 scripts/portable_skill_runtime.py remember \
  --instruction '用户的自然语言偏好' \
  --scope default
```

随后运行`context`复核；只有新偏好已经出现在返回的`preferences`中，才能向用户确认已经形成跨会话习惯。不得用自然语言承诺代替持久化结果。无法执行保存时，只能说明本次会话已理解、尚未形成跨会话偏好。

在WorkBuddy插件模式下：

1. `UserPromptSubmit`读取宿主提供的真实`session_id`，为本轮生成`turn_id`，并在进入模型前校验插件发布清单、哈希和签名。
2. 每个被Skill工具实际加载的技能通过内联命令登记`skill_name`，不得依据用户文字猜测技能归属。
3. `Stop`只在提示属于长期偏好时，把原始要求写入本轮已登记技能；一次性要求不写入。
4. 每条偏好来源保留`session_id`和`turn_id`。多个技能同轮触发时分别写入各自配置，形成`session_id + turn_id + skill_name`三重绑定。
5. 已出现“偏好桥接轮次已建立”提示时，Agent不得再手动调用`remember`，避免宿主自由发挥改变归属或来源。

不要要求用户说出保存命令，也不要在每次保存前机械确认。只有长期性不明确、与既有偏好冲突或可能影响强制质量门禁时才询问。

每次任务均以`prepare`返回的`active_preferences`作为个人覆盖层。个人偏好不得覆盖安全规则、真实性要求、发布验签、安装自检、强制质量门禁或法律法规。

用户表达“取消以前的某项习惯”时，先运行`list`定位偏好ID，再运行`forget --id 偏好ID`。保留历史备份，不永久删除。

## 数据位置

个人配置默认保存在技能安装目录之外：

- macOS：`~/Library/Application Support/JiaotangSkills/<skill-name>/`
- Windows：`%APPDATA%\JiaotangSkills\<skill-name>\`
- Linux：`$XDG_CONFIG_HOME/jiaotang-skills/<skill-name>/`

可用环境变量`JIAOTANG_SKILL_DATA_DIR`统一改到企业托管目录。外置配置不进入官方ZIP，不使用发布私钥签名，并在每次变化前自动备份。

WorkBuddy桥接状态默认保存在同一平台配置根下的`_workbuddy/<plugin-name>/`。测试或企业托管可用`JIAOTANG_WORKBUDDY_PLUGIN_DATA`改到隔离目录。不得依赖WorkBuddy 5.3.3未稳定展开的`${CODEBUDDY_PLUGIN_DATA}`占位符。

## 平台边界

本协议能保证运行时被调用后的完整性自检、内置清单验签和个人配置迁移。WorkBuddy插件在`UserPromptSubmit`阶段完成提示前验签，篡改时阻断本轮；技能触发后再执行单技能安装自检。其他宿主若只把`SKILL.md`作为模型提示，则调用仍取决于Agent遵循指令的能力。只有宿主平台提供“导入前安装钩子”或已安装可信引导器时，才能在平台读取新技能指令前完成验签和核心回滚。

未经过目标平台实测时，只能标注“结构兼容”；完成导入、脚本执行、资产访问、偏好保持和覆盖升级测试后，才可标注“已验证兼容”。
