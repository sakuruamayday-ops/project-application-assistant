"""Canonical JSON per evidence-ledger/references/result-delivery-contract.md."""

import hashlib
import json
import re
from decimal import Decimal


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"JSON 对象包含重复键：{key}")
        result[key] = value
    return result


def reject_constant(value):
    raise ValueError(f"JSON 数字必须有限：{value}")


def loads(value):
    return json.loads(value, parse_float=Decimal, parse_constant=reject_constant, object_pairs_hook=unique_object)


def quote(value):
    def escape(match):
        character = match[0]
        if character in ('"', '\\'):
            return '\\' + character
        return f'\\u{ord(character):04x}'

    return '"' + re.sub(r'["\\\x00-\x1f]', escape, value) + '"'


def canonical_json(value):
    if value is None:
        return 'null'
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, str):
        return quote(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, (Decimal, float)):
        number = value if isinstance(value, Decimal) else Decimal(str(value))
        if not number.is_finite():
            raise ValueError('JSON 数字必须有限')
        if number.is_zero():
            return '0'
        plain = format(number, 'f')
        return plain.rstrip('0').rstrip('.') if '.' in plain else plain
    if isinstance(value, list):
        return '[' + ','.join(canonical_json(item) for item in value) + ']'
    if isinstance(value, dict) and all(isinstance(key, str) for key in value):
        return '{' + ','.join(f'{quote(key)}:{canonical_json(value[key])}' for key in sorted(value)) + '}'
    raise ValueError(f'不支持的 JSON 数据类型：{type(value).__name__}')


def digest(value):
    return hashlib.sha256(canonical_json(value).encode('utf-8')).hexdigest()


def differences(expected, actual, path=''):
    if isinstance(expected, dict) and isinstance(actual, dict):
        result = []
        for key in sorted(expected.keys() | actual.keys()):
            field = f"{path}/{key.replace('~', '~0').replace('/', '~1')}"
            if key not in actual:
                result.append({'path': field, 'kind': 'missing', 'expected': expected[key], 'actual': None})
            elif key not in expected:
                result.append({'path': field, 'kind': 'unexpected', 'expected': None, 'actual': actual[key]})
            else:
                result.extend(differences(expected[key], actual[key], field))
        return result
    if canonical_json(expected) != canonical_json(actual):
        return [{'path': path, 'kind': 'mismatch', 'expected': expected, 'actual': actual}]
    return []
