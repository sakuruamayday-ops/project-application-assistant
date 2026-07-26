# WorkBuddy 人工兼容反馈

项目不再运行 macOS、Windows 自托管 GitHub Runner。WorkBuddy 包继续执行静态安全、结构、签名、SHA-256 和本机可用宿主测试；跨平台实际安装情况由主人手动收集团队用户反馈。

## 反馈边界

- 不在技能包中加入遥测、回传脚本或后台连接。
- 不收集用户姓名、账号、设备密钥、访问凭据、客户资料和本地文件路径。
- “人工反馈成功”只代表对应用户报告完成安装、启用和技能触发，不等同于 GitHub OIDC 签名或自动实机证明。
- 没有反馈时显示“安装器已包含，等待人工反馈”，不得写成已验证兼容。
- 反馈失败时如实登记问题，不静默改成成功。

## 主人需要提供的信息

收到用户反馈后，至少记录：

1. 平台：macOS 或 Windows。
2. 系统版本。
3. WorkBuddy 版本。
4. 是否完成插件安装、启用和一次真实技能触发。
5. 失败时的报错原文或截图。
6. 反馈时间。

## 登记格式

```json
{
  "schema": "jiaotang-workbuddy-compatibility-feedback/v1",
  "release_tag": "V1.3",
  "collection_method": "owner-collected",
  "platforms": {
    "macos": {
      "status": "not-reported"
    },
    "windows": {
      "status": "reported-pass",
      "summary": "Windows 11、WorkBuddy 5.x 完成安装、启用和轻量技能触发",
      "reported_at": "2026-07-26T23:00:00+08:00"
    }
  }
}
```

`status` 只允许 `reported-pass`、`reported-fail` 或 `not-reported`。该文件只在主人提供反馈且明确发布时随受控发布命令登记；平时仅修改源码和记录，不生成签名或新版本。
