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

- `company.name` 必须与当前企业一致；存在统一社会信用代码时优先用代码校验。
- 项目要求合并口径时，`consolidation_scope=standalone` 的数据不得直接使用。
- 金额在比较门槛前统一转换为项目要求的单位；不得把元与万元直接比较。
- `quality.status=unverified` 只能用于列出待核验缺口，不能形成达标结论。
- 对应年度和指标缺少时返回缺口，不从相邻年份推算。
- 税务风险、税收违法、申报资格和获批概率不属于共享事实字段。
