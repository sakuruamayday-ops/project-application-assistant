# 数据结构与公式

## 输入 JSON

```json
{
  "company": "示例制造企业有限公司",
  "years": {
    "2023": {
      "revenue": 0,
      "cost": 0,
      "profit_before_tax": 0,
      "net_profit": 0,
      "assets": 0,
      "assets_open": 0,
      "liabilities": 0,
      "equity": 0,
      "equity_open": 0,
      "current_assets": 0,
      "current_liabilities": 0,
      "cash": 0,
      "receivables": 0,
      "receivables_open": 0,
      "other_receivables": 0,
      "inventory": 0,
      "inventory_open": 0,
      "advances_from_customers": 0,
      "short_term_loans": 0,
      "operating_cash_flow": 0,
      "capex_cash": 0,
      "taxes_paid": 0,
      "sales_cash": 0,
      "research_expense": 0,
      "interest_expense": 0,
      "income_tax_expense": 0
    }
  }
}
```

金额统一用元。至少提供两个连续年度才能计算周转天数；缺失值使用 `null`，不要用零代替未知。

## 公式

| 指标 | 公式 |
|---|---|
| 毛利率 | 收入减成本 ÷ 收入 |
| 净利率 | 净利润 ÷ 收入 |
| 资产负债率 | 总负债 ÷ 总资产 |
| 流动比率 | 流动资产 ÷ 流动负债 |
| 速动比率 | 流动资产减存货后 ÷ 流动负债 |
| 现金比率 | 货币资金 ÷ 流动负债 |
| 平均净资产收益率 | 净利润 ÷ 平均权益 |
| 平均总资产收益率 | 净利润 ÷ 平均总资产 |
| 应收周转天数 | 平均应收账款 ÷ 收入 × 365 |
| 存货周转天数 | 平均存货 ÷ 营业成本 × 365 |
| 其他应收款占资产 | 其他应收款 ÷ 总资产 |
| 预收占收入 | 预收账款 ÷ 收入 |
| 研发费用率 | 会计研究或研发费用 ÷ 收入 |
| 现金税费支付率 | 现金流量表支付税费 ÷ 收入 |
| 销售收现率 | 销售商品和劳务收到现金 ÷ 收入 |
| 自由现金流 | 经营现金流减购建长期资产现金支出 |
| 利息保障倍数 | 利润总额加利息费用后 ÷ 利息费用 |

## 不得混用

- 会计研究费用、研发加计扣除费用、高企研发费用不是同一口径。
- 现金税费支付率不是增值税税负率。
- 预收账款是履约义务，不等同于同额现金负债。
- 审计报告的所得税费用为空不等于未申报或少缴企业所得税。
