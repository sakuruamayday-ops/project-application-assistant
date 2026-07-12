# 本地知识库与RAG配置

支持用户自配的文件目录、Chroma、LanceDB、PGVector或其他本地检索器。项目申报助手不绑定特定向量数据库。

## 配置

```yaml
providers:
  local_knowledge:
    enabled: true
    root_path: /absolute/path/to/knowledge
```

## 索引规则

- 排除密钥、聊天备份、客户通信和无关个人资料。
- 客户目录之间保持隔离。
- 索引结果必须保留原文件路径和修改时间。
- 命中政策和案例后回到原文件或官方来源核验。

## 验证与降级

用一个已知文件标题查询，确认能返回原路径。知识库未挂载或索引失败时，只使用当前会话文件和政府官方来源。

