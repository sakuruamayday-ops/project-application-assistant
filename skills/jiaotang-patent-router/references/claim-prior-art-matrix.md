# 权利要求—现有技术证据链

## 固定顺序

1. 从申请文件建立权利要求节点、从属引用边和跨保护客体引用边。
2. 沿从属引用路径汇总必要技术特征；解析三层以上嵌套限定、并列与择一关系、数值范围、马库什变量和各自独立选择；产品、方法和用途等不同保护客体分别确定独立权利要求。
3. 用独立权利要求必要技术特征作为 IPC 判断最高权重，并形成“IPC＋技术主题＋单项特征”检索蓝图。
4. P1 执行专利与非专利文献检索，记录公开日、来源链接、检索库、检索式、命中段落和证据等级。
5. 将检索结果标准化后交给 `scripts/build_claim_prior_art_matrix.py`，生成区别技术特征—现有技术对照表。
6. 新颖性只判断单一在先文件是否逐项公开同一权利要求全部必要技术特征。
7. 创造性依次记录最接近现有技术、区别特征、区别特征产生的技术效果、实际解决的技术问题、技术启示或组合动机。

## 现有技术输入

```json
{
  "documents": [
    {
      "document_id": "公开编号或稳定文献ID",
      "title": "标题",
      "publication_date": "YYYY-MM-DD",
      "source_url": "可复核原文链接",
      "source_verified": true,
      "prior_art_eligible": true,
      "evidence_level": "A/B/C/D",
      "procedural_role": "examiner_cited/closest_prior_art/search_result",
      "passages": [
        {
          "kind": "paragraph",
          "locator": "[0032]",
          "text": "对比文件原文",
          "figure_markers": ["图2"]
        },
        {
          "kind": "claim",
          "locator": "权利要求5",
          "text": "对比权利要求原文"
        }
      ],
      "feature_mappings": [
        {
          "feature_id": "C1-F1",
          "status": "disclosed",
          "source_locators": ["[0032]", "权利要求5", "图2"],
          "evidence": [
            {
              "locator": "[0032]",
              "text": "支持该映射的原文"
            }
          ]
        }
      ]
    }
  ]
}
```

`status` 只允许在证据支持时填写 `disclosed`、`not_disclosed` 或 `uncertain`。`disclosed` 必须同时带原文和段落号、权利要求号或附图定位；缺少定位会被降为 `MAPPING_INCOMPLETE`。没有可复核原文映射时，脚本只输出 `LEXICAL_REVIEW_REQUIRED` 或 `SEMANTIC_REVIEW_REQUIRED`，不得自动升级为“已公开”。

## 语义等同候选

- 使用 `references/technical-equivalence-rules.json` 仅扩展检索表达和发现候选。
- 词典归一、字符相似、语义模型或大模型判断都不能直接认定技术特征已公开。
- 语义裁决必须同时查看完整段落、上下文权利要求、相关附图及附图标记，并说明本领域技术人员为何会或不会理解为同一技术手段。
- 功能相同但结构、步骤、条件或技术效果不同的内容保持 `uncertain`，不得因“作用类似”直接写成等同。

## 输出解释

- `POTENTIAL_SINGLE_DOCUMENT_NOVELTY_RISK`：一份来源已核验、在先资格已确认的文件，对当前权利要求全部必要技术特征都有带定位的明确公开映射。
- `NO_VERIFIED_SINGLE_DOCUMENT_FULL_MAPPING_IN_CURRENT_EVIDENCE`：当前证据没有形成单一文件完整映射，不等于已经证明具备新颖性。
- `REQUIRES_DIFFERENCE_EFFECT_AND_TEACHING_ANALYSIS`：已经选出最接近现有技术候选，但仍需补技术效果、实际技术问题和技术启示证据。
