"""Carry source-field mappings through the DOCX write and readback."""

from collections import defaultdict
from pathlib import Path


def pointer(*parts):
    return '/' + '/'.join(str(part).replace('~', '~0').replace('/', '~1') for part in parts)


def source_rows(fields, manifest):
    if not isinstance(fields, list):
        raise ValueError('source_fields 须为数组')
    rows = []
    for field in fields:
        if not isinstance(field, dict) or not all(key in field for key in ('source_file', 'source_location', 'original_value')):
            raise ValueError('source_fields 每项须提供源文件、源位置和原值')
        if not all(isinstance(field[key], str) and field[key].strip() for key in ('source_file', 'source_location')):
            raise ValueError('source_file 和 source_location 须为非空字符串')
        target = field.get('target_field')
        if target is not None and (not isinstance(target, str) or not target.startswith('/')):
            raise ValueError('target_field 须为回填字段的 JSON Pointer 或 null')
        path = Path(field['source_file']).expanduser()
        rows.append({
            'source_file': str((manifest.parent / path).resolve()),
            'source_location': field['source_location'],
            'original_value': field['original_value'],
            'target_field': target,
            'converted_value': None,
            'reason': field.get('reason') or ('已映射，等待回填' if target else '未识别目标字段'),
            'status': 'mapped' if target else 'unrecognized',
        })
    return rows


class ImportBatch:
    def __init__(self, metadata, spec_path, output):
        if not isinstance(metadata, dict) or not isinstance(metadata.get('rows', []), list):
            raise ValueError('batch_check 须为包含 rows 数组的对象')
        self.batch_id = metadata.get('batch_id') or str(output.resolve())
        self.source_file = str(spec_path.resolve()) if spec_path else '本次结构化输入'
        self.mappings = defaultdict(list)
        self.rows = []
        self.writes = []
        self.used_mappings = set()
        for row in metadata.get('rows', []):
            fields = {'source_file', 'source_location', 'original_value', 'target_field', 'converted_value', 'reason', 'status'}
            if not isinstance(row, dict) or not fields.issubset(row) or row['status'] not in ('mapped', 'unrecognized'):
                raise ValueError('batch_check.rows 须沿用盘点回执中的来源字段及状态')
            if row['status'] == 'mapped':
                if not isinstance(row['target_field'], str) or not row['target_field'].startswith('/'):
                    raise ValueError('已映射行的目标字段须为 JSON Pointer')
                self.mappings[row['target_field']].append(row)
            else:
                self.rows.append(dict(row))

    def add(self, field, original, converted, reason, *, node=None, source=None, kind='field', read_value=None):
        location = source or field
        source_records = self.mappings.get(location)
        if source_records:
            self.used_mappings.add(location)
        else:
            source_records = [{
                'source_file': self.source_file, 'source_location': location, 'original_value': original,
            }]
        for origin in source_records:
            mapping_reason = origin.get('reason')
            row = {
                'source_file': origin['source_file'], 'source_location': origin['source_location'],
                'original_value': origin['original_value'], 'target_field': field, 'converted_value': converted,
                'reason': f'{mapping_reason}。{reason}' if mapping_reason else reason,
                'kind': kind, 'status': 'incomplete' if node is not None else 'unrecognized',
            }
            self.rows.append(row)
            if node is not None:
                self.writes.append((node, row, read_value))

    def locate(self, tree):
        for node, row, _ in self.writes:
            row['artifact_location'] = tree.getpath(node)

    def check(self, root, namespaces, read_text, *, text_key=lambda value: value):
        for _, row, read_value in self.writes:
            nodes = root.xpath(row['artifact_location'], namespaces=namespaces)
            row['actual_value'] = read_text(nodes[0]) if len(nodes) == 1 else None
            if len(nodes) == 1 and read_value is not None:
                row['actual_value'] = read_value(row['actual_value'])
            if row['actual_value'] is not None and text_key(row['actual_value']) == text_key(row['converted_value']):
                row['status'] = 'completed'
            else:
                row['check_reason'] = '成品回读值与转换值不一致' if nodes else '成品缺少目标位置'

    def report(self, counts, output, readback_errors=()):
        for field in sorted(self.mappings.keys() - self.used_mappings):
            for row in self.mappings[field]:
                self.rows.append({**row, 'status': 'unrecognized', 'reason': '本次回填缺对应目标字段'})
        incomplete = [row for row in self.rows if row['status'] != 'completed']
        partial = bool(incomplete or readback_errors or any(check['status'] != 'completed' for check in counts.values()))
        return {
            'batch_id': self.batch_id,
            'status': 'partial' if partial else 'completed',
            'rows': self.rows,
            'counts': counts,
            'readback_errors': list(readback_errors),
            'intermediate_artifact': str(output.resolve()) if partial else None,
        }
