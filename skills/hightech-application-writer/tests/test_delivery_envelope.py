import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from docx import Document


SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'hightech_delivery_gate.py'


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class DeliveryEnvelopeTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        self.docx = self.directory / '高企申请书.docx'
        self.report = self.directory / '最终交付.json'
        document = Document()
        document.add_paragraph('甲企业申请书')
        document.save(self.docx)

    def write_receipt(self, name, contents):
        path = self.directory / name
        path.write_text(json.dumps(contents, ensure_ascii=False), encoding='utf-8')
        return path

    def finalize(self, *options, code=0):
        run = subprocess.run([sys.executable, str(SCRIPT), 'finalize', str(self.docx),
                              '--report', str(self.report), *map(str, options)], capture_output=True, text=True)
        self.assertEqual(run.returncode, code, run.stderr or run.stdout)
        payload = json.loads(run.stdout)
        self.assertEqual(payload, json.loads(self.report.read_text(encoding='utf-8')))
        return payload

    def test_verified_docx_has_success_envelope_and_existing_receipt_fields(self):
        info = {'path': str(self.docx.resolve()), 'sha256': file_hash(self.docx)}
        copy = {'stage': 'template-copy', 'status': 'pass', 'template': info, 'working_copy': info}
        lint = {'stage': 'summary-lint', 'status': 'pass', 'docx': info}
        wps = {'stage': 'wps-review', 'status': 'pass', 'docx': info, 'pages': []}
        brand = {'status': 'passed', 'artifacts': [info]}
        paths = [self.write_receipt(f'{index}.json', value) for index, value in enumerate((copy, lint, wps, brand))]
        options = [part for option, path in zip(('--copy-receipt', '--summary-receipt', '--wps-receipt', '--brand-receipt'), paths)
                   for part in (option, path)]
        result = self.finalize(*options)
        delivery = result['delivery']
        self.assertEqual(set(delivery), {'status', 'resource_id', 'content', 'sha256', 'delivered_at'})
        self.assertEqual(result['status'], 'pass')
        self.assertEqual(delivery['status'], 'success')
        self.assertEqual(delivery['resource_id'], 'hightech-application-delivery')
        self.assertEqual(result['copy'], copy)
        self.assertEqual(result['summary'], lint)
        self.assertEqual(result['wps'], wps)
        self.assertEqual(result['brand_receipt']['sha256'], file_hash(paths[-1]))
        for artifact in [self.docx, *paths]:
            self.assertIn(f'`{artifact.resolve()}`，SHA-256 `{file_hash(artifact)}`', delivery['content'])

    def test_available_draft_is_delivered_as_partial(self):
        result = self.finalize()
        self.assertIs(result['delivery_allowed'], True)
        self.assertEqual(result['status'], 'warning')
        self.assertEqual(result['delivery']['status'], 'partial')
        self.assertEqual(result['docx']['sha256'], file_hash(self.docx))
        self.assertIn('高企申请书文件索引', result['delivery']['content'])

    def test_missing_docx_returns_explicit_fail_envelope(self):
        self.docx.unlink()
        result = self.finalize(code=2)
        self.assertEqual(result['status'], 'fail')
        self.assertEqual(result['delivery']['status'], 'fail')
        self.assertIs(result['delivery_allowed'], False)
        self.assertIsNone(result['artifact'])
        content = result['delivery']['content']
        self.assertIn(f'成品不可读取：{self.docx.resolve()}', content)
        self.assertEqual(result['delivery']['sha256'], hashlib.sha256(content.encode('utf-8')).hexdigest())

    def test_digest_covers_entire_exact_utf8_markdown_content(self):
        delivery = self.finalize()['delivery']
        content = f'# 高企申请书文件索引\n\n- 高企申请书 `{self.docx.resolve()}`，SHA-256 `{file_hash(self.docx)}`'
        self.assertEqual(delivery['content'], content)
        self.assertEqual(delivery['sha256'], hashlib.sha256(content.encode('utf-8')).hexdigest())

    def test_delivery_time_is_the_iso_utc_time_of_this_receipt(self):
        started = datetime.now(timezone.utc)
        result = self.finalize()
        ended = datetime.now(timezone.utc)
        delivered = datetime.fromisoformat(result['delivery']['delivered_at'])
        self.assertEqual(delivered.utcoffset(), timezone.utc.utcoffset(None))
        self.assertEqual(result['delivery']['delivered_at'], result['generated_at'])
        self.assertLessEqual(started, delivered)
        self.assertLessEqual(delivered, ended)

    def test_report_target_cannot_overwrite_indexed_docx(self):
        original = file_hash(self.docx)
        run = subprocess.run([sys.executable, str(SCRIPT), 'finalize', str(self.docx), '--report', str(self.docx)],
                             capture_output=True, text=True)
        self.assertEqual(run.returncode, 2)
        result = json.loads(run.stdout)
        self.assertEqual(result['delivery']['status'], 'fail')
        self.assertEqual(result['errors'], ['交付回执需另存，当前路径与成品或输入回执相同'])
        self.assertEqual(file_hash(self.docx), original)


if __name__ == '__main__':
    unittest.main()
