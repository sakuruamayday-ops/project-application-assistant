# 云端知识索引增量发布策略

## 目标

- 原始资料按 SHA-256 内容寻址增量上传，同一内容不重复占用 OSS。
- `production/knowledge/` 下只允许 `objects/` 内容寻址对象；旧 `current/` 和分类相对路径前缀永久禁止重新生成。
- manifest、对象集合和生产索引在一次发布中使用同一冻结版本。
- OSS 业务对象只使用 `production/knowledge/` 与 `production/index/` 两个大根目录。

## 每周政策增量例外

`automation-6` 生成且冻结的政策交接包采用“完整签名基线＋Ed25519 周增量链”，
不重新扫描知识库，不重建全部文档，也不为每周变化上传新的 3 GB 级完整 SQLite。
具体门禁、OSS 布局、服务器双槽切换和恢复流程见
[`policy-increment-release.md`](policy-increment-release.md)。

该例外不改变其他索引发布的完整不可变 release 规则；schema、解析器、分词器、
分块算法变化或完整性失败时，政策增量链也必须回到完整基线发布。
- 服务器查询索引在校验通过后原子切换；云端不生成快照、回滚快照或 `server-backups`。

## 固定发布顺序

所有人工和自动化发布统一执行“manifest冻结—去重上传—二次校验—索引发布—容量复核”，不得并发、跳步或在流水线中途改写冻结集合。

1. **manifest冻结**
   - 使用互斥锁阻止其他采集、建库和发布任务写入同一生产集合。
   - 生成并记录 manifest、OSS 白名单、索引文件及其 SHA-256。
   - 读取发布前容量，并至少按本轮完整索引大小预留版本增长空间；现有占用加预留量超过容量预算时立即熔断。
   - 识别文件年度、正式文号及公示稿、征求意见稿或正式版状态；配置了业务 profile 的文件同时核验条目数和序号连续性。
2. **去重上传**
   - 在冻结 manifest 中按 SHA-256 查重。
   - 相同哈希只补充归档路径和审计记录，不重复上传；新哈希对象才上传至 `production/knowledge/objects/`。
3. **二次校验**
   - 对冻结白名单内全部对象再次核对 SHA-256 元数据和对象大小。
   - 失败、缺失、孤立对象必须均为 0；任一非 0 立即停止，不得发布索引。
4. **索引发布**
   - 本地 SQLite 先通过 `PRAGMA quick_check` 和相关测试。
   - 将本轮索引发布至 `production/index/current/`，复核大小与 SHA-256 后再原子切换生产服务。
   - 服务器只保留当前版和上一版两个本地槽位；OSS 不生成 `snapshots`、`rollback-snapshots` 或 `server-backups`。
5. **容量复核**
   - 同时读取 Bucket 统计和对象版本清单，分别报告当前版本、非当前版本及总容量。
   - 确认未完成分片为 0，三个快照类前缀和 `production/server-backups/` 为空。
   - 统计接口存在延迟时保留两套口径并注明时间；不得将待生命周期回收的非当前版本计作已释放。

示例：

```bash
python3 services/knowledge-portal/scripts/ingest_knowledge_file.py \
  /path/to/source.pdf \
  --relative-target '10_政策与目录/目标目录/source.pdf' \
  --profile first-batch-directory \
  --expected-count 445 \
  --execute-pipeline
```

注意：全量重建 SQLite 会改变大量数据库页，不能把 rsync 差异块当作内容去重。减少传输和占用的首要门禁是“相同哈希不重建、不重传”。

## 恢复顺序

1. 优先将服务器 `.previous` 索引槽位切回当前路径。
2. 两个服务器槽位均不可用时，从 OSS `production/index/current/` 恢复正式发布索引。
3. 再根据 OSS 中的增量原始资料和 manifest 重建缺失期间索引。

## 发布门禁

- 本地和服务器 SQLite 必须通过 `PRAGMA quick_check`。
- rsync 后文件 SHA-256 必须与本地一致。
- 原子切换后服务健康检查必须通过。
- OSS 完整索引上传后必须复核对象大小与 SHA-256 元数据。
- 相同 SHA-256 文件不得触发全文索引重建。
- 公示稿、征求意见稿和草案不得覆盖正式版或标记为现行。
- 冻结后检测到 manifest 或索引 SHA-256 变化，必须终止本轮并重新开始。
- 未完成分片、快照前缀或 `server-backups` 非空时，容量复核不得判定为通过。
- `production/knowledge/` 下发现 `current/`、`10_政策与目录/`、`50_名单与对标/` 或 `90_方法与复盘/` 旧相对路径对象时，容量复核必须失败。
