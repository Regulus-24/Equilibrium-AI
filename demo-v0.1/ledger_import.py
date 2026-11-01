"""Safe, dependency-free import of CSV/Excel ledger files.

The importer only reads the first worksheet and produces a preview. It never
writes the ledger by itself; the caller must explicitly confirm the preview.
"""
from __future__ import annotations

import hashlib
import json
import base64
import csv
import io
import re
import zipfile
from datetime import date, datetime, timedelta
from xml.etree import ElementTree as ET

from ledger import CATEGORIES, entry_fingerprint, parse_amount


class ImportError(ValueError):
    pass


HEADER_ALIASES = {
    "date": {"日期", "交易日期", "记账日期", "date"},
    "kind": {"收支", "收支类型", "类型", "kind", "type"},
    "amount": {"金额", "交易金额", "发生金额", "amount"},
    "category": {"分类", "类别", "category"},
    "merchant": {"商户", "交易对方", "摘要", "说明", "merchant", "description"},
    "note": {"备注", "附言", "note"},
    "card_last4": {"卡片尾号", "卡号尾号", "尾号", "card_last4", "last4"},
}


def _clean(value):
    return str(value or "").strip()


def _kind(value):
    value = _clean(value).casefold()
    if value in {"收入", "入账", "income", "credit", "贷"}: return "income"
    if value in {"支出", "出账", "expense", "debit", "借"}: return "expense"
    return value


def _date(value):
    text = _clean(value)
    if re.fullmatch(r"\d{4}[-/]\d{1,2}[-/]\d{1,2}", text):
        y, m, d = re.split(r"[-/]", text)
        parsed = date(int(y), int(m), int(d))
        if parsed > date.today(): raise ImportError("日期不能晚于今天。")
        return parsed.isoformat()
    try:
        # Excel's 1900 date system, correcting its historical leap-year bug.
        serial = float(text)
        origin = date(1899, 12, 30)
        parsed = origin + timedelta(days=int(serial))
        if parsed > date.today(): raise ImportError("日期不能晚于今天。")
        return parsed.isoformat()
    except (ValueError, TypeError, OverflowError):
        raise ImportError("日期必须是 YYYY-MM-DD 或 Excel 日期。") from None


def _amount(value):
    text = _clean(value).replace(",", "")
    if text.startswith(("¥", "$")): text = text[1:]
    if text.startswith("-"): raise ImportError("金额不能为负数，请使用收支类型区分收入和支出。")
    return parse_amount(text)


def _rows_from_csv(raw):
    text = raw.decode("utf-8-sig")
    return list(csv.reader(io.StringIO(text)))


def _xlsx_rows(raw):
    try:
        z = zipfile.ZipFile(io.BytesIO(raw))
        shared = []
        if "xl/sharedStrings.xml" in z.namelist():
            root = ET.fromstring(z.read("xl/sharedStrings.xml"))
            shared = ["".join(node.text or "" for node in item.iter() if node.tag.endswith("}t")) for item in root]
        workbook = ET.fromstring(z.read("xl/workbook.xml"))
        first = next(node for node in workbook.iter() if node.tag.endswith("}sheet"))
        rel_id = next((v for k, v in first.attrib.items() if k.endswith("}id")), None)
        rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        target = next(node.attrib["Target"] for node in rels if node.attrib.get("Id") == rel_id)
        path = "xl/" + target.lstrip("/") if not target.startswith("xl/") else target
        root = ET.fromstring(z.read(path))
    except (KeyError, StopIteration, ET.ParseError, zipfile.BadZipFile) as exc:
        raise ImportError("无法读取 XLSX 文件，请导出为标准 Excel 工作簿。") from exc
    rows = []
    for row in root.iter():
        if not row.tag.endswith("}row"): continue
        cells = {}
        for cell in row:
            if not cell.tag.endswith("}c"): continue
            ref = cell.attrib.get("r", "A1")
            col = re.match(r"([A-Z]+)", ref).group(1)
            idx = 0
            for ch in col: idx = idx * 26 + ord(ch) - 64
            idx -= 1
            value = ""
            node = next((n for n in cell if n.tag.endswith("}v") or n.tag.endswith("}is")), None)
            if node is not None:
                if node.tag.endswith("}is"): value = "".join(n.text or "" for n in node.iter() if n.tag.endswith("}t"))
                else: value = node.text or ""
            if cell.attrib.get("t") == "s": value = shared[int(value)]
            cells[idx] = value
        rows.append([cells.get(i, "") for i in range(max(cells.keys(), default=-1) + 1)])
    return rows


