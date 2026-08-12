# 企业级技术—产品—收入母矩阵生成器使用指南

## 目标

企业只维护一份结构化母矩阵。各项目技能读取同一母矩阵自动生成项目视图，避免重复梳理技术、产品、性能、收入和来源。

生成器：

`scripts/technical_product_revenue_matrix.py`

模板：

`assets/enterprise-technical-product-revenue-matrix.template.json`

项目适配器：

`references/project-view-adapters.json`

## 推荐目录

在每家企业项目目录下建立：

```text
reports/
└── technical-product-revenue/
    ├── enterprise_master.json
    ├── enterprise_master_matrix.md
    ├── manifest.json
    └── project_views/
        ├── provincial_sme.json
        ├── provincial_sme.md
        ├── small_giant.json
        ├── small_giant.md
        └── ...
```

默认由Agent从企业资料自动维护 `enterprise_master.json`。Excel是可选内部审计界面，不是客户或业务人员的必填表，也不默认交付。Markdown、manifest 和项目视图不手工修改。

## 使用步骤

### 一、初始化

```bash
python3 scripts/technical_product_revenue_matrix.py init \
  --company "企业全称" \
  --credit-code "统一社会信用代码" \
  --as-of "2026-07-24" \
  --output "reports/technical-product-revenue/enterprise_master.json"
```

初始化文件包含占位内容，必须用本企业资料替换后才能通过校验。

### 二、填写母矩阵

依次填写：

1. `technologies`：核心技术版本、载体类型、公开技术名称、技术目标、可公开路线和窗口、来源、保密边界。
2. `products`：实际材料、部件、终端产品、装备、软件、器械、成果或样机。
3. `technology_product_links`：技术版本如何嵌入产品、是否稳定使用、形成什么性能。
4. `commercialization`：产品销售、应用效益或成果转化数据及来源。
5. `intellectual_property_links`：需要时增加技术、产品和知识产权映射。
6. `project_overrides`：只有项目政策明确要求特殊边界时才填写人工覆盖。

金额字段保存材料原始字符串，不自行加总或四舍五入。

### 二点一、可选内部Excel审计界面

仅在主人明确要求查看、批量维护或调试，且当前宿主具备表格创建与回读能力时，才将JSON母矩阵映射为Excel审计表。Excel不是正式技能运行依赖，也不要求客户填写。表格至少覆盖企业信息、技术清单、产品清单、技术产品映射、商业化收入、知识产权关联、项目人工覆盖、项目适配、校验看板和数据字典。

Excel回读后必须重新生成JSON，并继续执行 `validate` 和 `build`。同一技术与产品存在多个性能指标时分行填写，回读时合并为同一关系。当前宿主没有可靠表格能力时，直接维护JSON母矩阵，不调用不存在的本机Node桥接器。

### 三、校验

```bash
python3 scripts/technical_product_revenue_matrix.py validate \
  --input "reports/technical-product-revenue/enterprise_master.json"
```

校验会检查：

- ID唯一性和跨表引用；
- 技术版本、产品、性能和来源是否完整；
- 已量产或部署技术是否映射到终端产品；
- 商业化记录是否引用真实产品；
- 是否误用内部转移收入；
- 是否写入精确配方、组分比例、原料牌号、添加顺序或关键单点参数等禁止字段。

### 四、生成全部项目视图

```bash
python3 scripts/technical_product_revenue_matrix.py build \
  --input "reports/technical-product-revenue/enterprise_master.json" \
  --output-dir "reports/technical-product-revenue" \
  --projects all
```

也可只生成指定项目：

```bash
python3 scripts/technical_product_revenue_matrix.py build \
  --input "reports/technical-product-revenue/enterprise_master.json" \
  --output-dir "reports/technical-product-revenue" \
  --projects provincial_sme,small_giant,first_batch_material
```

### 五、项目技能读取

每个项目技能按以下顺序读取：

1. 读取 `manifest.json`；
2. 计算或核对 `enterprise_master.json` 的SHA-256；
3. 哈希与 `source_master_sha256` 不一致时，先重新运行生成器；
4. 读取 `project_views/<project_id>.json` 作为结构化底稿；
5. 读取同名 `.md` 作为人工复核视图；
6. 再叠加当期政策原文和项目专属门槛，不得直接把“结构已生成”解释为“项目已达标”。

## 项目ID

| 项目ID | 项目 |
|---|---|
| `provincial_sme` | 省级专精特新 |
| `small_giant` | 专精特新小巨人 |
| `first_batch_material` | 首批次新材料 |
| `first_set_equipment` | 首台套装备 |
| `first_edition_software` | 首版次软件 |
| `industrial_new_product` | 省工业新产品 |
| `zhejiang_manufacturing_excellence` | 浙江制造精品 |
| `science_project` | 科技计划与尖兵领雁 |
| `science_award` | 科技进步奖 |
| `innovative_medical_device` | 创新医疗器械 |
| `high_tech_enterprise` | 高新技术企业 |

## 状态语义

- `结构已生成，待政策核验`：母矩阵中存在可转换的技术或产品对象，不代表项目达标。
- `需换层或不适用`：没有找到符合该项目申报对象类型的产品，需要调整申报层级或判定该项目不适用。
- 项目视图中的提醒只做分诊，不能替代目录、检测、查新、注册、TRL、专项审计等政策门槛。

## 更新纪律

- 默认由Agent根据新增企业材料增量更新 `enterprise_master.json`。
- 使用Excel内部维护时，回导后重新执行 `validate` 和 `build`，不得逐个手工修改项目视图。
- 不得要求客户先填写Excel才能开展分析；Excel完整性不构成申报资格条件。
- 项目技能读取前必须检查哈希，避免引用过期视图。
- 母矩阵只保存可用于申报的公开层事实。商业秘密留在企业内部受控资料，不写入JSON。
