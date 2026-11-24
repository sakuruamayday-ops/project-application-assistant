import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'project_state.py'


class ProjectSyncTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        self.local = {
            'identity': {'enterprise': '甲企业', 'project': '高企', 'year': 2026},
            'version': 7, 'facts': {'设备': 5, '确认': True}, 'pending': ['证明材料'],
            'policy': '本轮同步范围外',
        }
        self.local_file = self.write('local.json', self.local)
        self.operations = [{'action': 'write', 'target': '项目状态'}, {'action': 'read', 'target': '项目状态'}]
        self.operation_file = self.write('operations.json', self.operations)

    def write(self, name, value):
        path = self.directory / name
        path.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
        return path

    def run_cli(self, *options, code=0, raw=False):
        result = subprocess.run([sys.executable, str(SCRIPT), *map(str, options)], capture_output=True, text=True)
        self.assertEqual(result.returncode, code, result.stderr or result.stdout)
        return result.stdout if raw else json.loads(result.stdout)

    def prepare(self, *fields):
        raw = self.run_cli('prepare-sync', self.local_file, '--fields', *fields, raw=True)
        prepared = self.directory / 'prepared.json'
        prepared.write_text(raw, encoding='utf-8')
        return json.loads(raw), prepared

    def verify(self, actual, code=0):
        _, preflight = self.prepare('pending', 'facts')
        target = self.write('readback.json', actual)
        return self.run_cli('verify-sync', preflight, '--readback', target, '--operations', self.operation_file, code=code)

    def test_authorized_content_matches_after_host_readback(self):
        result = self.verify({**self.local, 'policy': '另一版本，范围外'})
        self.assertEqual(result['status'], 'pass')
        self.assertEqual(result['fields'], ['facts', 'pending'])
        self.assertEqual(result['local_state'], {'facts': self.local['facts'], 'pending': ['证明材料']})
        self.assertEqual(result['target_readback']['facts'], result['local_state']['facts'])
        self.assertEqual(result['differences'], [])
        self.assertNotIn('policy', result['target_readback'])
        self.assertEqual(result['operations'], self.operations)

    def test_changed_field_inside_array_is_located(self):
        facts = {**self.local['facts'], '设备项': [{'编号': 5}]}
        self.write('local.json', {**self.local, 'facts': facts})
        target = {**self.local, 'facts': {**facts, '设备项': [{'编号': 6}]}}
        result = self.verify(target, code=2)
        self.assertEqual(result['differences'], [
            {'path': '/facts/设备项/0/编号', 'kind': 'mismatch', 'expected': 5, 'actual': 6},
        ])

    def test_partial_save_returns_difference_and_keeps_local_data_and_operations(self):
        target = {key: value for key, value in self.local.items() if key != 'pending'}
        result = self.verify(target, code=2)
        self.assertEqual(result['status'], 'fail')
        self.assertEqual(result['differences'], [
            {'path': '/pending', 'kind': 'missing', 'expected': ['证明材料'], 'actual': None},
        ])
        self.assertEqual(result['local_state']['pending'], ['证明材料'])
        self.assertEqual(result['target_readback']['facts'], self.local['facts'])
        self.assertEqual(result['operations'][0]['action'], 'write')
        self.assertEqual(json.loads(self.local_file.read_text(encoding='utf-8')), self.local)

    def test_same_content_does_not_accept_wrong_version(self):
        result = self.verify({**self.local, 'version': 6}, code=2)
        self.assertEqual(result['status'], 'fail')
        self.assertEqual(result['differences'], [{'path': '/version', 'kind': 'mismatch', 'expected': 7, 'actual': 6}])

    def test_same_content_does_not_accept_wrong_company(self):
        result = self.verify({**self.local, 'identity': {**self.local['identity'], 'enterprise': '乙企业'}}, code=2)
        self.assertEqual(result['differences'], [{
            'path': '/identity/enterprise', 'kind': 'mismatch', 'expected': '甲企业', 'actual': '乙企业',
        }])

    def test_unexpected_authorized_child_is_located_even_when_null(self):
        target = {**self.local, 'facts': {**self.local['facts'], '备注/测试~': None}}
        result = self.verify(target, code=2)
        self.assertEqual(result['differences'], [
            {'path': '/facts/备注~1测试~0', 'kind': 'unexpected', 'expected': None, 'actual': None},
        ])

    def test_readback_error_is_recorded_with_operations(self):
        prepared, preflight = self.prepare('facts')
        result = self.run_cli('verify-sync', preflight, '--readback-error', '宿主连接超时',
                              '--operations', self.operation_file, code=2)
        self.assertEqual(result['status'], 'fail')
        self.assertEqual(result['local_state'], prepared['local_state'])
        self.assertIsNone(result['target_readback'])
        self.assertEqual(result['differences'][0]['kind'], 'readback_failed')
        self.assertEqual(result['differences'][0]['actual'], '宿主连接超时')
        self.assertEqual(result['operations'], self.operations)

    def test_field_comparison_keeps_exact_numbers_and_json_types(self):
        before = r'{"version":7,"identity":"甲","facts":{"😀":-0.0,"\ue000":1e2,"b":1.2345678901234567890,"a":["1",1,true,null]}}'
        self.local_file.write_text(before, encoding='utf-8')
        _, snapshot = self.prepare('facts')
        readback = self.directory / 'readback.json'
        equivalent = before.replace('-0.0', '0').replace('1e2', '100')
        equivalent = equivalent.replace('1.2345678901234567890', '1.234567890123456789')
        readback.write_text(equivalent, encoding='utf-8')
        result = self.run_cli('verify-sync', snapshot, '--readback', readback)
        self.assertEqual(result['differences'], [])

        changed = equivalent.replace('1.234567890123456789', '1.234567890123456788')
        readback.write_text(changed.replace('"1",1,true', '"1",1,1'), encoding='utf-8')
        result = self.run_cli('verify-sync', snapshot, '--readback', readback, code=2)
        self.assertEqual([change['path'] for change in result['differences']], ['/facts/a/2', '/facts/b'])
        self.assertEqual(result['differences'][0], {
            'path': '/facts/a/2', 'kind': 'mismatch', 'expected': True, 'actual': 1,
        })


if __name__ == '__main__':
    unittest.main()
