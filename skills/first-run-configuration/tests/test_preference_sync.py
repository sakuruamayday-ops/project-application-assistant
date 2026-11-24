import argparse
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import manage_preferences as preferences


class PreferenceSyncTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / 'preferences.json'
        self.log = self.path.with_name('preference-merge-conflicts.json')
        self.args = argparse.Namespace(file=self.path, endpoint='https://example.invalid', token='fixture', summary='合并')
        self.base = {'output': {'detail_level': 'standard'}, 'region': {'city': '杭州'}}
        self.edited = {**self.base, 'output': {'detail_level': 'concise'}}
        self.remote = {**self.base, 'region': {'city': '宁波'}}
        self.merged = {**self.remote, 'output': self.edited['output']}
        self.path.write_text(json.dumps({
            'schema_version': 1, 'revision': 4, 'preferences': self.edited,
            '_meta': {'dirty': True, 'base_revision': 4, 'base_preferences': self.base},
        }, ensure_ascii=False), encoding='utf-8')
        self.original = self.path.read_bytes()

    def sync(self, readback, *, remote=None, written=None):
        replies = [remote or {'revision': 5, 'preferences': self.remote}, written or {'revision': 6, 'preferences': self.merged}, readback]
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.object(preferences, 'request_json', side_effect=replies) as request, redirect_stdout(stdout), redirect_stderr(stderr):
            status = preferences.command_sync(self.args)
        calls = [call.args for call in request.call_args_list]
        return status, calls, stdout.getvalue(), stderr.getvalue()

    def conflict(self, stage):
        self.assertEqual(self.path.read_bytes(), self.original)
        log = json.loads(self.log.read_text(encoding='utf-8'))
        self.assertEqual(log['stage'], stage)
        self.assertEqual(log['base_revision'], 4)
        self.assertEqual(log['status'], 'fail')
        return log

    def test_writes_three_way_merge_and_commits_baseline_from_separate_get(self):
        status, calls, output, _ = self.sync({'revision': 6, 'preferences': self.merged},
                                             written={'revision': 9, 'preferences': {}})
        self.assertEqual(status, 0)
        self.assertEqual([call[0] for call in calls], ['GET', 'PUT', 'GET'])
        self.assertEqual(calls[1][4], {'preferences': self.merged, 'base_revision': 5, 'change_summary': '合并'})
        self.assertIn('回读核对通过 R6', output)
        saved = preferences.read_json(self.path)
        self.assertEqual(saved['preferences'], self.merged)
        self.assertEqual(saved['_meta']['base_revision'], 6)
        self.assertEqual(saved['_meta']['base_preferences'], self.merged)
        self.assertIs(saved['_meta']['dirty'], False)

    def test_old_readback_revision_rejects_identical_content_and_keeps_baseline(self):
        status, _, _, output = self.sync({'revision': 5, 'preferences': self.merged})
        self.assertEqual(status, 3)
        self.assertIn('原基线已保留', output)
        log = self.conflict('verify')
        self.assertEqual(log['expected_revision'], 6)
        self.assertEqual(log['actual_revision'], 5)
        self.assertEqual(log['conflicts'], [{'path': '/revision', 'kind': 'mismatch', 'expected': 6, 'actual': 5}])

    def test_readback_failure_is_explicit_without_a_second_write(self):
        status, calls, _, output = self.sync(RuntimeError('回读超时'))
        self.assertEqual(status, 3)
        self.assertEqual([call[0] for call in calls], ['GET', 'PUT', 'GET'])
        self.assertIn('偏好同步失败（readback）', output)
        log = self.conflict('readback')
        self.assertEqual(log['conflicts'], [{'reason': '回读超时'}])
        self.assertEqual(log['expected_revision'], 6)
        self.assertIsNone(log['actual_revision'])

    def test_readback_locates_a_changed_missing_or_unexpected_field(self):
        cases = (
            ({'detail_level': 'standard'}, '/preferences/output/detail_level', 'mismatch', 'concise', 'standard'),
            ({}, '/preferences/output/detail_level', 'missing', 'concise', None),
            ({'detail_level': 'concise', 'unknown': 'extra'}, '/preferences/output/unknown', 'unexpected', None, 'extra'),
        )
        for output, path, kind, expected, actual in cases:
            with self.subTest(kind=kind):
                changed = {**self.merged, 'output': output}
                status, calls, _, _ = self.sync({'revision': 6, 'preferences': changed})
                self.assertEqual(status, 3)
                self.assertEqual([call[0] for call in calls], ['GET', 'PUT', 'GET'])
                self.assertEqual(self.conflict('verify')['conflicts'], [{
                    'path': path, 'kind': kind, 'expected': expected, 'actual': actual,
                }])

    def test_readback_locates_missing_top_level_fields(self):
        for readback, field, value in (
            ({'revision': 6}, '/preferences', self.merged),
            ({'preferences': self.merged}, '/revision', 6),
        ):
            with self.subTest(field=field):
                status, _, _, _ = self.sync(readback)
                self.assertEqual(status, 3)
                self.assertEqual(self.conflict('readback')['conflicts'], [
                    {'path': field, 'kind': 'missing', 'expected': value, 'actual': None},
                ])

    def test_non_integer_readback_revision_still_fails(self):
        status, _, _, _ = self.sync({'revision': Decimal('6.0'), 'preferences': self.merged})
        self.assertEqual(status, 3)
        self.assertEqual(self.conflict('readback')['conflicts'], [{
            'path': '/revision', 'kind': 'mismatch', 'expected': 6, 'actual': 6,
            'reason': 'revision 须为非负整数',
        }])

    def test_same_field_merge_conflict_is_reported_before_write(self):
        remote = {'revision': 5, 'preferences': {**self.remote, 'output': {'detail_level': 'detailed'}}}
        status, calls, _, _ = self.sync(None, remote=remote)
        self.assertEqual(status, 3)
        self.assertEqual([call[0] for call in calls], ['GET'])
        self.assertEqual(self.conflict('merge')['conflicts'], [{
            'path': 'output.detail_level', 'base': 'standard', 'local': 'concise', 'remote': 'detailed',
        }])

    def test_merge_keeps_number_and_boolean_distinct(self):
        merged, conflicts = preferences.merge_three_way({'enabled': 1}, {'enabled': True}, {'enabled': 1})
        self.assertEqual(conflicts, [])
        self.assertIs(merged['enabled'], True)


if __name__ == '__main__':
    unittest.main()
