# 共享财务事实契约

`enterprise-financial-facts/v1` 是财税分析、项目可行性、专精特新体检和申报材料之间的共享数据层。

```json
{
  "schema": "enterprise-financial-facts/v1",
  "company": {"name": "示例企业有限公司", "unified_social_credit_code": ""},
  "basis": {
    "currency": "CNY",
    "unit": "yuan",
    "consolidation_scope": "standalone",
    "accounting_standard": ""
  },
  "periods": {
    "2025": {
      "facts": {},
      "metrics": {},
      "evidence": {},
      "quality": {"status": "partially_verified", "missing_fields": [], "notes": []}
    }
  },
  "source_artifacts": [],
  "producer": "manufacturing-tax-risk-analysis"
}
```

## 复用门槛

- `company.name` 与当前企业一致；存在统一社会信用代码时优先用代码校验。
- 项目采用合并口径时，补齐合并范围数据；`consolidation_scope=standalone` 保留为单体分析。
- 金额按项目要求统一单位后比较门槛，并保留转换过程。
- `quality.status=unverified` 用于待核缺口，达标判断另据已核验记录。
- 年度或指标缺项返回具体缺口，已知年度继续计算。
- 税务风险、税收违法、申报资格和获批概率不属于共享事实字段。
