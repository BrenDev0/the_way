"""Where GoHighLevel's pagination lives, kept out of the fetch loop.

GHL does not paginate one way, and the differences are not cosmetic:

- `search-contacts-advanced` is a POST. Page size is `pageLimit` in the *body* (max 100),
  and the next page is requested by echoing back the **last row's own `searchAfter`**
  array. The cursor is a property of the rows, not of the response envelope.
- `search-conversation` is a GET. Page size is `limit` in the *query string*, the cursor
  parameter is `startAfterDate`, and the rows carry its value under `sort` as a
  one-element array.
- Others offer only a `page` number, or nothing at all.

So there is no single "next page" to follow, and the field holding the cursor depends on
the operation. Both shapes above were confirmed against the live API -- three-row pages,
zero id overlap between page one and page two. The remaining shapes are inferred from the
operation contract rather than observed, which is why `detect` returns None on anything
it does not recognise: a wrong guess at a parameter name is silently ignored by GHL and
comes back looking like a complete one-page dataset, which is the one outcome worth
engineering against. None stops the fetch after one page and says so.
"""

import json
from dataclasses import dataclass

GROUPS = ("path", "query", "body")

# GHL's own ceiling on every list endpoint seen so far. Asking for more is not an error,
# it is silently clamped, which makes the "short page means last page" check lie.
MAX_PAGE_SIZE = 100


class GhlFetchError(Exception):
    """An upstream GHL or MCP failure, carrying the text the model should be shown."""


@dataclass(frozen=True)
class Paging:
    """How one operation walks its pages.

    The fetch loop drives entirely off these fields, so teaching it a new GHL shape means
    adding a `Paging` here rather than another branch in the loop.
    """

    kind: str
    # Alternative names for the page-size parameter, in preference order. GHL is not
    # consistent even within one paging style: `search-contacts-advanced` calls it
    # `pageLimit` and rejects `limit`, while `search-opportunities-advanced` -- same
    # searchAfter cursor, same POST body -- calls it `limit`. Whichever the contract
    # declares is the one sent.
    size_params: tuple[str, ...] = ()
    size_in: str = "query"
    cursor_in: str = "query"
    # (alternative row fields, request parameter). Read off the LAST row of a page, taking
    # the first field the rows actually carry. Contacts publish their cursor as
    # `searchAfter`; opportunities publish the identical [epoch, id] pair as `sort`.
    cursor_map: tuple[tuple[tuple[str, ...], str], ...] = ()
    # the row field is a one-element array whose contents are the cursor (`sort`: [epoch])
    unwrap_single: bool = False
    page_param: str | None = None
    verified: bool = False

    def describe(self) -> str:
        if self.page_param:
            return f"{self.kind} (increments '{self.page_param}')"
        pairs = ", ".join(f"row.{'|'.join(src)} -> {dst}" for src, dst in self.cursor_map)
        return f"{self.kind} ({pairs})"


SEARCH_AFTER = Paging(
    kind="searchAfter",
    size_params=("pageLimit", "limit"),
    size_in="body",
    cursor_in="body",
    cursor_map=((("searchAfter", "sort"), "searchAfter"),),
    verified=True,
)

START_AFTER_DATE = Paging(
    kind="startAfterDate",
    size_params=("limit",),
    cursor_map=((("sort",), "startAfterDate"),),
    unwrap_single=True,
    verified=True,
)

# Inferred from the operation contract, not observed -- the token this was built against
# lacks `opportunities.readonly`, so the row field holding the cursor is a reasonable
# reading of the docs rather than something seen on the wire. If `dateAdded` is not what
# the rows actually carry, `cursor_from` returns None, the fetch stops after one page and
# the manifest records it as incomplete. Wrong here costs a truncated dataset that
# announces itself, never a silent one.
START_AFTER_ID = Paging(
    kind="startAfter",
    size_params=("limit",),
    cursor_map=((("dateAdded",), "startAfter"), (("id",), "startAfterId")),
)

PAGE_NUMBER = Paging(kind="page", size_params=("limit",), page_param="page")

STRATEGIES = {
    p.kind: p for p in (SEARCH_AFTER, START_AFTER_DATE, START_AFTER_ID, PAGE_NUMBER)
}


def contract_of(text: str) -> dict:
    """The `operation` object out of a describe_operation response."""
    payload = _loads(text)
    operation = payload.get("operation")
    if not isinstance(operation, dict):
        raise GhlFetchError(
            f"describe_operation returned no operation contract: {text[:300]}"
        )
    return operation


def detect(operation: dict) -> Paging | None:
    """The paging strategy this operation supports, read off its own contract."""
    query = set(operation.get("parameterNames") or [])
    query |= {
        p["name"]
        for p in operation.get("parameters", [])
        if isinstance(p, dict) and p.get("name")
    }
    body = {
        f["name"]
        for f in operation.get("requestBodyFields", [])
        if isinstance(f, dict) and f.get("name")
    }

    if "searchAfter" in body:
        return SEARCH_AFTER
    if "startAfterDate" in query:
        return START_AFTER_DATE
    if "startAfter" in query and "startAfterId" in query:
        return START_AFTER_ID
    if "page" in query:
        return PAGE_NUMBER
    return None


