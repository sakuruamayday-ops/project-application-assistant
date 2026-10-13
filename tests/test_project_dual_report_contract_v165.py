import json
import runpy
import tempfile
import uuid
from contextlib import contextmanager
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "skills"
CONTRACT = SKILLS / "project-feasibility" / "references" / "two-report-contract.md"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_dual_report_contract_has_distinct_depth_and_deadlines() -> None:
    text = read(CONTRACT)
    for phrase in (
        "报告一：项目前期评估报告",
        "报告二：项目申报可行性分析报告",
        "申报截止日期",
        "已截止",
        "待当年通知",
        "现行条件或完整评分表逐项拆解",
        "确定得分",
        "条件得分",
        "完成节点",
    ):
        assert phrase in text


def test_dual_report_contract_covers_twelve_project_types() -> None:
    text = read(CONTRACT)
    for project in (
        "高新技术企业",
        "专精特新中小企业",
        "专精特新“小巨人”",
        "首台套",
        "首批次新材料",
        "首版次软件",
        "研发中心",
        "制造精品",
        "单项冠军",
        "绿色工厂",
        "数字化项目",
        "科技计划",
    ):
        assert f"| {project} |" in text


def test_all_project_domain_routes_load_the_shared_contract() -> None:
    for skill in (
        "high-tech-enterprise-preassessment",
        "sme-score-preassessment",
        "industrialization-projects",
        "technology-innovation-projects",
        "quality-brand-projects",
        "green-development-projects",
        "digitalization-projects",
    ):
        assert "project-feasibility/references/two-report-contract.md" in read(
            SKILLS / skill / "SKILL.md"
        )


def test_common_strengthening_and_watermark_contract_are_mandatory() -> None:
    text = read(CONTRACT)
    for phrase in (
        "国内产品技术水平评价咨询报告",
        "国际产品技术水平评价咨询报告",
        "国内领先、国际先进",
        "共享品牌运行时",
        "默认只输出一份 PDF",
        "用户明确要求可编辑稿",
        "不设置文档加密或编辑限制",
    ):
        assert phrase in text


def test_sme_digital_diagnostic_is_soft_strengthening_without_invented_score() -> None:
    text = read(
        SKILLS
        / "sme-score-preassessment"
        / "references"
        / "digital-transformation-diagnostic-strengthening.md"
    )
    for phrase in (
        "软提升与证据补强",
        "发展战略",
        "业务创新转型",
        "新型能力",
        "系统性解决方案",
        "治理体系",
        "全国与同行对标",
        "待企业确认，建议补强",
    ):
        assert phrase in text
    assert "不得提前写入成熟度等级、指数、全国排名或同行排名" in text


def test_hightech_super_deduction_chain_is_complete_and_sanitized() -> None:
    text = read(
        SKILLS
        / "high-tech-enterprise-preassessment"
        / "references"
        / "rd-super-deduction-strengthening.md"
    )
    for phrase in (
        "立项及可行性报告",
        "研发人员名单",
        "研发设备清单",
        "人员工时记录",
        "研发材料领用记录",
        "小试、中试或试制过程记录",
        "研发项目结题报告",
        "专利与研发项目关联台账",
        "研发费用辅助账工作簿",
        "研发费用明细账",
        "专项审计和纳税申报",
    ):
        assert phrase in text
    for customer_marker in ("杭州彭公", "研发费用归集(1)"):
        assert customer_marker not in text


def test_delivery_contract_registers_both_report_categories() -> None:
    payload = json.loads(read(SKILLS / "delivery-contracts.json"))
    role = payload["skill_roles"]["project-feasibility"]
    assert role["owns"] == [
        "project-presale-assessment-report",
        "project-feasibility-analysis-report",
    ]
    for profile_name in role["owns"]:
        profile = payload["delivery_profiles"][profile_name]
        artifact = profile["required_artifacts"][0]
        assert artifact["formats"] == ["docx", "pdf"]
        assert profile["branding_contracts"] == [
            {
                "mode": "required",
                "variant": "default",
                "artifact_roles": [artifact["role"]],
            }
        ]


