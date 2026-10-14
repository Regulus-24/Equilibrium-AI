"""Local manual ledger. Integer cents; independent of the bank simulation."""
import json
import re
import threading
import hashlib
import uuid
from datetime import date
from pathlib import Path

from vendor.io_utils import atomic_write_json
from analysis import monthly_comparisons

CATEGORIES = {
    "expense": ["餐饮", "购物", "交通", "住房", "日用", "娱乐", "医疗", "学习", "礼物", "其他"],
    "income": ["工资", "兼职", "理财收益", "礼金", "其他"],
}


class LedgerConflict(ValueError):
    pass


def parse_amount(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{1,9}(?:\.[0-9]{1,2})?", value):
        raise ValueError("金额须为正数，最多 9 位整数、2 位小数，不支持逗号或科学计数法。")
    whole, _, fraction = value.partition(".")
    cents = int(whole) * 100 + int(fraction.ljust(2, "0"))
    if cents <= 0:
        raise ValueError("金额必须大于 0。")
    return cents


class Ledger:
    def __init__(self, root):
        self.file = Path(root) / "ledger.json"
        self.lock = threading.RLock()

    def read(self):
        if not self.file.exists():
            return {"entries": {}, "custom_categories": {"income": [], "expense": []}}
        return json.loads(self.file.read_text(encoding="utf-8"))

    @staticmethod
    def version(data):
        return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

    def backup(self):
        with self.lock:
            return {"format": "equilibrium-ledger", "version": 1, "data": self.read()}

    @staticmethod
    def validate_backup(backup):
        def reject():
            raise ValueError("备份格式或记录无效，请选择衡智导出的账本 JSON 文件。")
        if not isinstance(backup, dict) or set(backup) != {"format", "version", "data"} or backup["format"] != "equilibrium-ledger" or type(backup["version"]) is not int or backup["version"] != 1:
            reject()
        data = backup["data"]
        if not isinstance(data, dict) or set(data) != {"entries", "custom_categories"} or not isinstance(data["entries"], dict) or not isinstance(data["custom_categories"], dict) or set(data["custom_categories"]) != set(CATEGORIES):
            reject()
        for kind, names in data["custom_categories"].items():
            if not isinstance(names, list) or len(names) > 100:
                reject()
            known = {name.casefold() for name in CATEGORIES[kind]}
            for name in names:
                if not isinstance(name, str) or not 1 <= len(name) <= 20 or name != name.strip() or name.casefold() in known:
                    reject()
                known.add(name.casefold())
        for key, row in data["entries"].items():
            if not isinstance(row, dict) or set(row) != {"id", "revision", "kind", "cents", "date", "category", "note"}:
                reject()
            if not re.fullmatch(r"[a-zA-Z0-9-]{1,64}", key) or row["id"] != key or type(row["revision"]) is not int or not 1 <= row["revision"] <= 9007199254740991:
                reject()
            if type(row["cents"]) is not int or not 1 <= row["cents"] <= 99999999999 or not isinstance(row["kind"], str) or row["kind"] not in CATEGORIES:
                reject()
            if not isinstance(row["date"], str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", row["date"]):
                reject()
            try:
                if date.fromisoformat(row["date"]) > date.today():
                    reject()
            except ValueError:
                reject()
            if row["category"] not in CATEGORIES[row["kind"]] + data["custom_categories"][row["kind"]] or not isinstance(row["note"], str) or len(row["note"]) > 500:
                reject()
        return json.loads(json.dumps(data))

    def preview_restore(self, payload):
        if set(payload) != {"backup"}:
            raise ValueError("恢复参数无效。")
        data = self.validate_backup(payload["backup"])
        with self.lock:
            current = self.read()
            return {"count": len(data["entries"]), "current_count": len(current["entries"]), "expected_version": self.version(current)}

    def restore(self, payload):
        if set(payload) != {"backup", "expected_version", "confirm"} or payload["confirm"] is not True:
            raise ValueError("请先预览并确认恢复账本。")
        data = self.validate_backup(payload["backup"])
        with self.lock:
            if payload["expected_version"] != self.version(self.read()):
                raise LedgerConflict("预览后账本发生变化，请重新选择文件并确认恢复。")
            # Save a recoverable copy before replacing any records.
            filename = "before-restore-" + uuid.uuid4().hex + ".json"
            folder = self.file.parent / "backups"
            folder.mkdir(exist_ok=True)
            atomic_write_json(folder / filename, self.backup())
            for row in data["entries"].values():
                row["revision"] = uuid.uuid4().int % (2 ** 48) + 1
            atomic_write_json(self.file, data)
            return {"restored": True, "count": len(data["entries"]), "safety_backup": "backups/" + filename}

    def public(self):
        with self.lock:
            data = self.read()
            entries = sorted(data["entries"].values(), key=lambda row: (row["date"], row["id"]), reverse=True)
            months, years, days = {}, {}, {}
            for row in entries:
                for groups, key in ((months, row["date"][:7]), (years, row["date"][:4]), (days, row["date"])):
                    total = groups.setdefault(key, {"income": 0, "expense": 0, "balance": 0, "categories": {"income": {}, "expense": {}}})
                    total[row["kind"]] += row["cents"]
                    total["balance"] += row["cents"] * (1 if row["kind"] == "income" else -1)
                    group = total["categories"][row["kind"]]
                    group[row["category"]] = group.get(row["category"], 0) + row["cents"]
            today = date.today()
            return {"version": self.version(data), "as_of": today.isoformat(), "entries": entries, "months": months, "years": years, "days": days,
                    "comparisons": monthly_comparisons(entries, today),
                    "categories": {kind: names + data["custom_categories"][kind] for kind, names in CATEGORIES.items()}}

    def save(self, payload):
        if set(payload) != {"id", "revision", "kind", "amount", "date", "category", "note"}:
            raise ValueError("记账字段不完整或包含未知字段。")
        entry_id = payload["id"]
        if not isinstance(entry_id, str) or not re.fullmatch(r"[a-zA-Z0-9-]{1,64}", entry_id):
            raise ValueError("记录编号无效，请刷新后重试。")
        if type(payload["revision"]) is not int or payload["revision"] < 0:
            raise ValueError("记录版本无效。")
        kind = payload["kind"]
        if not isinstance(kind, str) or kind not in CATEGORIES:
            raise ValueError("请选择收入或支出。")
        raw_date = payload["date"]
        if not isinstance(raw_date, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", raw_date):
            raise ValueError("请选择有效日期。")
        try:
            parsed_date = date.fromisoformat(raw_date)
        except ValueError:
            raise ValueError("请选择有效日期。") from None
        if parsed_date > date.today():
            raise ValueError("记账日期不能晚于今天，未来预算请勿记为已发生交易。")
        category, note = payload["category"], payload["note"]
        if not isinstance(category, str) or not 1 <= len(category.strip()) <= 20:
            raise ValueError("类别名称请填写 1—20 个字。")
        if not isinstance(note, str) or len(note) > 500:
            raise ValueError("备注最多 500 个字。")
        row = {"id": entry_id, "kind": kind, "cents": parse_amount(payload["amount"]),
               "date": raw_date, "category": category.strip(), "note": note.strip()}
        with self.lock:
            data = self.read()
            known = CATEGORIES[kind] + data["custom_categories"][kind]
            row["category"] = next((name for name in known if name.casefold() == row["category"].casefold()), row["category"])
            existing = data["entries"].get(entry_id)
            # An identical retry returns the original row, never duplicates it.
            if existing and existing["revision"] == payload["revision"] + 1 and all(existing[key] == value for key, value in row.items()):
                return {"entry": existing, "replayed": True}
            if (existing is None and payload["revision"] != 0) or (existing is not None and existing["revision"] != payload["revision"]):
                raise LedgerConflict("这笔记录已被修改或删除，请刷新账本后重新编辑。")
            if row["category"] not in known:
                if len(data["custom_categories"][kind]) >= 100:
                    raise ValueError("该收支类型最多保存 100 个自定义类别，请选择已有类别。")
                data["custom_categories"][kind].append(row["category"])
            row["revision"] = payload["revision"] + 1
            data["entries"][entry_id] = row
            atomic_write_json(self.file, data)
            return {"entry": row, "replayed": False}

    def delete(self, payload):
        if set(payload) != {"id", "revision"} or not isinstance(payload["id"], str) or type(payload["revision"]) is not int:
            raise ValueError("删除参数无效。")
        with self.lock:
            data = self.read()
            existing = data["entries"].get(payload["id"])
            if not existing or existing["revision"] != payload["revision"]:
                raise LedgerConflict("这笔记录已被修改或删除，请刷新账本。")
            del data["entries"][payload["id"]]
            atomic_write_json(self.file, data)
            return {"deleted": True}
