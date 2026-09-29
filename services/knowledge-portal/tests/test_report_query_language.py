import sqlite3

import pytest

from app.recognized_enterprise_discovery import build_recognition_query_plan, recognition_search
from app.three_first_routing import plan_three_first_analysis


@pytest.mark.parametrize('query', ['这家企业能报首台套吗', '这个产品可以申报首台套吗', '这家企业能否报首台套', '能不能申报首台套'])
def test_feasibility_does_not_search_question_words_or_all_enterprises(query):
    result = recognition_search(sqlite3.connect(':memory:'), query=query)
    assert result['route_to'] == 'enterprise_lifecycle_decision'
    plan = plan_three_first_analysis(query)
    assert plan['route_to'] == 'enterprise_lifecycle_decision'
    assert plan['product_name'] == ''
    assert not plan['routes']['public_list_search']


@pytest.mark.parametrize('query', ['工业机器人这个产品有做过三首的吗', '工业机器人有报过首台套吗？'])
def test_product_precedent_extracts_product_and_keeps_history_route(query):
    plan = plan_three_first_analysis(query)
    assert plan['product_name'] == '工业机器人'
    assert plan['routes']['public_list_search']
    assert plan['route_to'] == 'three_first_analysis'


def test_known_conversation_fields_survive_feasibility_routing():
    plan = plan_three_first_analysis('这家企业能报首台套吗', enterprise_name='企业甲', product_name='工业机器人')
    assert plan['enterprise_name'] == '企业甲'
    assert plan['product_name'] == '工业机器人'
    assert plan['routes']['public_list_search']


@pytest.mark.parametrize('phrase', ['专精小巨人', '专精、小巨人', '专精和小巨人'])
def test_shorthand_keeps_both_projects(phrase):
    plan = build_recognition_query_plan('工业机器人有报过'+phrase+'的吗')
    assert plan['projects'] == ['专精特新中小企业', '小巨人']


def test_formal_small_giant_name_stays_single_project():
    plan = build_recognition_query_plan('工业机器人有哪些国家专精特新小巨人企业')
    assert plan['projects'] == ['国家专精特新小巨人企业']


def test_broad_subject_does_not_promote_related_children_to_exact():
    taxonomy = [
        {'canonical_subject': '工业机器人', 'exact_terms': ['工业机器人制造'], 'related_terms': ['自动化设备']},
        {'canonical_subject': '巡检机器人', 'exact_terms': ['巡检系统'], 'related_terms': ['工业机器人']},
    ]
    plan = build_recognition_query_plan('工业机器人有哪些小巨人', taxonomy=taxonomy)
    assert plan['subjects'] == ['工业机器人']
    assert '巡检系统' not in plan['exact_terms']
    assert plan['related_terms'] == ['自动化设备']
    fallback = build_recognition_query_plan('自动化设备有哪些小巨人', taxonomy=taxonomy)
    assert fallback['subjects'] == ['工业机器人']

@pytest.mark.parametrize('period,years', [
    ('2023到2025年', [2023, 2024, 2025]),
    ('2023年至2025年', [2023, 2024, 2025]),
    ('2023—2025年', [2023, 2024, 2025]),
    ('2023年、2025年', [2023, 2025]),
])
def test_year_ranges_and_discrete_years(period, years):
    assert build_recognition_query_plan(period+'工业机器人有哪些小巨人')['years'] == years


def test_explicit_year_selection_is_not_expanded():
    assert build_recognition_query_plan('2023到2025年工业机器人小巨人', years=[2023, 2025])['years'] == [2023, 2025]


@pytest.mark.parametrize('negation', ['不要', '不包括', '不包含', '排除', '不查'])
def test_excluded_project_is_removed_even_from_explicit_projects(negation):
    q = '工业机器人有哪些小巨人，'+negation+'省级专精特新中小企业'
    for projects in [[], ['小巨人', '专精特新中小企业']]:
        plan = build_recognition_query_plan(q, projects=projects)
        assert plan['projects'] == ['小巨人']
        assert plan['regions'] == []


def test_pagination_counts_groups_and_preserves_upstream_truncation(monkeypatch):
    import app.recognized_enterprise_discovery as module
    def discover(*args, **kwargs):
        return {'verified_matches': [], 'pending_candidates': [],
                'coverage_ledger': {'verified_truncated': True, 'pending_truncated': False}}
    monkeypatch.setattr(module, 'discover_recognized_enterprises', discover)
    result = recognition_search(sqlite3.connect(':memory:'), query='工业机器人有哪些小巨人', subject_terms=['工业机器人'], limit=5)
    assert result['pagination']['returned'] == 0
    assert result['pagination']['is_truncated'] is True
    assert result['pagination']['supports_offset'] is False


@pytest.mark.parametrize('query', [
    '国家专精特新小巨人企业 四足机器人',
    '四足机器人有哪些国家小巨人同行',
    '2023到2025年四足机器人有哪些国家小巨人',
])
def test_products_outside_taxonomy_remain_searchable(query):
    plan = build_recognition_query_plan(query, taxonomy=[{'canonical_subject': '智能水表', 'exact_terms': [], 'related_terms': []}])
    assert plan['subjects'] == ['四足机器人']
    assert plan['exact_terms'] == ['四足机器人']
    assert not plan['clarification']


@pytest.mark.parametrize('query', ['有哪些小巨人企业', '这个产品有哪些小巨人', '这家企业有哪些小巨人同行'])
def test_missing_subject_is_not_invented_by_unknown_topic_fallback(query):
    plan = build_recognition_query_plan(query)
    assert plan['subjects'] == []
    assert plan['clarification']


def test_unlisted_product_keeps_enterprise_word_inside_name():
    plan = build_recognition_query_plan('国家小巨人企业 企业管理软件')
    assert plan['subjects'] == ['企业管理软件']


def test_unlisted_search_keywords_do_not_collapse_into_one_subject():
    plan = build_recognition_query_plan('人形机器人 具身智能 整机装备 国家专精特新小巨人企业')
    assert plan['subjects'] == ['人形机器人', '具身智能', '整机装备']