def _headers(row):
    found = {}
    for index, raw in enumerate(row):
        text = _clean(raw).casefold()
        for field, aliases in HEADER_ALIASES.items():
            if text in {a.casefold() for a in aliases}: found[field] = index
    required = {"date", "kind", "amount", "category"}
    if not required <= set(found):
        raise ImportError("表头至少需要：日期、收支类型、金额、分类。")
    return found


def preview_bytes(filename, raw, existing_entries=None):
    if not isinstance(filename, str) or not re.search(r"\.(csv|xlsx)$", filename, re.I):
        raise ImportError("仅支持 CSV 或 XLSX 文件。")
    if len(raw) > 5 * 1024 * 1024: raise ImportError("导入文件最多 5 MB。")
    rows = _rows_from_csv(raw) if filename.casefold().endswith(".csv") else _xlsx_rows(raw)
    if not rows: raise ImportError("文件没有数据。")
    headers = _headers(rows[0])
    # Keep compatibility with older callers that passed a list of ids.
    existing_entries = existing_entries or []
    existing_ids = {row for row in existing_entries if isinstance(row, str)}
    existing_fingerprints = {entry_fingerprint(row) for row in existing_entries if isinstance(row, dict)}
    valid, errors, duplicates, seen_fingerprints = [], [], [], set()
    for line, row in enumerate(rows[1:], start=2):
        if not any(_clean(x) for x in row): continue
        try:
            kind = _kind(row[headers["kind"]] if headers["kind"] < len(row) else "")
            category = _clean(row[headers["category"]] if headers["category"] < len(row) else "")
            if kind not in CATEGORIES: raise ImportError("收支类型必须是收入或支出。")
            if not category or len(category) > 20: raise ImportError("分类不能为空且最多20字。")
            if category not in CATEGORIES[kind]: category = "其他"
            cents = _amount(row[headers["amount"]] if headers["amount"] < len(row) else "")
            merchant_index = headers.get("merchant")
            note_index = headers.get("note")
            merchant = _clean(row[merchant_index]) if merchant_index is not None and merchant_index < len(row) else ""
            note = _clean(row[note_index]) if note_index is not None and note_index < len(row) else ""
            card_index = headers.get("card_last4")
            card_last4 = _clean(row[card_index]) if card_index is not None and card_index < len(row) else ""
            if card_last4 and (not card_last4.isdigit() or len(card_last4) != 4):
                raise ImportError("卡片尾号必须是 4 位数字。")
            item = {"kind": kind, "cents": cents, "date": _date(row[headers["date"]]), "category": category,
                    "note": merchant + ("；" + note if note else "")}
            if card_last4: item["card_last4"] = card_last4
            item["id"] = "import-" + hashlib.sha256(json.dumps(item, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:48]
            fingerprint = entry_fingerprint(item)
            if item["id"] in existing_ids:
                duplicates.append({"line": line, "reason": "导入编号已存在"})
                continue
            if fingerprint in existing_fingerprints:
                duplicates.append({"line": line, "reason": "账本中已有相同记录"})
                continue
            if fingerprint in seen_fingerprints:
                duplicates.append({"line": line, "reason": "文件内重复记录"})
                continue
            seen_fingerprints.add(fingerprint)
            valid.append(item)
        except (ImportError, ValueError, IndexError) as exc:
            errors.append({"line": line, "error": str(exc)})
    return {"rows": valid[:1000], "errors": errors[:100], "duplicates": duplicates[:100],
            "duplicate_count": len(duplicates), "total_rows": len(valid),
            "parsed_rows": len(valid) + len(duplicates) + len(errors), "truncated": len(valid) > 1000}


def preview_payload(payload, existing_entries=None):
    if not isinstance(payload, dict) or set(payload) != {"filename", "content_base64"}:
        raise ImportError("导入参数必须包含 filename 和 content_base64。")
    try: raw = base64.b64decode(payload["content_base64"], validate=True)
    except Exception as exc: raise ImportError("文件内容不是有效的 Base64。") from exc
    return preview_bytes(payload["filename"], raw, existing_entries)
