"""Minimal server-side Qwen client for DashScope's OpenAI-compatible API."""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request


SYSTEM_PROMPT = """你是衡智助手的自然语言理解与规划器。只输出一个 JSON 对象，不要 Markdown，不要解释。
JSON 必须包含 intent、answer、tool_calls 三个字段。intent 只能是 bill_analysis、wealth_operation、card_management、cross_scene、clarification。
tool_calls 是 1 到 5 个对象，每个对象包含 name 和 arguments。只能使用这些只读或预览工具：
get_bill_report(period)，get_card_status(card_id)，get_card_summary(period)，preview_temporary_lock(card_id)，compare_products(days, accept_loss)，
preview_simulated_purchase(code, amount_cents, need_date, accept_loss)，query_order(order_id)。
绝不能返回 approve、confirm、save、trade、reset 或任何写入工具。执行写入必须由服务端独立确认。
不要编造金额、账单、卡片或订单事实；需要事实时调用对应工具。自然语言涉及陌生扣款和锁卡时，依次调用账单、卡片状态、临时锁卡预览。
理财模拟申购必须使用 amount_cents、need_date、accept_loss，并且只生成预览。answer 要简短说明计划和需要用户确认的动作。"""


class LLMClientError(ValueError):
    """Safe, user-facing error raised by the provider adapter."""


def _json_from_content(content):
    if isinstance(content, list):
        content = "".join(
            part.get("text", "") for part in content if isinstance(part, dict)
        )
    if not isinstance(content, str):
        raise LLMClientError("Qwen 返回内容不是文本。")
    text = content.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S | re.I)
    if fenced:
        text = fenced.group(1)
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise LLMClientError("Qwen 未返回有效 JSON 规划。") from exc
    if not isinstance(value, dict):
        raise LLMClientError("Qwen 规划必须是 JSON 对象。")
    return value


class LLMClient:
    def __init__(self, api_key=None, base_url=None, model=None, timeout=None):
        self.api_key = api_key if api_key is not None else os.getenv("DASHSCOPE_API_KEY", "").strip()
        self.base_url = (base_url or os.getenv(
            "QWEN_BASE_URL",
            "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        )).rstrip("/")
        self.model = model or os.getenv("QWEN_MODEL", "qwen-plus")
        self.timeout = float(timeout if timeout is not None else os.getenv("QWEN_TIMEOUT_SECONDS", "30"))

    def complete(self, message, context=None):
        if not self.api_key:
            raise LLMClientError("DASHSCOPE_API_KEY 未设置，请在服务端环境变量中配置。")
        if not isinstance(message, str) or not 1 <= len(message.strip()) <= 2000:
            raise LLMClientError("message 必须是 1—2000 字的文本。")
        context = context if isinstance(context, dict) else {}
        user_content = message.strip()
        if context:
            user_content += "\n\n仅作为上下文参考的 JSON：" + json.dumps(context, ensure_ascii=False, separators=(",", ":"))
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            "temperature": 0.1,
        }
        request = urllib.request.Request(
            self.base_url,
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            # Do not include response bodies: providers can echo request details.
            if exc.code in (401, 403):
                raise LLMClientError("Qwen API 鉴权失败，请检查 DASHSCOPE_API_KEY。") from exc
            raise LLMClientError(f"Qwen API 请求失败（HTTP {exc.code}）。") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise LLMClientError("Qwen API 暂时不可用或请求超时。") from exc
        try:
            data = json.loads(raw.decode("utf-8"))
            content = data["choices"][0]["message"]["content"]
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
            raise LLMClientError("Qwen API 返回格式异常。") from exc
        return _json_from_content(content), {"provider": "dashscope", "model": self.model}
