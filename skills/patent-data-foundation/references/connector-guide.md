# 专利数据连接器

## 数据源顺序

1. 国家知识产权局专利检索及分析系统。用户可免费注册，用于中国及多国专利检索、分析和下载：`https://pss-system.cponline.cnipa.gov.cn/`。
2. 国家知识产权局知识产权数据资源公共服务系统批量下载包。用户注册后自行下载，Skill只导入用户有权使用的标准化数据：`https://ipdps.cnipa.gov.cn/`。
3. 欧洲专利局Open Patent Services。适合程序化获取著录、同族、法律事件和全文数据，需要注册应用并配置OAuth：`https://www.epo.org/en/searching-for-patents/data/web-services/ops`。
4. Google Cloud BigQuery公共数据。适合批量统计和专利地图，需要Google Cloud项目及相应身份认证，不等同于普通API Key。
5. 用户授权的第三方数据库API、MCP或导出文件。

## 是否必须配置API或MCP

- 企业专利清单核验、单个专利检索和基础法律状态复核：不强制API或MCP，可使用国家知识产权局免费系统和用户提供文件。
- 批量相似检索、同族扩展、FTO、竞争格局、专利地图和持续监测：建议配置专利API、BigQuery或由用户合法部署的MCP连接器。
- MCP不是新的专利数据源，只是把官方或授权API封装为Agent工具；没有合法上游数据时，不能仅靠MCP名称获得完整专利数据。

## 使用方式

```bash
python3 scripts/patent_connector.py init
python3 scripts/patent_connector.py import --provider cnipa-bulk --input normalized-cnipa.jsonl
```

国家知识产权局批量数据更新频率及字段以官方开放目录为准。连接器不内置账号、下载令牌或第三方数据库内容。法律状态必须继续执行官方登记簿、官方公报、第三方数据库三级核验。
