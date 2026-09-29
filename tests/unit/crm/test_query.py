import pytest

from src.crm import datasets, query

ROWS = [
    {"id": 1, "stage": "won", "value": 1200, "contact": {"email": "a@x.com"}, "date": "2026-07-02"},
    {"id": 2, "stage": "won", "value": 800, "contact": {"email": None}, "date": "2026-08-15"},
    {"id": 3, "stage": "lost", "value": 500, "contact": {}, "date": "2026-08-20"},
    {"id": 4, "stage": "open", "value": "n/a", "date": "2026-09-01"},
]


def f(field, op, value=None):
    return {"field": field, "op": op, "value": value}


def test_with_no_filter_every_row_counts():
    assert query.run(ROWS, []).startswith("4 of 4 rows match (no filter).")


def test_equality_ignores_case():
    assert query.run(ROWS, [f("stage", "eq", "WON")]).startswith("2 of 4")


def test_filters_are_anded_and_stated():
    result = query.run(ROWS, [f("stage", "eq", "won"), f("value", "gt", 1000)])

    assert result.startswith("1 of 4")
    assert "stage eq 'won' and value gt 1000" in result


def test_a_dotted_field_reaches_inside_an_object():
    assert query.run(ROWS, [f("contact.email", "exists")]).startswith("1 of 4")
    assert query.run(ROWS, [f("contact.email", "missing")]).startswith("3 of 4")


def test_iso_dates_compare_as_dates():
    assert query.run(ROWS, [f("date", "gte", "2026-08-01")]).startswith("3 of 4")


def test_a_breakdown_is_largest_first():
    result = query.run(ROWS, [], group_by="stage")

    lines = result.splitlines()
    assert lines[1] == "By stage:"
    assert lines[2] == "  won: 2"


def test_a_total_skips_values_that_are_not_numbers():
    result = query.run(ROWS, [], sum_field="value")

    assert "value totals 2,500.00 across 3 rows" in result


def test_a_breakdown_can_carry_totals():
    result = query.run(ROWS, [], group_by="stage", sum_field="value")

    assert "won: 2  (value total 2,000.00)" in result


def test_a_missing_group_value_is_its_own_bucket():
    assert "(none): 3" in query.run(ROWS, [], group_by="contact.email")


MANIFEST = {
    "name": "contacts",
    "folder": "contacts-20260929",
    "rows": 20,
    "reported_total": 1842,
    "field_count": 1,
    "bytes": 100,
    "fetched_at": "2026-09-29T10:00:00+00:00",
    "operation_id": "search-contacts-advanced",
    "pagination": "searchAfter",
    "pages": 1,
    "complete": False,
    "stopped_because": "max_rows (20) was reached",
    "profile": [],
}


def test_a_partial_fetch_says_so_in_capitals():
    report = datasets.report(MANIFEST)

    assert "20 rows of 1,842 reported by CX" in report
    assert "Complete: NO" in report
    assert "dataset='contacts-20260929'" in report


def test_a_complete_fetch_says_so():
    assert "Complete: yes" in datasets.report({**MANIFEST, "rows": 1842, "complete": True})


@pytest.mark.parametrize(
    ("rows", "total", "max_rows", "strategy", "complete"),
    [
        (100, 100, 5000, object(), True),
        (20, 100, 5000, object(), False),
        (20, None, 5000, object(), True),
        (20, None, 5000, None, False),
        (5000, None, 5000, object(), False),
    ],
)
def test_completeness_is_checked_not_assumed(rows, total, max_rows, strategy, complete):
    assert datasets._complete(rows, total, max_rows, strategy) is complete
