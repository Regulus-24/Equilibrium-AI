"""Small deterministic simulated order state machine for the competition demo."""
from __future__ import annotations

import hashlib
import json
import threading
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

from vendor.io_utils import atomic_write_json


class OrderConflict(ValueError):
    pass


def _now():
    return datetime.now(timezone.utc).isoformat()


class OrderBook:
    def __init__(self, root):
        self.path = Path(root) / "orders.json"
        self.lock = threading.RLock()
        if not self.path.exists():
            self.write({"version": 1, "orders": {}})

    def read(self):
        return json.loads(self.path.read_text(encoding="utf-8"))

    def write(self, value):
        atomic_write_json(self.path, value)

    def preview(self, payload):
        allowed = {"code", "amount_cents", "need_date", "accept_loss", "funding_check"}
        if not isinstance(payload, dict) or not set(payload) <= allowed or not {"code", "amount_cents", "need_date", "accept_loss"} <= set(payload):
            raise ValueError("申购预览参数不完整。")
        code = payload["code"]
        if not isinstance(code, str) or code not in {"000343", "000359", "000397", "000389", "000719"}:
            raise ValueError("当前仅支持首批五只货币基金的模拟订单。")
        if type(payload["amount_cents"]) is not int or payload["amount_cents"] <= 0:
            raise ValueError("模拟申购金额必须为正整数分。")
        try:
            need = date.fromisoformat(payload["need_date"])
        except (ValueError, TypeError):
            raise ValueError("用款日期无效。") from None
        if need < date.today():
            raise ValueError("用款日期不能早于今天。")
        if payload["accept_loss"] is not True:
            raise ValueError("未确认可承受本金损失，模拟订单已阻断。")
        funding_check = payload.get("funding_check")
        if funding_check is not None and funding_check.get("status") != "ready_for_comparison":
            raise ValueError("现金安全检查未通过：" + "；".join(funding_check.get("reasons", [])))
        order = {
            "id": "order-" + uuid.uuid4().hex[:12],
            "code": code,
            "amount_cents": payload["amount_cents"],
            "need_date": payload["need_date"],
            "status": "DRAFT",
            "history": [{"status": "DRAFT", "at": _now()}],
            "created_at": _now(),
            "note": "仅模拟订单，不连接银行或基金平台。",
        }
        if funding_check is not None:
            order["funding_check"] = funding_check
        order["preview_hash"] = hashlib.sha256(
            json.dumps(order, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()
        with self.lock:
            state = self.read()
            state["orders"][order["id"]] = order
            state["version"] += 1
            self.write(state)
        return order

    def confirm(self, payload):
        if set(payload) != {"order_id", "preview_hash", "confirm"} or payload["confirm"] is not True:
            raise ValueError("请明确确认具体模拟订单。")
        with self.lock:
            state = self.read()
            order = state["orders"].get(payload["order_id"])
            if not order or order["preview_hash"] != payload["preview_hash"]:
                raise OrderConflict("模拟订单预览已失效，请重新生成。")
            if order["status"] == "COMPLETED":
                return {"order": order, "replayed": True}
            if order["status"] != "DRAFT":
                raise OrderConflict("模拟订单当前状态不能确认。")
            order["status"] = "ACCEPTED"
            order["accepted_at"] = _now()
            order["history"].append({"status": "ACCEPTED", "at": order["accepted_at"]})
            state["version"] += 1
            self.write(state)
            # The demo settles immediately but keeps ACCEPTED distinct in the record.
            order["status"] = "COMPLETED"
            order["completed_at"] = _now()
            order["history"].append({"status": "COMPLETED", "at": order["completed_at"]})
            self.write(state)
            return {"order": order, "replayed": False}

    def query(self, order_id):
        with self.lock:
            order = self.read()["orders"].get(order_id)
        if not order:
            raise ValueError("未找到模拟订单。")
        return order

    def public(self):
        with self.lock:
            state = self.read()
            return {"version": state["version"], "orders": list(state["orders"].values())}
