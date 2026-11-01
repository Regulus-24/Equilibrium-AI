"""Provider adapters for product quotes.

Tencent Licaitong does not expose a public personal-portfolio API for this
prototype. The adapter is therefore opt-in and expects an authorized
organization endpoint supplied through environment variables. It never logs
tokens and never attempts to automate a consumer login.
"""
from __future__ import annotations

import json
import os
from urllib.parse import quote
from urllib.request import Request, urlopen


class ProviderError(ValueError):
    pass


class TencentLicaitongProvider:
    name = "tencent_licensed"

    def __init__(self, base_url=None, token=None, timeout=15):
        self.base_url = (base_url or os.getenv("TENCENT_LCT_API_BASE_URL", "")).rstrip("/")
        self.token = token if token is not None else os.getenv("TENCENT_LCT_API_TOKEN", "")
        self.timeout = timeout

    def status(self):
        return {
            "name": self.name,
            "configured": bool(self.base_url and self.token),
            "supported": bool(self.base_url and self.token),
            "message": "等待已授权的腾讯理财通机构接口；个人理财通登录、验证码和网页抓取不在支持范围内。"
            if not (self.base_url and self.token) else "已配置授权数据源，实际字段需按合作方契约校验。",
        }

    def fetch_history(self, code):
        if not self.base_url or not self.token:
            raise ProviderError("腾讯理财通适配器未配置授权 API；请设置 TENCENT_LCT_API_BASE_URL 和 TENCENT_LCT_API_TOKEN。")
        if not self.base_url.startswith("https://"):
            raise ProviderError("腾讯理财通数据源必须使用 HTTPS。")
        url = self.base_url + "/products/" + quote(code, safe="")
        req = Request(url, headers={"Authorization": "Bearer " + self.token, "Accept": "application/json"})
        try:
            with urlopen(req, timeout=self.timeout) as response:
                raw = response.read(2_000_001)
        except Exception as exc:
            raise ProviderError("腾讯理财通授权接口请求失败。") from exc
        if len(raw) > 2_000_000:
            raise ProviderError("腾讯理财通接口响应过大。")
        try:
            data = json.loads(raw.decode("utf-8"))
            rows = data.get("data", data) if isinstance(data, dict) else data
            if isinstance(rows, dict): rows = rows.get("quotes", rows.get("history"))
        except (UnicodeDecodeError, json.JSONDecodeError, AttributeError) as exc:
            raise ProviderError("腾讯理财通接口未返回 JSON。") from exc
        if not isinstance(rows, list) or not rows:
            raise ProviderError("腾讯理财通接口未返回收益历史。")
        normalized = []
        for row in rows:
            if not isinstance(row, dict) or not {"date", "per10k"} <= set(row):
                raise ProviderError("腾讯理财通收益字段不符合适配器契约。")
            normalized.append({"date": str(row["date"]), "per10k": str(row["per10k"]),
                               "annual7": None if row.get("annual7") is None else str(row["annual7"]), "nav": row.get("nav")})
        return normalized, raw.decode("utf-8")


def provider_statuses():
    return [
        {"name": "eastmoney_public", "configured": True, "supported": True,
         "message": "公开行情源，适合演示和无账号跟踪。"},
        TencentLicaitongProvider().status(),
    ]
