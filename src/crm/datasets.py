"""Page a CX read operation into the workspace and describe what landed.

The return value is a manifest -- row count, field profile, where the rows are -- and
never rows. That is the whole point: the rows exist where something can count them
exactly, instead of in a context window where they have to be counted by impression.
"""

import asyncio
import json
import re
from datetime import UTC, datetime

from src.core.exceptions import ApplicationError
from src.core.mcp.client import McpClient
from src.projects.domain import Project
from src.projects.files import ProjectFiles

from . import config
from . import paging as pg
from .connection import CXConnection
from .paging import GhlFetchError
from .profile import profile, table

INCOMPLETE = "INCOMPLETE"


def slug(text: str, limit: int = 40) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return cleaned[:limit].rstrip("-") or "dataset"


def today() -> str:
    return datetime.now(UTC).strftime("%Y%m%d")


def folder_path(folder: str) -> str:
    return f"{config.DATA_FOLDER}/{folder}"


async def fetch(
    connection: CXConnection,
    files: ProjectFiles,
    name: str,
    operation_id: str,
    params: dict | None = None,
    max_rows: int = 5000,
    fields: list[str] | None = None,
    pagination: str = "auto",
    refresh: bool = False,
) -> str:
    workspace = await files.workspace()
    folder = f"{slug(name)}-{today()}"
    request = {"operation_id": operation_id, "params": params or {}, "fields": fields}

    if not refresh:
        cached = await _cached(files, workspace, folder, request)
        if cached:
            return cached

    async with connection.session() as client:
        try:
            operation = pg.contract_of(await connection.describe(operation_id, client))
        except GhlFetchError as exc:
            return f"Could not fetch '{name}': {exc}"

        # Read-only by construction, checked against the server's own classification
        # rather than the operation's name. This loops without approval and runs inside
        # unattended background tasks, so it must not be reachable as a bulk write path.
        kind = operation.get("kind")
        if kind != "read":
            return (
                f"Refusing to fetch with '{operation_id}': the CX server classifies it as "
                f"'{kind}', not a read. This tool only ever reads. Use ExecuteCXOperation "
                f"for anything that writes, and search again with kind='read' if you were "
                f"looking for the list version of this operation."
            )

        if pagination != "auto":
            strategy = pg.STRATEGIES.get(pagination)
            if strategy is None:
                return (
                    f"Unknown pagination '{pagination}'. Valid values: auto, "
                    f"{', '.join(pg.STRATEGIES)}."
                )
        else:
            strategy = pg.detect(operation)

        try:
            rows, result = await _page(
                connection, client, operation, operation_id, params or {}, strategy, max_rows, fields
            )
        except GhlFetchError as exc:
            return f"{INCOMPLETE} -- fetching '{name}' failed: {exc}"

    body = "".join(json.dumps(row, default=str) + "\n" for row in rows).encode("utf-8")
    try:
        await files.write(
            workspace, f"{folder_path(folder)}/{config.ROWS_FILE}", body, overwrite=True
        )
    except ApplicationError as exc:
        return f"{INCOMPLETE} -- the rows could not be saved: {exc.message}"

    manifest = {
        "name": name,
        "folder": folder,
        **request,
        "fetched_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "pagination": strategy.describe() if strategy else "none",
        "bytes": len(body),
        **result,
    }
    await files.write(
        workspace,
        f"{folder_path(folder)}/{config.MANIFEST_FILE}",
        json.dumps(manifest, indent=2, default=str).encode("utf-8"),
        overwrite=True,
    )
    return report(manifest)


async def _page(
    connection: CXConnection,
    client: McpClient,
    operation: dict,
    operation_id: str,
    params: dict,
    strategy: pg.Paging | None,
    max_rows: int,
    fields: list[str] | None,
) -> tuple[list[dict], dict]:
    """The page loop. Returns every row it kept and what the manifest needs to state
    plainly whether the dataset is whole."""
    base = pg.normalize(params, bool(operation.get("hasRequestBody")))
    _inject_location(base, operation, connection.location_id)

    size_slot = pg.size_param_for(operation, strategy) if strategy else None
    written: list[dict] = []
    cursor: dict | None = None
    seen_cursors: set[str] = set()
    pages = 0
    reported_total: int | None = None
    row_key: str | None = None
    # The page size to measure a short final page against. Known up front only when the
    # operation takes a size parameter; otherwise learned from page one. Guessing it --
    # assuming 100 when GHL defaults to 20 -- makes the first page look short and ends the
    # fetch at 20 rows while reporting it as the complete set.
    expected: int | None = None
    stopped = ""

    while True:
        request = {group: dict(values) for group, values in base.items()}
        asked = min(pg.MAX_PAGE_SIZE, max_rows - len(written))

        if size_slot:
            slot, group = size_slot
            pg.place(request, group, slot, asked)
            expected = asked

        if cursor and strategy:
            for key, value in cursor.items():
                pg.place(request, strategy.cursor_in, key, value)

        if strategy and strategy.page_param:
            pg.place(request, "query", strategy.page_param, pages + 1)

        data = pg.payload(await connection.execute(operation_id, request, client=client))
        pages += 1

        rows, row_key = pg.rows_from(data, prefer=row_key)
        reported_total = pg.total_from(data) or reported_total

        if not rows:
            stopped = "a page came back empty, so there was no more data"
            break

        for row in rows[: max_rows - len(written)]:
            written.append({key: row.get(key) for key in fields} if fields else row)

        if expected is None:
            expected = len(rows)

        if len(written) >= max_rows:
            stopped = f"max_rows ({max_rows}) was reached"
            break
        if reported_total is not None and len(written) >= reported_total:
            stopped = "every row CX reported had been written"
            break
        if strategy is None:
            stopped = (
                "this operation exposes no pagination parameter the fetcher recognises, "
                "so only the first page was retrieved"
            )
            break
        if len(rows) < expected:
            stopped = "the last page was short, so there was no more data"
            break
        if pages >= config.MAX_PAGES:
            stopped = f"the page limit ({config.MAX_PAGES}) was reached"
            break

        if not strategy.page_param:
            cursor = pg.cursor_from(rows[-1], strategy)
            if cursor is None:
                carried = ", ".join(" or ".join(names) for names, _ in strategy.cursor_map)
                stopped = (
                    f"the last row carried no cursor -- '{strategy.kind}' paging reads it "
                    f"from row field(s) '{carried}', which this operation's rows do not "
                    f"contain, so paging stopped after {pages} page(s)"
                )
                break

            fingerprint = json.dumps(cursor, sort_keys=True, default=str)
            if fingerprint in seen_cursors:
                stopped = "the cursor stopped advancing, so paging was halted"
                break
            seen_cursors.add(fingerprint)

        await asyncio.sleep(config.PAGE_PAUSE_SECONDS)

    fields_profile = profile(written)
    return written, {
        "rows": len(written),
        "reported_total": reported_total,
        "pages": pages,
        "complete": _complete(len(written), reported_total, max_rows, strategy),
        "stopped_because": stopped,
        "row_key": row_key,
        "field_count": len(fields_profile),
        "profile": fields_profile,
    }


