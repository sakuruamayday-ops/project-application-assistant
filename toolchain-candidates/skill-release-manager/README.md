# 发布工具链候选

`references/portable-runtime-notice.md` 是托管运行提示的唯一维护源。仓库刷新脚本读取此文件；`package-runtime-notice.patch` 让发布器读取相同文件，避免打包时重新生成另一版提示。

这是独立工具链变更候选，尚未应用到已安装、受保护的发布器。正式发布前须将补丁与该资源一起纳入发布工具链的受控更新，继续执行原有完整性、发布者、签名及来源校验。不得手改安装包或绕过校验。`portable-runtime-protocol.md` 的协议正文和签名代码均未更改。
