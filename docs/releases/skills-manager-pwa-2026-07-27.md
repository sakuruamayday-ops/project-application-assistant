# 焦糖 Skills 管理器 PWA 正式发布

状态：已于2026年7月27日23:58北京时间正式发布。

生产部署ID：`20260727235850`

## 本次发布

- 门户新增 `/skills-manager`，以HTTPS PWA作为当前可正式交付的macOS与Windows双端Skills管理入口。
- 通用Skills、WorkBuddy macOS、WorkBuddy Windows继续使用独立发布通道；Windows热修复不会推动macOS强制更新。
- 修复Windows单端热修复后macOS下载入口错误显示“当前版本未包含”的问题。
- 同步前检查安全上下文、WebCrypto、ZIP解压、目录授权和可恢复替换能力；能力不足时只提供校验后下载。
- 未托管同名路径会阻断写入；更新前建立目录内恢复点，回滚不永久删除当前版本。
- 用户名所在页面不进入Service Worker缓存，API与下载请求不离线缓存。

## 发行证书边界

- 本次不发布Electron原生安装包，不要求用户绕过Gatekeeper、SmartScreen或未知发布者警告。
- 原生客户端必须取得Apple Developer ID、公证能力和Windows Authenticode证书，并完成双端实机验收后才能另行发布。
- WorkBuddy包内Ed25519用于证明内容来源和完整性，不等同于操作系统代码签名；系统阻断时停止安装，不提供绕过步骤。

## 兼容性

- 不修改V1.3.1.2的49项Skills内容、版本、签名包或发布索引。
- 不改变既有用户安装、设备绑定和凭据。
- 本次不包含短信登录。

## 发布验收

- GitHub PR #56已合并，PWA与原生发布策略两项CI检查通过。
- 根项目114项通过、2项跳过、6个子测试通过。
- 知识门户183项测试通过。
- 29个项目算法包覆盖率100%，3项高频项目检索金标准通过。
- REST、Streamable HTTP MCP、正式下载包、最近备份六项发布门禁通过。
- 49项Skills签名覆盖为49/49。
- 公网登录页、PWA入口、Manifest、能力清单、Service Worker权限和服务健康验收通过。
- 生产静态文件4/4与主线SHA-256一致。

## 回滚

生产部署前备份位于：

`/opt/jiaotang-kb-backups/20260727235850`
