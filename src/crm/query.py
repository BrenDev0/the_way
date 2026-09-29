"""Exact answers over a fetched dataset.

The profile describes a dataset's shape; this answers questions about it -- how many
rows match, how they break down, what they total. Each result states the filters it
applied, so a figure can always be shown beside the question that produced it.
"""

from collections import Counter
from collections.abc import Sequence
from typing import Any

from . import config

MISSING = object()


def lookup(row: dict, field: str) -> Any:
    """A dotted field path into a row, or MISSING when any step is absent."""
    value: Any = row
    for part in field.split("."):
        if not isinstance(value, dict) or part not in value:
            return MISSING
        value = value[part]
    return value


def matches(row: dict, field: str, op: str, expected: Any) -> bool:
    value = lookup(row, field)

    if op == "exists":
        return value is not MISSING and value not in (None, "", [], {})
    if op == "missing":
        return value is MISSING or value in (None, "", [], {})
    if value is MISSING or value is None:
        return op == "ne"

    if op == "eq":
        return _same(value, expected)
    if op == "ne":
        return not _same(value, expected)
    if op == "contains":
        if isinstance(value, list):
            return any(_same(item, expected) for item in value)
        return str(expected).lower() in str(value).lower()

    try:
        left, right = _comparable(value, expected)
    except (TypeError, ValueError):
        return False
    return {
        "gt": left > right,
        "gte": left >= right,
        "lt": left < right,
        "lte": left <= right,
    }.get(op, False)


def _same(value: Any, expected: Any) -> bool:
    if isinstance(value, str) and isinstance(expected, str):
        return value.lower() == expected.lower()
    return value == expected


def _comparable(value: Any, expected: Any) -> tuple[Any, Any]:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value, float(expected)
    return str(value), str(expected)


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is MISSING or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def run(
    rows: Sequence[dict],
    filters: Sequence[dict],
    group_by: str | None = None,
    sum_field: str | None = None,
) -> str:
    kept = [
        row
        for row in rows
        if all(matches(row, f["field"], f["op"], f.get("value")) for f in filters)
    ]

    applied = (
        " and ".join(f"{f['field']} {f['op']} {f.get('value')!r}" for f in filters)
        or "no filter"
    )
    lines = [f"{len(kept):,} of {len(rows):,} rows match ({applied})."]

    if sum_field and not group_by:
        total, counted = _total(kept, sum_field)
        lines.append(f"{sum_field} totals {total:,.2f} across {counted:,} rows that carry a number.")

    if group_by:
        groups: Counter = Counter()
        totals: dict[str, float] = {}
        for row in kept:
            value = lookup(row, group_by)
            key = "(none)" if value in (MISSING, None, "") else str(value)
            groups[key] += 1
            if sum_field:
                amount = _number(lookup(row, sum_field))
                if amount is not None:
                    totals[key] = totals.get(key, 0.0) + amount

        lines.append(f"By {group_by}:")
        for key, count in groups.most_common(config.MAX_QUERY_GROUPS):
            line = f"  {key}: {count:,}"
            if sum_field:
                line += f"  ({sum_field} total {totals.get(key, 0.0):,.2f})"
            lines.append(line)
        if len(groups) > config.MAX_QUERY_GROUPS:
            lines.append(f"  ... {len(groups) - config.MAX_QUERY_GROUPS} smaller groups not shown")

    return "\n".join(lines)


def _total(rows: Sequence[dict], field: str) -> tuple[float, int]:
    amounts = [n for n in (_number(lookup(row, field)) for row in rows) if n is not None]
    return sum(amounts), len(amounts)
