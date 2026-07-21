# 首次启动协议

本协议适用于把完整技能包放入Agent后的第一次对话。

1. 检查用户配置目录中的 `capabilities.json`。文件不存在或 `startup_protocol_version` 低于当前版本时，立即运行 `first-run-configuration`。
2. 启用 `experience-recorder`、`skill-curator`、`skill-evolution` 和 `evolution-governance`。自动能力仅包括脱敏记录、四问复盘、冲突诊断和候选优化；正式Skill修改、合并、归档和发布仍需审批。
3. 完成云端知识库及可选供应商能力检测，生成不含凭据的能力报告。
4. 仅在本协议首次完成时提醒用户输入：`帮我安装OCR、PDF、Word、PPT、Excel和联网检索这几个Skills`。
5. 进入 `project-application-assistant` 总入口。复杂任务结束时调用 `experience-recorder` 并实际回答四问；四问不得进入正式客户交付正文。
6. 将 `startup_protocol_version` 写入能力报告。以后更换模型或重启Agent时不重复首次提示；协议升级时重新执行新增步骤。

Skills没有统一安装钩子。Agent未自动触发时，应在发现本技能包且能力报告缺失的第一轮对话执行本协议。
