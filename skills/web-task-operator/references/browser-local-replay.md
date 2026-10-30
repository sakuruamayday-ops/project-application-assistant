# 浏览器本地请求重放

## 适用条件

仅在以下条件同时满足时使用：

- 用户已在目标网站合法登录并有权读取目标数据。
- 用户在浏览器中可以正常打开页面。
- 本地重放用于宿主或可访问性受限，而网站正常授权会话仍可用的场景。
- 用户已确认批量范围、频率、输出位置和用途。

遇验证码、账号风控、付费、权限、条款或网站访问限制时，转官方人工交互或其他已授权来源，请求重放仅用于正常授权会话内的业务读取。

## 通用流程

1. 优先让用户通过扫码完成登录；网站不支持扫码时，由用户自行输入凭据。
2. 打开开发者工具的Network面板并启用保留日志。
3. 在网站中执行一次正常的搜索、筛选或翻页动作。
4. 使用Fetch/XHR或接口路径关键词过滤请求，识别列表请求。
5. 记录请求路径、方法、查询参数、请求体和非敏感业务Header，先查看一页响应结构。
6. 在同一网站页面的Console中运行同源 `fetch`，设置 `credentials: "include"`，让浏览器自动携带会话。
7. 以低频方式逐页读取，在本地内存去重，并将结果下载到用户电脑。
8. 用户向 Agent 提供脱敏业务文件，认证信息留在本机安全会话。

“Copy as fetch” 内容留在本机；运行前清理显式 `cookie`、`authorization` 等敏感 Header。必要动态 CSRF 仅在本地临时使用，对话、诊断和交付采用脱敏业务结果。

## Safari 提示

1. Safari → 设置 → 高级，启用“在菜单栏中显示开发菜单”。
2. 开发 → 显示网页检查器，进入“网络”，勾选“保留日志”。
3. 正常操作一次页面，在过滤框输入接口路径关键词，例如 `data-api`。
4. 查看 URL、方法、查询、请求体和响应，认证信息留本地安全会话。
5. 切换到“控制台”，运行同源 `fetch` 并在本地下载结果。

Safari 当前 URL 操作受限时，给出上述人工提示，待用户完成官方页面交互后重新观察。

## Chrome 提示

1. macOS 按 `Option+Command+I`，Windows或Linux按 `F12` 或 `Ctrl+Shift+I`。
2. 打开Network，勾选Preserve log，选择Fetch/XHR。
3. 正常触发一次列表刷新，查看请求的Headers、Payload和Response。
4. 如使用“Copy as fetch”，仅在本机Console运行，先删除显式Cookie和Authorization字段。
5. 用 `credentials: "include"` 在同源授权会话取结果，向 Agent 仅提供脱敏业务文件。

## Edge 提示

1. macOS 按 `Option+Command+I`，Windows按 `F12` 或 `Ctrl+Shift+I`。
2. 打开Network，勾选Preserve log，使用Fetch/XHR过滤。
3. 读取请求参数与响应结构；本地Console重放方法与Chrome相同。
4. 在当前本地浏览器开发者工具内操作，凭据和配置由浏览器安全机制管理。

## Firefox 提示

1. macOS 按 `Option+Command+I`，Windows或Linux按 `F12` 或 `Ctrl+Shift+I`。
2. 进入“网络”，启用持久日志，选择XHR过滤。
3. 正常触发列表请求，查看Params、Request和Response。
4. 在同源页面的“控制台”中编写 `fetch`；Cookie由浏览器会话携带，不手工读取。
5. 将响应整理为脱敏业务数据下载，认证信息留在本机。

## 本地导出模板

以下模板只展示安全结构，接口路径、方法和业务参数来自用户亲自查看的真实请求：

```javascript
const records = [];

for (let pageNumber = 1; pageNumber <= maxPages; pageNumber += 1) {
  const response = await fetch("/实际同源接口", {
    method: "POST",
    credentials: "include",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({pageNumber, pageSize: 20})
  });

  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  const pageData = await response.json();
  records.push(...extractRecords(pageData));
  await new Promise(resolve => setTimeout(resolve, requestIntervalMs));
}

const blob = new Blob([JSON.stringify(records, null, 2)], {
  type: "application/json"
});
const link = document.createElement("a");
link.href = URL.createObjectURL(blob);
link.download = "browser-export.json";
link.click();
URL.revokeObjectURL(link.href);
```

模板使用中性占位，Cookie、Token、密码和 Authorization 留在本地安全会话。首次读取一页核对结构、字段、去重键及允许频率，再扩大到授权范围。