def _complete(rows: int, total: int | None, max_rows: int, strategy) -> bool:
    """Whether the rows are the whole result set. With a total from CX this is checked,
    not trusted; with none, a fetch that stopped on its own cap or had no paging strategy
    is called partial -- assuming otherwise is how a 20-row first page gets reported as a
    full quarter."""
    if total is not None:
        return rows >= total
    return strategy is not None and rows < max_rows


def _inject_location(params: dict, operation: dict, location_id: str) -> None:
    """Supply locationId where the operation declares one and the caller did not. Several
    operations answer 401 without it, which reads exactly like a missing scope."""
    if not location_id:
        return

    if any("locationId" in params.get(group, {}) for group in pg.GROUPS):
        return

    for parameter in operation.get("parameters", []):
        if isinstance(parameter, dict) and parameter.get("name") == "locationId":
            declared = parameter.get("in")
            group = declared if isinstance(declared, str) and declared in pg.GROUPS else "query"
            pg.place(params, group, "locationId", location_id)
            return

    if "locationId" in (operation.get("parameterNames") or []):
        pg.place(params, "query", "locationId", location_id)


async def manifests(files: ProjectFiles, workspace: Project, day: str | None = None) -> list[dict]:
    """Every dataset manifest in the workspace, optionally only those from one day."""
    try:
        data = await files.contents(workspace, config.DATA_FOLDER)
    except ApplicationError:
        return []

    found = []
    for folder in data.folders:
        if day and not folder.name.endswith(f"-{day}"):
            continue
        try:
            _, raw = await files.read_bytes(
                workspace, f"{folder_path(folder.name)}/{config.MANIFEST_FILE}"
            )
            found.append(json.loads(raw.decode("utf-8")))
        except (ApplicationError, json.JSONDecodeError, UnicodeDecodeError):
            continue
    return found


async def _cached(files: ProjectFiles, workspace: Project, folder: str, request: dict) -> str | None:
    """Today's dataset for this exact request, under any name.

    Matched on the request rather than the dataset name, because the name is only the
    caller's label -- keying on it meant a re-ask under a new label re-pulled identical
    rows. A different request under a name in use still re-fetches: two questions must
    never serve each other's rows.
    """
    for manifest in await manifests(files, workspace, today()):
        if not all(manifest.get(key) == value for key, value in request.items()):
            continue

        note = (
            f"Fetched {manifest['fetched_at']} and read from the workspace just now -- no "
            f"API calls were made. This IS the current data for that request; do not "
            f"re-fetch it under another name. If the CRM has genuinely changed since, call "
            f"this again with the SAME name and refresh=True."
        )
        if manifest.get("folder") != folder:
            note += (
                f"\nIt was fetched under the name '{manifest['name']}', so query it as "
                f"'{manifest.get('folder')}'."
            )
        return f"{report(manifest)}\n\n{note}"

    return None


def report(manifest: dict) -> str:
    total = manifest.get("reported_total")
    rows = manifest["rows"]

    headline = f"{rows:,} rows"
    if total is not None:
        headline += f" of {total:,} reported by CX"

    folder = manifest.get("folder", "")
    lines = [
        (
            f"Dataset '{manifest['name']}': {headline}, "
            f"{manifest['field_count']} fields, {manifest['bytes']:,} bytes."
        ),
        f"Query it: QueryCXDataset with dataset='{folder}'",
        f"Stored:   .the_way/{folder_path(folder)}/{config.ROWS_FILE}  (one JSON object per line)",
        f"As of:    {manifest['fetched_at']}  via {manifest['operation_id']}",
        f"Paging:   {manifest['pagination']} over {manifest['pages']} page(s)",
    ]

    if manifest["complete"]:
        lines.append("Complete: yes -- every row CX reported was written.")
    else:
        lines.append(
            f"Complete: NO. Paging stopped because {manifest['stopped_because']}. Any "
            f"figure from this dataset describes {rows:,} rows, not the whole set -- say so "
            f"in anything you report, and never present it as the full picture."
        )

    lines += ["", "Fields:", table(manifest.get("profile") or [])]

    if manifest.get("fields"):
        lines.append(
            f"\nOnly these fields were kept: {', '.join(manifest['fields'])}. Anything else "
            f"CX returned is not in the dataset."
        )

    return "\n".join(lines)