def size_param_for(operation: dict, paging: Paging) -> tuple[str, str] | None:
    """(parameter, group) to put the page size in, or None if the operation declares none
    of the alternatives and the server's own default has to stand."""
    if paging.size_in == "body":
        names = {f.get("name") for f in operation.get("requestBodyFields", [])}
    else:
        names = set(operation.get("parameterNames") or [])

    for candidate in paging.size_params:
        if candidate in names:
            return candidate, paging.size_in

    return None


def normalize(params: dict, has_body: bool) -> dict:
    """Caller params in grouped {path, query, body} form.

    The MCP server will map a flat dict to the right places itself, and for the caller's
    own filters that is fine. It is not fine for pagination: a page size placed in the
    wrong group is dropped without complaint and the fetch quietly returns a single page.
    Grouping up front means the loop places the size and the cursor exactly, rather than
    hoping.
    """
    grouped = {group: dict(params.get(group) or {}) for group in GROUPS}
    loose = {k: v for k, v in (params or {}).items() if k not in GROUPS}

    if loose:
        grouped["body" if has_body else "query"].update(loose)

    return grouped


def place(params: dict, group: str, key: str, value) -> None:
    params.setdefault(group, {})[key] = value


def rows_from(data, prefer: str | None = None) -> tuple[list[dict], str | None]:
    """The row array out of a GHL response body, plus the key it came from.

    The key is returned so the caller can pass it back as `prefer` on the next page: the
    last page of a fetch is often empty, every candidate list is then empty too, and
    picking "the longest list" would silently change columns mid-dataset.
    """
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)], None

    if not isinstance(data, dict):
        return [], None

    if prefer is not None:
        found = data.get(prefer)
        return (found if isinstance(found, list) else []), prefer

    candidates = [
        (key, value)
        for key, value in data.items()
        if isinstance(value, list) and (not value or isinstance(value[0], dict))
    ]
    if not candidates:
        return [], None

    key, value = max(candidates, key=lambda item: len(item[1]))
    return value, key


def total_from(data) -> int | None:
    if isinstance(data, dict):
        for key in ("total", "totalCount", "count"):
            value = data.get(key)
            if isinstance(value, int):
                return value
    return None


def cursor_from(row: dict, paging: Paging) -> dict | None:
    """The next page's cursor parameters, taken off the last row of this page.

    Each parameter names several row fields it may live under, tried in order -- the same
    cursor is published as `searchAfter` by one endpoint and `sort` by another.
    """
    cursor = {}
    for row_fields, param in paging.cursor_map:
        value = next(
            (row[field] for field in row_fields if row.get(field) is not None), None
        )
        if value is None:
            return None
        if paging.unwrap_single and isinstance(value, list):
            if not value:
                return None
            value = value[0]
        cursor[param] = value

    return cursor or None


def payload(text: str) -> dict | list:
    """The GHL response body with the MCP envelope taken off.

    A failed operation raises rather than returning an empty page, so the fetch loop
    cannot mistake "the token lacks this scope" for "there is no more data".
    """
    envelope = _loads(text)

    if not envelope.get("success", True):
        detail = envelope.get("data") or envelope.get("error") or {}
        message = detail.get("message") if isinstance(detail, dict) else str(detail)
        status = envelope.get("status")

        if status == 401:
            raise GhlFetchError(
                f"CX refused the request with 401: {message}. The private integration "
                f"token's granted scopes do not cover "
                f"'{envelope.get('operationId', 'this operation')}'. This is a "
                f"permissions problem, not a query problem -- do not retry it with "
                f"different parameters, and tell the user which scope is missing."
            )

        raise GhlFetchError(
            f"CX returned {status} for "
            f"'{envelope.get('operationId', 'the operation')}': {message or text[:300]}"
        )

    body = envelope.get("data", envelope)
    return body if isinstance(body, (dict, list)) else {}


def _loads(text: str) -> dict:
    """Parse a tool result that is usually JSON and occasionally a prose error.

    `_call` in crm/connection.py prefixes upstream failures with "<tool> failed: " before the
    JSON body, so the first brace is found rather than assumed to be at position zero.
    """
    start = text.find("{")
    if start == -1:
        raise GhlFetchError(text.strip() or "empty response from the CX server")

    try:
        parsed = json.loads(text[start:])
    except json.JSONDecodeError as exc:
        raise GhlFetchError(
            f"could not parse the CX response as JSON ({exc}): {text[:300]}"
        ) from exc

    return parsed if isinstance(parsed, dict) else {"data": parsed}
