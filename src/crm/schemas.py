from typing import Any, Literal

from pydantic import BaseModel, Field


class SearchCXOperations(BaseModel):
    """Find a CX operation by describing what you want to do in plain language.

    The server does not publish a catalog of operations -- it indexes the whole CX public
    API and answers queries against it, so this is the ONLY way to discover what is
    available. Always start here. Never guess an operationId; a guessed one simply is not
    found, and the error tells you nothing about what the real one is.

    Each result carries the operationId, method and path, requiredScopes, whether it takes
    a request body, and whether it is a read, a write, a delete, or moves money."""

    query: str = Field(
        description="What you are trying to do, in plain language -- 'find a contact by "
        "email', 'create a conversation AI agent', 'list pipelines'"
    )
    domains: list[str] | None = Field(
        default=None,
        description="Optional domains to constrain the search, for example ['contacts'] or "
        "['conversations']. Leave unset unless a first search returned results from the "
        "wrong area.",
    )
    kind: Literal["read", "write", "delete", "money_movement"] | None = Field(
        default=None,
        description="Optional filter. Use 'read' when you only need to look something up -- "
        "it keeps write and money-moving operations out of the results entirely.",
    )
    limit: int | None = Field(
        default=None, ge=1, le=50, description="Maximum results (1-50). Defaults to the server's own limit."
    )


class DescribeCXOperation(BaseModel):
    """Get the exact request contract for one operationId returned by SearchCXOperations.

    Returns the path and query parameters, the request body fields, a sanitised example
    payload, the required scopes, and safety metadata. Call this before ExecuteCXOperation
    whenever the operation takes a request body or its parameters are not obvious -- the
    field names cannot be guessed from the operation name."""

    operation_id: str = Field(
        description="Exact operationId from a SearchCXOperations result, for example 'update-association'"
    )


class ExecuteCXOperation(BaseModel):
    """Run a CX operation and return the API response.

    The server applies authorisation, the API version, scope and permission checks, and
    tenant isolation itself -- you supply only the operation and its parameters.

    This acts on the user's live CRM. For anything that creates, changes, deletes, or moves
    money, run it once with dry_run=True first, check the preview, and only then run it for
    real. Never send a write whose body you have not confirmed with DescribeCXOperation."""

    operation_id: str = Field(description="Exact operationId from a SearchCXOperations result")
    params: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Parameters for the operation. Either grouped -- "
            '{"path": {...}, "query": {...}, "body": {...}} -- or flat, in which case the '
            "server maps known field names to the right place. Take the names from "
            "DescribeCXOperation rather than guessing them."
        ),
    )
    dry_run: bool = Field(
        default=False,
        description="Preview the request and the parameters you supplied without actually "
        "running it upstream. Use this before every write, delete, or money-moving operation.",
    )
    reason: str = Field(
        default="",
        description="Short user-facing reason for the operation, shown in CX's audit trail. "
        "Give one for any write.",
    )
    idempotency_key: str | None = Field(
        default=None,
        description="Optional key that makes a retried write apply once rather than twice. "
        "Supply a stable value when retrying a write that may already have gone through.",
    )


class FetchCXDataset(BaseModel):
    """Pull every page of a CX READ operation into the workspace, and get back a
    description of the data rather than the data itself.

    USE THIS FOR ANY QUESTION ABOUT MORE THAN A HANDFUL OF RECORDS -- counts, totals,
    breakdowns, trends, "how many", "what share of", anything per-month or per-stage.
    ExecuteCXOperation returns one page, usually 20 rows out of thousands, straight into
    your context. Answering a counting question from that has two failure modes and both
    produce a confident wrong number: you are working from a fraction of the records, and
    you are adding up values by reading them rather than by counting them. This tool
    removes both. It pages to the end, writes one JSON object per line, and hands you row
    counts, field names, null rates and value ranges that were computed over the file.

    Keep using ExecuteCXOperation for single records ("what is this contact's email"),
    for anything that writes, and for reads where you genuinely only want the newest few.

    What comes back is a manifest: where the rows are, the row count against the total CX
    reported, whether the fetch is complete, and a per-field profile. The rows never enter
    your context: read the profile to decide what to ask, then answer with QueryCXDataset.
    If the manifest says Complete: NO, the file is a partial pull -- say so in whatever you
    report and never describe it as the full set.

    Fetches are cached per day, so asking a second question about the same dataset costs
    no API calls. Pass refresh=True when you need it re-pulled."""

    name: str = Field(
        description=(
            "Short name for this dataset, used as the folder name -- 'contacts', "
            "'won-opportunities-q3', 'conversations'. Reuse the same name for the same "
            "query to hit the day's cache; use a different one for a different query."
        )
    )
    operation_id: str = Field(
        description=(
            "Exact operationId from a SearchCXOperations result, and it must be a read. "
            "Prefer the search/list form of an operation -- 'search-contacts-advanced' "
            "rather than 'get-contact'. Search with kind='read' to find it."
        )
    )
    params: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Filters and sort for the operation, in the same grouped shape "
            'ExecuteCXOperation takes: {"query": {...}} or {"body": {...}}. Take the field '
            "names from DescribeCXOperation. Do NOT set page size, page number, or any "
            "cursor (limit, pageLimit, page, searchAfter, startAfter, startAfterDate) -- "
            "paging is handled for you and a value here will fight it. locationId is filled "
            "in automatically where the operation needs one."
        ),
    )
    max_rows: int = Field(
        default=5000,
        ge=1,
        le=50000,
        description=(
            "Safety ceiling on the fetch. Raise it when CX reports a total above it -- the "
            "manifest will say the fetch is incomplete if this is what stopped it."
        ),
    )
    fields: list[str] | None = Field(
        default=None,
        description=(
            "Top-level fields to keep, dropping the rest. Leave unset to keep everything, "
            "which is usually right -- a field you did not keep is a question you cannot "
            "ask later without re-fetching."
        ),
    )
    pagination: Literal["auto", "searchAfter", "startAfterDate", "startAfter", "page"] = Field(
        default="auto",
        description=(
            "Leave on 'auto'. It reads the operation's own contract to work out how the "
            "endpoint pages. Only override if a fetch came back incomplete because no "
            "strategy was recognised."
        ),
    )
    refresh: bool = Field(
        default=False,
        description=(
            "Re-fetch from CX even if today's cached copy exists. Use it when the user has "
            "just changed something in the CRM and expects to see it."
        ),
    )


class DatasetFilter(BaseModel):
    field: str = Field(description="Field name, dotted to reach inside an object: 'contact.email'")
    op: Literal["eq", "ne", "contains", "gt", "gte", "lt", "lte", "exists", "missing"] = Field(
        description="How to compare. Dates are ISO strings, so gt/lt work on them too."
    )
    value: Any = Field(default=None, description="What to compare against; unused by exists/missing")


class QueryCXDataset(BaseModel):
    """Count, total or break down the rows of a dataset FetchCXDataset wrote -- exactly,
    over every row, never by reading them.

    Every figure you report about CX data should come from this or from a FetchCXDataset
    manifest. Filters are ANDed. With group_by you get one line per value, largest first;
    with sum_field each count carries a total of that numeric field."""

    dataset: str = Field(
        description="The dataset's folder name as the manifest printed it, for example "
        "'contacts-20260929'"
    )
    filters: list[DatasetFilter] = Field(default_factory=list)
    group_by: str | None = Field(default=None, description="Field to break the count down by")
    sum_field: str | None = Field(default=None, description="Numeric field to total")
