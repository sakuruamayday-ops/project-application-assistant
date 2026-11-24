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
- 归集各份新财务原表时，`sources` 或 `source_artifacts` 中每份原表登记 `company_name` 和原表位置。主体为空报缺主体信息，主体冲突列出文件和各自主体，停止归集。
- 项目采用合并口径时，补齐合并范围数据；`consolidation_scope=standalone` 保留为单体分析。
- 金额按项目要求统一单位后比较门槛，并保留转换过程。
- `quality.status=unverified` 用于待核缺口，达标判断另据已核验记录。
- 年度或指标缺项返回具体缺口，已知年度继续计算。
- 税务风险、税收违法、申报资格和获批概率不属于共享事实字段。

## 结构化核验回执

`validate_financial_assessment.py` 可直接读取三表计算生成的 `enterprise-financial-facts/v1` 主输出。主体取 `company`，口径取 `basis` 与 `periods` 的年度，各期事实关联同名 `evidence` 中的原表位置。回执保留各期 `quality`，并独立复算主输出中有值、有来源的年度资产负债率和研发费用率。其余指标沿用三表计算产物。

`validate_financial_assessment.py` 接受同一批核验结果。`identity` 取企业名或统一社会信用代码，`scope` 登记期间、币种、单位和合并范围。`sources` 登记原报表或业务表，`facts`、`metrics` 登记事实与指标，`conflicts` 和 `quality` 保留本批冲突及质量状态。可用事实和计算结果填 `source_ids`。

回执保留 `status` 和 `errors`，并返回 `identity`、`scope`、`sources`、`quality` 和 `issues`。每条问题含 `field_location`、`current_value`、`expected_requirement`、`fix`、`source_location`。`expected_requirement` 用 `rule` 和 `reference` 回指输入契约、计算公式或已核来源。源表位置优先从该事实或指标的 `source_location` 取值，也可按 `source_ids` 定位 `sources` 中的 `location`、`sheet`、`page`、`cell` 或 `field`。缺位置时回执写「缺来源位置」。

复算时给事实填写唯一 `id`、`value`、质量状态和来源。指标保留原字段，额外填 `formula_id` 和顺序化 `inputs`。输入可写 `{"fact_id":"assets"}` 引用事实，或写 `{"metric":"净资产"}` 引用另一个复算指标。格式见[公式与派生汇总](reconciliation-and-formulas.md#公式与派生汇总)。修正原始值后用同一命令复算，`recomputed_metrics` 交付新值，`issues` 逐项给出仍需更新的原结果。可独立计算的指标随同一回执输出。

共用三表回执按原始 JSON 的十进制精度复算，比例保留原运算精度后核对，展示舍入留到报表。主营占比 `main_revenue_ratio` 取 `main_revenue ÷ revenue`，高新收入占比 `high_tech_income_ratio` 取 `high_tech_income ÷ total_income`，研发费率采用对应项目要求的研发费与收入口径。三个比例的原始比值须在 0 到 1 之间。回执的 `items` 用于填写缺陷项、差距、补强动作、优先级和证据位置，既有 `issues` 保留原数和修改定位。

旧版采集工作簿支持带有主体栏、年度列头与对应财务科目行的 XLSX 或 XLSM。脚本用原值复算，保留报错单元格。一批多份输入各按文件核验，主体不一致或存在错误时批次回执拒收。其他表式先按来源台账提取到结构化事实。
