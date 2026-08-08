# 每周政策增量自动发布

## 适用范围

本链仅接收 `automation-6` 已冻结的 `increment_handoff.json`、
`manifest_expected_hits.csv` 与 `handoff_digest.json`。冻结交接包是唯一变化集；
发布任务不得重新扫描知识库，也不得调用全量全文索引重建器。

普通政策周增量执行以下固定顺序：

1. 逐条验证交接包、源文件 SHA-256、大小和 manifest 预期命中基数。
2. 从当前受信索引槽位增量维护文档、分块、FTS、政策版本和相关派生表。
3. 生成 `manifest_verification.json`，仅当 exact 等于交接文件总数且其他状态均为零时继续。
4. 以 Ed25519 签署逻辑增量包，并把前一链摘要写入本轮签名。
5. 将新增原件按 SHA-256 内容寻址上传；相同哈希只复核，不重复上传。
6. 将完整基线锚点、受信公钥、不可变增量包和指针历史写入 OSS。
7. 用 4 KiB rsync 差异算法更新服务器非活动槽位，逐文件复核后原子切换。
8. CAS 切换增量链 `current`，执行服务器深度验签、REST/MCP 固定路由和新增文档命中测试。
9. 仅在服务器、云端、REST、MCP 全部通过后提交本地链状态。

任何步骤失败均不得提交本地链状态。服务器已切换时自动恢复上一槽位；云端
指针已切换时恢复前一已签名指针。失败的不可变增量包可以保留审计，但不会被
`current` 引用。

## 存储布局

- 完整基线：复用已存在的 OSS 不可变完整索引 release，并在本地保存 APFS
  写时复制基线和 Ed25519 基线锚点。
- 周增量：`production/index/policy-increment/v1/deltas/{chain_sha256}/`。
- 指针历史：`production/index/policy-increment/v1/pointers/{chain_sha256}.json`。
- 当前指针：`production/index/policy-increment/v1/current.json`。
- 原始资料：`production/knowledge/objects/{sha256前两位}/{sha256}`。
- 服务器：只保留 current 与 previous 两个完整槽位；rsync 在上一槽位旁临时
  组装，成功后替换上一槽位，失败时不破坏可回滚版本。

本地链状态位于 `/Users/zsh/JiaotangData/索引/policy-increment-chain`；发布私钥
位于 `/Users/zsh/.config/project-assistant/policy-increment-chain`，权限固定为
`0600`，不得进入仓库、交接包或发布报告。

## 灾难恢复

恢复顺序固定为：

1. 从 OSS 现有完整索引 release 恢复并验签基线。
2. 验证基线 Ed25519 锚点。
3. 按 `current.json` 中的顺序逐个下载增量包。
4. 对每包验证前驱链摘要、签名、payload、handoff 摘要和 manifest exact 回执。
5. 逐包重放并核对候选 SQLite 与 manifest SHA-256。
6. 通过 SQLite、结构化表、REST/MCP 和新增文档命中测试后才允许切换。

日常增量不允许普通整库复制。灾难恢复介质不支持写时复制时，只有恢复任务可
显式设置 `JIAOTANG_POLICY_ALLOW_FULL_COPY=1`。

## 重新建立完整基线的条件

出现下列任一情况时停止周增量并建立新的完整签名基线：

- SQLite schema、分词器、解析器或分块算法变化；
- 链、manifest、SQLite 或 OSS 对象完整性失败；
- 增量变化比例超过发布配置阈值；
- 主人明确要求基线压实或密钥轮换。

## 权威名单边界

国家专精特新小巨人、浙江省专精特新中小企业、浙江省首台套、首批次新材料、
首版次软件产品仍先执行名单结构化表重建、区域覆盖审计和金标准。普通政策增量
器对这五类名单保持 fail closed；在没有独立的名单链成功回执和结构化表差分导入
实现前，不得以普通文档增量绕过。
