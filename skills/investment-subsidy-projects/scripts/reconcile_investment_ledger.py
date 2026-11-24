#!/usr/bin/env python3
"""检查投资台账日期、逐笔凭证、税额及表列合计。"""
import argparse
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import json
from pathlib import Path

REQUIRED = {"id", "contract", "invoice", "acceptance", "payment", "asset",
            "amount_tax_included", "amount_tax_excluded", "date"}
EVIDENCE_FIELDS = ("invoice", "acceptance", "payment")
AMOUNTS = ("amount_tax_included", "amount_tax_excluded")
CENT = Decimal("0.01")


def decimal_value(value):
    amount = Decimal(str(value))
    if not amount.is_finite():
        raise InvalidOperation
    return amount


def money_yuan(value):
    amount = decimal_value(value)
    if amount != amount.quantize(CENT):
        raise InvalidOperation
    return amount


def evidence_index(evidence, errors):
    index = {}
    for field in EVIDENCE_FIELDS:
        records = evidence.get(field)
        indexed = index[field] = {}
        if not isinstance(records, list) or not records:
            errors.append(f"{field}凭证须为非空数组")
            continue
        for record in records:
            ref = record.get("id") if isinstance(record, dict) else None
            if not isinstance(ref, str) or not ref.strip() or ref in indexed:
                errors.append(f"{field}凭证编号缺失或重复:{ref}")
                continue
            indexed[ref] = record
    return index


def check_payment(item, gross, evidence, label, errors):
    invoice_amount = gross
    paid = None
    if evidence is not None:
        linked = {}
        for field in EVIDENCE_FIELDS:
            ref = item.get(field)
            record = evidence[field].get(ref) if isinstance(ref, str) else None
            if (record is None or record.get("row") != item["id"]
                    or record.get("contract") != item["contract"]):
                errors.append(f"{label}:{field}凭证缺失或未关联本笔记录及合同:{ref}")
            else:
                linked[field] = record
        if len(linked) != len(EVIDENCE_FIELDS):
            return
        if linked["payment"].get("invoice") != item["invoice"]:
            errors.append(f"{label}:银行付款未对应本笔发票 {item['invoice']}")
            return
        asset_ids = [record.get("asset_id") for record in linked.values()]
        if any(asset_ids) and not all(asset_id == asset_ids[0] for asset_id in asset_ids):
            errors.append(f"{label}:发票、验收及付款关联的资产编号不一致")
        try:
            invoice_amount = money_yuan(linked["invoice"].get("gross"))
        except InvalidOperation:
            errors.append(f"{label}:发票含税金额缺失或无效")
            return
        if invoice_amount != gross:
            errors.append(f"{label}:原票含税 {invoice_amount} 元与台账含税 {gross} 元不一致")
        installments = linked["payment"].get("installments")
        try:
            if not isinstance(installments, list) or not installments:
                raise InvalidOperation
            paid = sum((money_yuan(part["金额"]) for part in installments), Decimal(0))
        except (InvalidOperation, KeyError, TypeError):
            errors.append(f"{label}:银行实际付款流水缺失或金额无效")
            return
    reported_paid = item.get("bank_paid_yuan")
    if paid is None or reported_paid is not None:
        try:
            reported_paid = money_yuan(reported_paid)
        except InvalidOperation:
            errors.append(f"{label}:bank_paid_yuan 缺银行实付金额或金额无效")
            return
        if paid is None:
            paid = reported_paid
        elif paid != reported_paid:
            errors.append(f"{label}:银行流水合计 {paid} 元与台账银行实付 {reported_paid} 元不一致")
    difference = paid - invoice_amount
    if difference:
        errors.append(f"{label}:发票含税 {invoice_amount} 元，银行实付 {paid} 元，差额 {difference} 元")


def iso_date(value):
    if not isinstance(value, str):
        raise ValueError("日期须为 YYYY-MM-DD")
    parsed = date.fromisoformat(value)
    if parsed.isoformat() != value:
        raise ValueError("日期须为 YYYY-MM-DD")
    return parsed


def period_bounds(period, errors):
    if period is None:
        return None
    try:
        start, end = iso_date(period["start"]), iso_date(period["end"])
        if start > end:
            raise ValueError("项目期起始日晚于结束日")
        return start, end
    except (KeyError, TypeError, ValueError):
        errors.append("项目期须有真实日期 start、end，且起始日不晚于结束日")
        return None


