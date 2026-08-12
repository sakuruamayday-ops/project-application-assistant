# 候选差异与审批绑定

## 审批哈希

- `diff_sha256`: `1a8b49ff1c8bce3fe55a9e60c0bb45a468ce7b56541da03c0a9bc983dbb10b04`
- `bound_candidate_sha256`: `f68b48704d5428cf231609f96022c5b8a8f3fb8a18822db4d0095a0f38d9277c`

## 受保护变更

1. 高企知识产权、PS和科技成果转化汇总表实施一项一行简写粒度、编号和占位符校验。
2. 正式文档必须使用 WPS Office 逐页验收，并保留每页截图与检查清单。
3. 原模板字节复制回执、字段校验回执、WPS回执、品牌回执和最终 DOCX SHA-256 必须闭环一致。
4. Pages、LibreOffice和快速预览只可用于诊断，不能代替WPS验收。

## 批准目标文件

| 路径 | 候选 SHA-256 | 权限 |
|---|---|---|
| `skills/high-tech-enterprise-application-drafting/SKILL.md` | `c69f41383afd493f4bd0fd2ce631b1bf74727810c93b7124d12ec89129c1561f` | `0644` |
| `skills/high-tech-enterprise-application-drafting/agents/openai.yaml` | `e7a30ae7303f188eaf7be7ce60dcff3b57c98bf6e0db08309296b19d73c3622b` | `0644` |
| `skills/high-tech-enterprise-application-drafting/references/summary-table-contract.md` | `2df1c7f39af586878fd7c423552345b8811e7fdde015515b23b0ccb70c515a42` | `0644` |
| `skills/high-tech-enterprise-application-drafting/references/v1.3.1-release-plan.md` | `c8107f4a862e0c326ebe1d88eee8e1db9c4980fa1cb44792a203292950014255` | `0644` |
| `skills/high-tech-enterprise-application-drafting/scripts/hightech_delivery_gate.py` | `6a880e525cb2af551c9fd5dc05a371221e1f002b2e6c49dcae8743b7aa311939` | `0755` |
| `tests/test_hightech_application_drafting.py` | `d9d273ed042114928120b0a23a536e6c0a0e3870217a67cf8cc52f126975eb61` | `0644` |

发布清单、签名伴随物、V1.6.4.2功能介绍和演进审计文件属于本次获授权的机械发布伴随变更，不改受保护业务逻辑。
