"""Deterministic narrative layer built only from an insights report.

The module deliberately does not infer merchants, balances, motives, or risk
levels. It turns server-calculated facts and candidate records into a stable
contract that a future LLM can explain without becoming the source of truth.
"""
from __future__ import annotations


CONTRACT_VERSION = "bill-analysis-narrative-v1"


def _money(cents):
    if cents is None:
        return "资料不足"
    return f"¥{cents / 100:,.2f}".rstrip("0").rstrip(".")


def _trim(text, limit):
    text = str(text or "")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _ids(rows):
    return list(dict.fromkeys(row.get("id") for row in rows if row.get("id")))


def _insight(index, priority, kind, certainty, title, body, evidence, suggestion):
    return {
        "id": f"insight-{index}",
        "priority": priority,
        "type": kind,
        "certainty": certainty,
        "title": _trim(title, 80),
        "body": _trim(body, 240),
        "evidence_ids": list(dict.fromkeys(evidence)),
        "suggestion": _trim(suggestion, 160) if suggestion else None,
    }


def build_narrative(report):
    """Build a schema-shaped narrative from an existing deterministic report."""
    if not isinstance(report, dict) or not isinstance(report.get("facts"), dict):
        raise ValueError("账单事实报告无效。")
    facts = report["facts"]
    evidence = report.get("evidence", [])
    previous = report.get("previous_evidence", [])
    current_ids = _ids(evidence)
    previous_ids = _ids(previous)
    expense = facts.get("expense", 0)
    income = facts.get("income", 0)
    balance = facts.get("balance", 0)
    period = report.get("period", "当前期间")
    insights = []
    next_index = 1

    if current_ids:
        insights.append(_insight(next_index, 1, "fact", "fact", "本期收支概览",
            f"{period}已记录收入 {_money(income)}，支出 {_money(expense)}，记录结余 {_money(balance)}。结余不是银行余额。",
            current_ids, "如需判断真实可用现金，请单独确认当前现金和预留金额。"))
        next_index += 1
    else:
        insights.append(_insight(next_index, 1, "information_needed", "information_needed", "缺少本期账单记录",
            f"{period}没有已记录交易，当前只能说明账本没有记录，不能说明实际没有收支。",
            [], "导入或补充本期账单后再生成分析。"))
        next_index += 1

    comparison = report.get("comparison", {}).get("expense", {})
    delta = comparison.get("delta")
    if delta is not None and previous_ids:
        direction = "增加" if delta > 0 else "减少" if delta < 0 else "没有变化"
        insights.append(_insight(next_index, 2, "comparison", "fact", "与上一期间比较",
            f"支出较上一期间{direction} {_money(abs(delta))}；比较仅基于已记录数据，当前未结束期间不预测期末金额。",
            current_ids + previous_ids, "查看分类明细，确认变化来自哪些支出类别。"))
        next_index += 1
    elif report.get("partial"):
        insights.append(_insight(next_index, 2, "information_needed", "information_needed", "比较口径需要注意",
            "本期尚未结束，与上一完整期间的记录时长不同，当前比较不能代表整月或全年趋势。",
            current_ids + previous_ids, "待本期结束后再进行完整期间比较。"))
        next_index += 1

    top = (report.get("top_expenses") or [])[:1]
    if top:
        row = top[0]
        insights.append(_insight(next_index, 2, "large_expense_candidate", "candidate", "本期最大支出",
            f"最大一笔支出为 {_money(row.get('cents'))}，分类为{row.get('category') or '未分类'}，日期为{row.get('date') or '未知'}。",
            [row.get("id")] if row.get("id") else [], "确认这笔支出是否符合你的预期。"))
        next_index += 1

    for candidate in report.get("candidates", []):
        if len(insights) >= 6:
            break
        ids = list(dict.fromkeys(candidate.get("ids", []) + candidate.get("evidence", [])))
        if candidate.get("type") == "duplicate":
            title, body = "疑似重复记账", "发现日期、金额、分类和非空备注相同的记录；这只是重复候选，不代表欺诈。"
            kind = "duplicate_candidate"
        else:
            reason = candidate.get("reason", {})
            title = "金额偏离同类历史"
            body = f"这笔支出高于前90天同类历史阈值（历史 {reason.get('history_count', 0)} 笔），需要人工核查。"
            kind = "large_expense_candidate"
        insights.append(_insight(next_index, 1, kind, "candidate", title, body, ids, "打开对应记录，标记为正常或需要核查。"))
        next_index += 1

    recurring = (report.get("recurring_candidates") or [])[:1]
    if recurring and len(insights) < 6:
        item = recurring[0]
        reason = item.get("reason", {})
        insights.append(_insight(next_index, 3, "fact", "candidate", "可能的固定支出或订阅",
            f"{reason.get('merchant', '某项支出')}近120天出现 {reason.get('occurrences', 0)} 次；这是模式提示，需要人工确认。",
            item.get("ids", []), "确认是否为你主动订阅的服务。"))
        next_index += 1

    insufficient = report.get("insufficient_ids") or []
    if insufficient and len(insights) < 6:
        insights.append(_insight(next_index, 3, "information_needed", "information_needed", "部分记录缺少历史依据",
            f"有 {len(insufficient)} 笔支出没有足够的前90天同类历史，因此未进行金额偏离判断。",
            insufficient, "补充更早期间账单后再复核。"))

    summary = f"{period}已记录支出 {_money(expense)}，发现 {len(report.get('candidates', []))} 项待核查候选。"
    if not current_ids:
        summary = f"{period}暂无已记录交易，当前只能生成数据不足提示。"
    return {
        "contract_version": CONTRACT_VERSION,
        "source_ledger_version": str(report.get("version", "")),
        "summary": _trim(summary, 300),
        "insights": insights,
    }