def test_action_report_declares_host_required_delivery_fields() -> None:
    payload = json.loads(read(SKILLS / "delivery-contracts.json"))
    profile = payload["delivery_profiles"]["sme-action-report"]
    assert profile["requires_peer_comparison"] is True
    assert profile["required_artifacts"] == [{
        "role": "assessment_report",
        "formats": ["pdf"],
        "requires_sha256": True,
        "validation_gate": "document-render-and-structure-gate",
    }]
    assert profile["branding_contracts"] == [{
        "mode": "required", "variant": "default", "artifact_roles": ["assessment_report"],
    }]


def test_action_report_checks_follow_renderer_order_and_table_titles() -> None:
    profile = json.loads(read(SKILLS / "delivery-contracts.json"))["delivery_profiles"]["sme-action-report"]
    renderer = runpy.run_path(str(SKILLS / "project-feasibility/scripts/sme_action_report.py"))
    sections = {key: (title, columns) for key, title, columns in renderer["SECTIONS"]}
    headings = []
    for title, keys in renderer["GROUPS"]:
        headings.append(title)
        headings.extend(sections[key][0] for key in keys if sections[key][0])
    headings.append("数据来源")
    text = "\n".join(headings)
    positions = [text.index(marker) for marker in profile["required_sections"]]
    assert positions == sorted(positions)
    for table in profile["required_tables"]:
        matches = [columns for title, columns in sections.values() if table["id"] in title]
        assert len(matches) == 1
        assert list(matches[0]) == table["required_columns"]


def test_v1652_keeps_v165_report_and_project_logic_boundaries() -> None:
    text = read(CONTRACT)
    assert "企业分析报告 A、B、C 版" in text
    assert "尖兵领雁、市级重大及科技计划类的既有分析逻辑保持不变" in text
    manifest = json.loads(read(SKILLS / "suite-manifest.json"))
    contract = json.loads(read(SKILLS / "delivery-contracts.json"))
    assert manifest["release"]["tag"] == f"V{contract['rule_version']}"


def test_enterprise_panorama_keeps_business_modes_but_defaults_each_to_pdf() -> None:
    text = read(SKILLS / "enterprise-panorama-analysis" / "SKILL.md")
    manifest = json.loads(read(SKILLS / "suite-manifest.json"))
    assert "A 第一版｜标准销售版" in text
    assert "B 第二版｜GCIP深度顾问版" in text
    assert "C 全生成｜同时生成A和B" in text
    assert "每种已选报告默认只交付一份 PDF" in text
    assert "只有用户明确要求可编辑稿时才追加对应 Word" in text
    assert "gongchuang_deliver_pdf" in text
    assert 'deliveryProfileId="enterprise-panorama-standard"' in text
    assert 'deliveryProfileId="enterprise-panorama-professional"' in text
    assert "不再提供标准销售版" not in text
    contract = json.loads(read(SKILLS / "delivery-contracts.json"))
    assert manifest["release"]["version"] == contract["rule_version"]


def test_customer_body_does_not_require_internal_delivery_assertions() -> None:
    contract = json.loads(read(SKILLS / "delivery-contracts.json"))
    for skill in ("enterprise-panorama-analysis", "manufacturing-tax-risk-analysis", "sme-development-projects"):
        groups = contract["skills"][skill]["required_marker_groups"]
        markers = [marker for group in groups for marker in group]
        assert not any("审计通过" in marker or ".py通过" in marker or "交付产物" in marker for marker in markers)
        assert "交付Word" not in markers
        assert "交付PDF" not in markers
    profiles = contract["delivery_profiles"]
    assert profiles["enterprise-panorama-standard"]["branding_contracts"]
    assert profiles["enterprise-panorama-standard"]["required_artifacts"]


@contextmanager
def sales_html_case():
    # Own the actual generation inputs and output, including failed attempts.
    # Move them to Trash rather than pytest's permanent temporary-file cleanup.
    folder = Path(tempfile.mkdtemp(prefix="sales-master-test-"))
    try:
        yield folder, runpy.run_path(str(SKILLS / "enterprise-panorama-analysis/scripts/build_sales_html.py"))
    finally:
        trash = Path.home() / ".Trash"
        trash.mkdir(exist_ok=True)
        folder.rename(trash / f"{folder.name}-{uuid.uuid4()}")