def reconcile(payload, today, evidence=None):
    errors = []
    envelope = payload if isinstance(payload, dict) else {}
    rows = envelope.get("records") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        errors.append("台账须为逐笔记录的数组")
        rows = []
    elif not rows:
        errors.append("台账无可核验记录")

    bounds = period_bounds(envelope.get("project_period"), errors)
    declared = envelope.get("table_totals", {})
    if not isinstance(declared, dict):
        errors.append("table_totals 须为表列金额字段与合计的对象")
        declared = {}
    indexed = evidence_index(evidence, errors) if evidence is not None else None

    totals = dict.fromkeys((*AMOUNTS, *declared), Decimal(0))
    evidence_totals = dict.fromkeys(AMOUNTS, Decimal(0))
    verified_record_ids = []
    incomplete = set()
    seen = {}
    rate_checked = 0
    for index, item in enumerate(rows, 1):
        if not isinstance(item, dict):
            errors.append(f"{index}:台账记录须为对象")
            incomplete.update(totals)
            continue
        row_start = len(errors)
        label = f"{index}（{item['id']}）" if item.get("id") else str(index)
        missing = sorted(key for key in REQUIRED if item.get(key) is None
                         or isinstance(item[key], str) and not item[key].strip()
                         or key in EVIDENCE_FIELDS and not isinstance(item[key], str))
        if missing:
            errors.append(f"{label}:缺少{','.join(missing)}")

        row_date = None
        if "date" not in missing:
            try:
                row_date = iso_date(item["date"])
                if row_date > today:
                    errors.append(f"{label}:日期 {row_date} 晚于当前日期 {today}")
                if bounds and not bounds[0] <= row_date <= bounds[1]:
                    errors.append(f"{label}:日期 {row_date} 不在项目期 {bounds[0]} 至 {bounds[1]}")
            except ValueError:
                errors.append(f"{label}:无效日期 {item['date']!r}")

        amounts = {}
        for key in totals:
            try:
                amounts[key] = decimal_value(item.get(key))
                totals[key] += amounts[key]
            except InvalidOperation:
                incomplete.add(key)
                if key not in missing:
                    errors.append(f"{label}:{key} 不是有效十进制金额")

        gross, net = (amounts.get(key) for key in AMOUNTS)
        voucher = str(item.get("voucher_number") or item.get("id") or "").strip()
        if voucher and row_date and gross is not None:
            key = (voucher, gross, row_date)
            if key in seen:
                errors.append(f"{label}:重复流水，凭证号 {voucher}、金额 {gross}、日期 {row_date}，"
                              f"与第 {seen[key]} 行重复")
            else:
                seen[key] = index

        if gross is None or net is None:
            continue
        if net > gross:
            errors.append(f"{label}:未税额 {net} 高于含税额 {gross}")
        if not {"id", "contract", *EVIDENCE_FIELDS}.intersection(missing):
            check_payment(item, gross, indexed, label, errors)
        raw_rate = item.get("tax_rate", envelope.get("tax_rate"))
        if raw_rate not in (None, ""):
            try:
                value = str(raw_rate).strip()
                rate = decimal_value(value[:-1]) / 100 if value.endswith(("%", "％")) else decimal_value(value)
                if not 0 <= rate <= 1:
                    raise InvalidOperation
                expected_net = (gross / (1 + rate)).quantize(CENT, rounding=ROUND_HALF_UP)
                actual_net = net.quantize(CENT, rounding=ROUND_HALF_UP)
            except InvalidOperation:
                errors.append(f"{label}:无效税率 {raw_rate!r}，填写 0 至 1 的小数或百分比")
            else:
                rate_checked += 1
                if actual_net != expected_net:
                    errors.append(f"{label}:税率 {rate:.2%} 反算未税额 {expected_net}，台账未税额 {net}")
        if len(errors) == row_start:
            verified_record_ids.append(item["id"])
            for field in AMOUNTS:
                evidence_totals[field] += amounts[field]

    reconciliations = {}
    for field, value in declared.items():
        try:
            table_total = decimal_value(value)
        except InvalidOperation:
            errors.append(f"{field}:表列合计不是有效十进制金额")
            continue
        if field in incomplete:
            errors.append(f"{field}:明细金额缺失或无效，无法核对表列合计 {table_total}")
            continue
        difference = totals[field] - table_total
        reconciliations[field] = {"detail": str(totals[field]), "declared": str(table_total), "difference": str(difference)}
        if difference:
            unit = " 万元" if field.endswith("_wanyuan") else ""
            errors.append(f"{field}:明细合计 {totals[field]}{unit}，表列合计 {table_total}{unit}，差额 {difference}{unit}")

    return {"status": "fail" if errors else "pass", "count": len(rows),
            "total_tax_included": str(evidence_totals[AMOUNTS[0]]), "total_tax_excluded": str(evidence_totals[AMOUNTS[1]]),
            "verified_record_ids": verified_record_ids,
            "project_period_checked": bounds is not None, "tax_rate_checked": rate_checked,
            "table_reconciliations": reconciliations, "errors": errors}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ledger", type=Path)
    parser.add_argument("--invoices", type=Path)
    parser.add_argument("--acceptances", type=Path)
    parser.add_argument("--payments", type=Path)
    args = parser.parse_args()
    paths = (args.invoices, args.acceptances, args.payments)
    if any(paths) and not all(paths):
        parser.error("--invoices、--acceptances、--payments 须同时提供")
    try:
        evidence = {field: json.loads(path.read_text(encoding="utf-8"))
                    for field, path in zip(EVIDENCE_FIELDS, paths)} if all(paths) else None
        result = reconcile(json.loads(args.ledger.read_text(encoding="utf-8")), date.today(), evidence)
    except (OSError, ValueError) as error:
        result = {"status": "fail", "errors": [str(error)]}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
