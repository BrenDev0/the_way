"""What a dataset looks like, so nobody has to read it to find out.

The profile is the thing the model actually receives. It answers "what columns are there,
how full are they, and what range do they cover" -- the questions you would otherwise
answer by pulling rows into a context window, which is exactly what this whole layer
exists to avoid.

It deliberately stops short of answering questions *about* the data. No sums, no averages,
no group-bys: those are analysis, they belong in a query whose text can be shown next to
its result, and a summary statistic computed here would arrive with nothing to check it
against. Shape only.
"""

import re

# Above this a field is an identifier or free text, not a category, and listing its values
# tells the reader nothing they can use.
MAX_DISTINCT = 25
EXAMPLES = 3
TRUNCATE = 60

ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}")


def profile(rows: list[dict]) -> list[dict]:
    """One entry per top-level field, most-populated first."""
    if not rows:
        return []

    fields: dict[str, dict] = {}

    for row in rows:
        if not isinstance(row, dict):
            continue
        for key, value in row.items():
            entry = fields.setdefault(
                key,
                {
                    "field": key,
                    "present": 0,
                    "nulls": 0,
                    "empty": 0,
                    "types": set(),
                    "values": {},
                    "distinct_overflow": False,
                    "low": None,
                    "high": None,
                },
            )
            _observe(entry, value)

    profiles = [_finish(entry, len(rows)) for entry in fields.values()]
    profiles.sort(key=lambda p: (-p["present"], p["field"]))
    return profiles


def _observe(entry: dict, value) -> None:
    if value is None:
        entry["nulls"] += 1
        return

    entry["present"] += 1

    if isinstance(value, bool):
        entry["types"].add("bool")
        _track(entry, value)
        return

    if isinstance(value, (int, float)):
        entry["types"].add("number")
        _range(entry, value)
        return

    if isinstance(value, str):
        entry["types"].add("string")
        if not value:
            entry["empty"] += 1
            return
        if ISO_DATE.match(value):
            entry["types"].add("date")
            _range(entry, value)
        _track(entry, value)
        return

    if isinstance(value, list):
        entry["types"].add("array")
        if not value:
            entry["empty"] += 1
        return

    if isinstance(value, dict):
        entry["types"].add("object")
        if not value:
            entry["empty"] += 1
        return

    entry["types"].add(type(value).__name__)


def _range(entry: dict, value) -> None:
    """min/max, but only among values of one comparable kind -- a field holding both
    numbers and ISO strings would raise on the first comparison between them."""
    low, high = entry["low"], entry["high"]

    if low is None:
        entry["low"] = entry["high"] = value
        return

    if type(low) is not type(value) and not (
        isinstance(low, (int, float)) and isinstance(value, (int, float))
    ):
        return

    entry["low"] = min(low, value)
    entry["high"] = max(high, value)


def _track(entry: dict, value) -> None:
    values = entry["values"]
    key = value if isinstance(value, bool) else str(value)[:TRUNCATE]

    if key in values:
        values[key] += 1
    elif len(values) < MAX_DISTINCT:
        values[key] = 1
    else:
        # stop growing the map, but record that it stopped -- a distinct count that
        # silently caps out reads as a real cardinality, which would turn a free-text
        # field into a 25-value category
        entry["distinct_overflow"] = True


def _finish(entry: dict, total: int) -> dict:
    values = entry["values"]

    result = {
        "field": entry["field"],
        "present": entry["present"],
        # a field absent from a row and a field explicitly null are the same thing to
        # anyone about to query it
        "nulls": total - entry["present"],
        "types": sorted(entry["types"]),
    }

    if entry["empty"]:
        result["empty"] = entry["empty"]

    if entry["low"] is not None:
        result["min"] = entry["low"]
        result["max"] = entry["high"]

    if not values:
        return result

    result["distinct"] = (
        f">={MAX_DISTINCT}" if entry["distinct_overflow"] else len(values)
    )

    # A tally is only worth its width when the field is a CATEGORY -- when values repeat,
    # so the counts say something about the distribution. Two cases where they never do:
    #
    # - the field already has a range (a date or a number), where "2026-09-07T16:27:17=1,
    #   2026-08-28T22:05:35=1, ..." is the column reprinted one value at a time; and
    # - every value occurs exactly once, which means it is an id or free text.
    #
    # Both were costing ~130 tokens per field to say nothing: four timestamp columns and
    # two id columns made up over half of a 1,402-token profile of twenty rows. The range
    # or a couple of examples carries the same information in a tenth of the space.
    ranged = "min" in result
    unique = len(values) == entry["present"]

    if entry["distinct_overflow"] or unique:
        if not ranged:
            result["examples"] = list(values)[:EXAMPLES]
    elif not ranged:
        result["values"] = dict(sorted(values.items(), key=lambda kv: -kv[1]))

    return result


def table(profiles: list[dict]) -> str:
    """The profile as fixed-width text. Read by a model, so the column that matters
    (what is actually in the field) goes last where it can run long."""
    if not profiles:
        return "(no fields -- the dataset is empty)"

    # A field null in every row needs its name carried (so nobody queries it expecting
    # data) but not a row of zeroes and a blank content column. Named in one line instead.
    present = [p for p in profiles if p["present"]]
    empty = [p["field"] for p in profiles if not p["present"]]

    if not present:
        return f"every field was null in all rows: {', '.join(empty)}"

    width = min(max(len(p["field"]) for p in present), 34)
    lines = [f"{'field'.ljust(width)}  present   nulls  type            content"]

    for p in present:
        lines.append(
            f"{p['field'][:width].ljust(width)}  "
            f"{p['present']:>7}  {p['nulls']:>6}  "
            f"{'/'.join(p['types'])[:14].ljust(14)}  {_content(p)}"
        )

    if empty:
        lines.append(
            f"\nnull in all {profiles[0]['present'] + profiles[0]['nulls']} rows "
            f"({len(empty)} fields): {', '.join(empty)}"
        )

    return "\n".join(lines)


def _content(p: dict) -> str:
    if "values" in p:
        shown = ", ".join(f"{key}={count}" for key, count in list(p["values"].items())[:6])
        more = "" if p.get("distinct", 0) <= 6 else f", +{p['distinct'] - 6} more"
        return f"{shown}{more}"

    if "min" in p:
        return f"{p['min']} -> {p['max']}"

    if "examples" in p:
        return f"{p['distinct']} distinct, e.g. {', '.join(map(str, p['examples']))}"

    if p.get("empty"):
        return f"{p['empty']} empty"

    return ""