def sales_input():
    return {
        "company": {"name": "合成模板验证有限公司", "paid_in_capital": "已提供工商公开原文"},
        "report_date": "合成报告日期", "data_as_of": "合成资料时点",
        "sections": {
            "03": {"paragraphs": [{"text": "已验证说明", "status": "low"},
                                    {"text": "待核说明", "status": "medium"},
                                    {"text": "风险说明", "status": "high"}]},
            "12": {"tables": [{"type": "summary-risks", "rows": [["—", "合成核验", "待来源支持", {"text": "待核", "severity": "pending"}]]}]},
        },
        "sources": [{"name": "合成测试来源", "url": "https://example.gov.cn/test", "queried_at": "合成时点"}],
    }


def sales_generate(module, folder, data, output="report.html"):
    source = folder / "input.json"
    source.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    destination = folder / output
    return module["build_sales_html"](source, destination), destination


def test_sales_html_preserves_fixed_master_dom_and_actual_state_components():
    from lxml import html
    with sales_html_case() as (folder, module):
        result, destination = sales_generate(module, folder, sales_input())
        document = html.fromstring(destination.read_text())
        assert result["status"] == "pass" and result["format"] == "html"
        assert document.xpath('//section[@data-section]/@data-section') == [f"{n:02}" for n in range(1, 14)]
        assert "经营数据与财务概况" in document.xpath('//section[@data-section="07"]/h1')[0].text_content()
        rows = document.xpath('//table[@class="basic-info"]/tbody/tr')
        assert len(rows) == 15 and all(len(row.xpath('./td')) == 2 for row in rows)
        assert [row.xpath('./td')[0].text_content() for row in rows] == [
            "企业名称", "曾用名", "统一社会信用代码", "成立日期", "注册资本", "实缴资本", "法定代表人", "企业类型", "登记状态", "注册地址", "经营范围", "纳税人资质", "所属行业", "登记机关", "官网",
        ]
        icons = document.xpath('//span[@class="section-icon-slot"]/img')
        assert len(icons) == 13 and all(node.get('src').startswith('data:image/png;base64,') for node in icons)
        assert 'width:20.500000pt;height:18.500000pt' in icons[0].get('style')
        assert len({node.get('style') for node in icons}) > 1
        for level in ('low', 'medium', 'high'):
            assert document.xpath(f'//span[@class="risk {level}"]')
        assert document.xpath('//span[@class="severity pending"]')
        assert document.xpath('//div[@class="assessment-level"]')[0].text_content() == '待核'
        assert len(document.xpath('//div[contains(@class,"comparison-card")]')) == 2
        assert not document.xpath('//script')
        text = document.find('body').text_content()
        assert '浙江巨能' not in text and '913307010928162928' not in text and 'B+' not in text
        assert '报告机构：共创知识产权' in text and '主要数据来源' in text
        css = document.xpath('//style')[0].text
        assert '.risk::before' in css and 'border-radius: 50%' in css
        assert 'table-layout: auto' in css and 'width: 65%' in css
        assert '.basic-info td:first-child { font-weight: 700' not in css


def test_sales_html_escapes_business_text_and_keeps_template_tokens_literal():
    from lxml import html
    with sales_html_case() as (folder, module):
        data = sales_input()
        literal = '<script>raw()</script> {{BODY_13}} {{STYLE}} {{CALLOUT_INFO}} & 引号"'
        data['sections']['03']['paragraphs'].append(literal)
        data['sections']['03']['callouts'] = [{'kind': kind, 'title': '合成说明', 'text': '只展示固定原组件'} for kind in ('warning', 'success', 'info', 'danger')]
        _, destination = sales_generate(module, folder, data)
        document = html.fromstring(destination.read_text())
        assert literal in document.find('body').text_content()
        assert len(document.xpath('//section[@data-section]')) == 13
        assert not document.xpath('//script') and len(document.xpath('//style')) == 1
        images = document.xpath('//div[contains(@class,"callout")]/img')
        assert len(images) == 4 and all(node.get('src').startswith('data:image/png;base64,') for node in images)
        for patch in ({'html': '<div>custom DOM</div>'}, {'sections': {'01': {'css': 'body{}'}}}):
            invalid = {**data, **patch}
            try:
                sales_generate(module, folder, invalid, 'invalid.html')
            except ValueError:
                pass
            else:
                raise AssertionError('layout input must be rejected')
            assert not (folder / 'invalid.html').exists()


