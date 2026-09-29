from src.api_keys.domain import Provider
from src.core.tools.context import ToolContext
from src.core.tools.domain import Tool
from src.projects.files import ProjectFiles

from . import config, datasets, query
from .connection import CXConnection
from .schemas import (
    DatasetFilter,
    DescribeCXOperation,
    ExecuteCXOperation,
    FetchCXDataset,
    QueryCXDataset,
    SearchCXOperations,
)


def available(context: ToolContext) -> bool:
    credential = context.credentials.get(str(Provider.GOHIGHLEVEL))
    return bool(credential and credential.account_id)


def build(context: ToolContext) -> dict[str, Tool]:
    """The CX tools, or none when no CX key has been issued to this user -- a missing
    integration removes its own tools rather than failing on every call."""
    credential = context.credentials.get(str(Provider.GOHIGHLEVEL))
    if credential is None or not credential.account_id:
        return {}

    connection = CXConnection(token=credential.secret, location_id=credential.account_id)
    files = ProjectFiles(
        context.session, context.organization_id, context.user_id, context.bucket_store
    )

    async def search_cx_operations(query: str, domains=None, kind=None, limit=None) -> str:
        return await connection.search(query, domains, kind, limit)

    async def describe_cx_operation(operation_id: str) -> str:
        return await connection.describe(operation_id)

    async def execute_cx_operation(
        operation_id: str,
        params: dict | None = None,
        dry_run: bool = False,
        reason: str = "",
        idempotency_key: str | None = None,
    ) -> str:
        return await connection.execute(operation_id, params, dry_run, reason, idempotency_key)

    async def fetch_cx_dataset(
        name: str,
        operation_id: str,
        params: dict | None = None,
        max_rows: int = 5000,
        fields: list[str] | None = None,
        pagination: str = "auto",
        refresh: bool = False,
    ) -> str:
        return await datasets.fetch(
            connection, files, name, operation_id, params, max_rows, fields, pagination, refresh
        )

    async def query_cx_dataset(
        dataset: str,
        filters: list | None = None,
        group_by: str | None = None,
        sum_field: str | None = None,
    ) -> str:
        workspace = await files.workspace()
        folder = dataset.strip().strip("/").split("/")[-1]
        if folder in (config.ROWS_FILE, config.MANIFEST_FILE):
            folder = dataset.strip("/").split("/")[-2]

        rows = await files.read_json_lines(
            workspace, f"{datasets.folder_path(folder)}/{config.ROWS_FILE}"
        )
        conditions = [
            DatasetFilter.model_validate(f).model_dump() if not isinstance(f, dict) else f
            for f in filters or []
        ]
        return query.run(rows, conditions, group_by, sum_field)

    return {
        SearchCXOperations.__name__: Tool(schema=SearchCXOperations, handler=search_cx_operations),
        DescribeCXOperation.__name__: Tool(schema=DescribeCXOperation, handler=describe_cx_operation),
        ExecuteCXOperation.__name__: Tool(schema=ExecuteCXOperation, handler=execute_cx_operation),
        FetchCXDataset.__name__: Tool(schema=FetchCXDataset, handler=fetch_cx_dataset),
        QueryCXDataset.__name__: Tool(schema=QueryCXDataset, handler=query_cx_dataset),
    }
