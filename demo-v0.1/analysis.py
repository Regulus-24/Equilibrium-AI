"""Deterministic month-to-month analysis of recorded ledger entries."""
from calendar import monthrange
from datetime import date, timedelta


def month_key(day):
    return f"{day.year:04d}-{day.month:02d}"


def monthly_comparisons(entries, today):
    groups = {}
    for row in entries:
        if row["date"] <= today.isoformat():
            groups.setdefault(row["date"][:7], []).append(row)
    keys = set(groups) | {month_key(today)}
    # Include an empty following month so a missing current period is explicit.
    for key in list(keys):
        year, month = map(int, key.split("-"))
        if year == 9999 and month == 12:
            continue
        following = date(year + (month == 12), month % 12 + 1, 1)
        if following <= today:
            keys.add(month_key(following))
    result = {}
    for key in sorted(keys):
        year, month = map(int, key.split("-"))
        start = date(year, month, 1)
        month_end = date(year, month, monthrange(year, month)[1])
        end = min(month_end, today)
        previous_end = start - timedelta(days=1) if start > date.min else None
        previous_start = previous_end.replace(day=1) if previous_end else None
        previous_key = month_key(previous_end) if previous_end else None
        current = groups.get(key, [])
        previous = groups.get(previous_key, [])
        status = "ready" if current and previous else "missing_current" if not current else "missing_previous"
        report = {
            "current_start": start.isoformat(), "current_end": end.isoformat(),
            "previous_start": previous_start.isoformat() if previous_start else None,
            "previous_end": previous_end.isoformat() if previous_end else None,
            "previous_month": previous_key, "partial": end < month_end,
            "current_days": (end-start).days+1,
            "previous_days": previous_end.day if previous_end else 0,
            "current_count": len(current), "previous_count": len(previous),
            "status": status, "kinds": {},
        }
        for kind in ("expense", "income"):
            current_categories, previous_categories = {}, {}
            for rows, totals in ((current, current_categories), (previous, previous_categories)):
                for row in rows:
                    if row["kind"] == kind:
                        totals[row["category"]] = totals.get(row["category"], 0) + row["cents"]
            now, before = sum(current_categories.values()), sum(previous_categories.values())
            comparable = status == "ready"
            delta = now - before if comparable else None
            categories = []
            for category in sorted(set(current_categories) | set(previous_categories)):
                a, b = current_categories.get(category, 0), previous_categories.get(category, 0)
                categories.append({"category": category, "current": a, "previous": b,
                                   "delta": a-b if comparable else None})
            if comparable:
                categories.sort(key=lambda row: (-abs(row["delta"]), -row["delta"], row["category"]))
            # Hundredths of a percent, rounded using integer arithmetic.
            rate = ((abs(delta)*10000 + before//2)//before) * (-1 if delta < 0 else 1) if comparable and before else None
            report["kinds"][kind] = {
                "current": now, "previous": before, "delta": delta,
                "percent_basis_points": rate, "categories": categories,
                "increase": sum(max(row["delta"], 0) for row in categories) if comparable else None,
                "decrease": sum(max(-row["delta"], 0) for row in categories) if comparable else None,
            }
        result[key] = report
    return result