def test_sales_html_rejects_actual_color_words_without_promoting_business_status():
    with sales_html_case() as (folder, module):
        for value in ('政府公示名单同名主体已命中（绿）', '第三方平台单源，待官方核验（黄）', '知识产权公开记录空白（红）', '单源待核(⻩)', '待核（ ⻩ ）'):
            data = sales_input()
            data['sections']['03']['paragraphs'] = [value]
            try:
                sales_generate(module, folder, data, 'invalid.html')
            except ValueError as error:
                assert '{text,status}' in str(error)
            else:
                raise AssertionError('plain color markers must not render')
            assert not (folder / 'invalid.html').exists()
        data['sections']['03']['paragraphs'] = ['绿色制造、黄色涂层、红外技术是普通业务文字。']
        _, destination = sales_generate(module, folder, data)
        assert '绿色制造、黄色涂层、红外技术' in destination.read_text()


def test_sales_html_financial_missing_and_public_capital_do_not_share_a_false_restriction():
    from lxml import html
    with sales_html_case() as (folder, module):
        data = sales_input()
        _, destination = sales_generate(module, folder, data, 'pending.html')
        document = html.fromstring(destination.read_text())
        body = document.xpath('//section[@data-section="07"]')[0].text_content()
        assert '请企业提供' in body and '0万元' not in body and '0元' not in body
        data['sections']['07'] = {'tables': [
            {'type': 'operating-metrics', 'source_kind': 'customer-file', 'rows': [['营收', '用户提供数值', '客户财务资料']]},
            {'type': 'paid-capital', 'source_kind': 'government-source', 'rows': [['本企业股东', '已核认缴', '已核实缴', '待核比例', '公开原文日期']]},
        ]}
        sales_generate(module, folder, data, 'provided.html')
        data['sections']['07']['tables'][0]['source_kind'] = 'third-party-estimate'
        try:
            sales_generate(module, folder, data, 'invalid.html')
        except ValueError as error:
            assert '用户提供' in str(error)
        else:
            raise AssertionError('estimated financial metrics must not render')
        assert not (folder / 'invalid.html').exists()
        missing = sales_input()
        _, destination = sales_generate(module, folder, missing, 'pending-after-provided.html')
        assert '用户提供数值' not in destination.read_text()


def test_sales_html_new_file_cli_and_cross_platform_font_uris():
    from pathlib import PurePosixPath, PureWindowsPath
    import subprocess
    import sys
    with sales_html_case() as (folder, module):
        source = folder / 'input.json'
        source.write_text(json.dumps(sales_input(), ensure_ascii=False))
        output = folder / 'report.html'
        argv = [sys.executable, '-B', str(SKILLS / 'enterprise-panorama-analysis/scripts/build_sales_html.py'), '--input', str(source), '--output', str(output)]
        first = subprocess.run(argv, text=True, capture_output=True)
        assert first.returncode == 0 and json.loads(first.stdout)['status'] == 'pass'
        original = output.read_bytes()
        second = subprocess.run(argv, text=True, capture_output=True)
        assert second.returncode == 2 and json.loads(second.stdout)['status'] == 'fail'
        assert output.read_bytes() == original
        invalid = sales_input()
        invalid['sections']['03']['paragraphs'] = ['单源待核（⻩）']
        source.write_text(json.dumps(invalid, ensure_ascii=False))
        bad = subprocess.run(argv[:-1] + [str(folder / 'bad.html')], text=True, capture_output=True)
        assert bad.returncode == 2 and json.loads(bad.stdout)['status'] == 'fail'
        assert not (folder / 'bad.html').exists()
        assert '%20' in module['font_uri'](PurePosixPath('/签名字体/a b.otf'))
        uri = module['font_uri'](PureWindowsPath("C:/签名 素材/a'quote.otf"))
        assert uri.startswith('file:///C:/') and '%20' in uri and '%27' in uri and '\\' not in uri
        registry = json.loads((SKILLS / 'client-runtime-operations.json').read_text())
        operation = next(item for item in registry['operations'] if item['id'] == 'enterprise-panorama-analysis.build-sales-html')
        assert operation['parameters']['output']['extensions'] == ['.html']
        assert operation['network'] == 'none' and operation['sandbox_mode'] == 'workspace-write'
        assert all((SKILLS / path).is_file() for path in operation['files'])
