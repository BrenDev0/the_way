# Architecture

How the backend is laid out, the rules that keep it that way, and where new code goes.
The rules are checked by `tests/unit/test_architecture.py`; if a change breaks one, that
test names the file and line.

The style is **vertical slices** (one folder per feature) with **ports and adapters**
inside each slice, and a small `core` of infrastructure the slices share.

## Layout

```
src/
  <feature>/                one slice: users, projects, conversations, skills, ...
    domain.py               the plain types of the feature (dataclasses, enums)
    ports.py                what the feature needs from outside: callables / protocols
    use_cases.py            the rules, written against ports   (a package when it grows)
    service.py, config.py,  small helpers of the slice
    cache.py, keys.py ...
    sqlalchemy/             ADAPTER: models.py, mapper.py (row <-> domain), adapter.py
    fastapi/                HTTP: routes.py, schemas.py, dependencies.py
  core/                     infrastructure shared by slices, one folder per capability
    cache/        ports.py + redis/adapter.py
    bucket/       ports.py + boto3/adapter.py
    cryptography/ ports.py + bcrypt/ and fernet/
    communications/  Email, the EmailSender port, smtp/adapter.py
    events/, llm/, tools/, tasks/, mcp/, agents/
    database/sqlalchemy/    Base and mixins, the engine and session factory
    settings.py, exceptions.py
  fastapi/                  the HTTP APP: main.py, middleware, exception handlers,
                            dependencies.py (app services + get_db_session), schemas.py
                            (ApiBaseModel), signing, rate limiting, v1/ and desktop/ routers
  emails/                   the look every email shares (logo, layout)
  assistants/               builds the tool catalog from the slices; ToolContext
  worker/, render/, render_client/    other entry points / services
```

Two things are easy to confuse:

* `src/fastapi/` is the **app** (it owns the process: builds it, mounts the routers).
  A feature's `fastapi/` folder is that feature's **HTTP adapter**.
* `core/<capability>/<tech>/` is shared infrastructure behind a port. A feature's
  `sqlalchemy/` folder is the adapter for **that feature's** ports.

## The rules

Each one is a test.

1. **`core` depends on no feature** and not on the app.
2. **`core` knows no web framework** (no FastAPI, no Starlette).
3. **Inside `core`, only `core/database` touches SQLAlchemy.**
4. **A `sqlalchemy/` adapter knows nothing of HTTP.**
5. **`domain`, `ports`, `use_cases` and `service` import neither FastAPI nor SQLAlchemy.**
   They take ports (functions) as arguments; they never reach for a session.
6. **`fastapi/` code reaches the database only through ports.** Wiring an adapter to a
   port happens in the feature's `fastapi/dependencies.py`, and nowhere else in `fastapi/`.

The direction is always inward: `fastapi/` and `sqlalchemy/` depend on `domain`, `ports` and
`use_cases`; those depend on nothing outside the slice except `core` ports and other
slices' `domain` / `ports`.

## Where does X go?

| I am adding...                              | It goes in                                                        |
|---------------------------------------------|-------------------------------------------------------------------|
| a new kind of thing the app stores          | `<feature>/domain.py`, `ports.py`, `sqlalchemy/models.py`, `mapper.py`, `adapter.py` |
| a business rule                             | `<feature>/use_cases.py` (taking ports as arguments)              |
| an HTTP endpoint                            | `<feature>/fastapi/routes.py`, its bodies in `fastapi/schemas.py` |
| turning a domain object into a JSON answer  | `XResponse.from_domain(...)` in `fastapi/schemas.py`              |
| wiring a port to its database function      | `<feature>/fastapi/dependencies.py` (`provide_..._fn`)            |
| a new external service (a mail API, a CRM)  | a port in `core/<capability>/ports.py` + `core/<capability>/<tech>/adapter.py` |
| a setting                                   | `core/settings.py` (see "Known debt")                             |
| a rule shared by every request              | `src/fastapi/` (middleware, dependencies)                         |
| an email                                    | `<feature>/emails.py` + `<feature>/email_templates/`, using `src/emails/layout.py` |
| a tool the assistant can call               | `<feature>/tools.py`, listed in `src/assistants/catalog.py`; it takes what it needs from `ToolContext` (`context.files`, `context.ports`) -- add a port to `ToolPorts` and bind it in `assistants/sql.py` |
| a command-line report                       | beside the slice it reports on, run as `python -m src.<feature>.<name>` |

### A new feature, step by step

1. `src/<feature>/domain.py`: the types.
2. `ports.py`: one `Callable` alias per thing the feature needs (`GetXFn = Callable[[UUID], Awaitable[X | None]]`).
3. `use_cases.py`: the rules, each function taking the ports it needs. Test them with plain
   fakes in `tests/unit/<feature>/` -- no database.
4. `sqlalchemy/`: `models.py` (add its `import` to `migrations/env.py` and
   `tests/integration/conftest.py`), `mapper.py`, `adapter.py`; add an Alembic migration.
5. `fastapi/dependencies.py`: a `provide_..._fn(session)` for each port.
6. `fastapi/schemas.py`, `fastapi/routes.py`: thin -- parse, call a use case, shape the answer.
7. Mount the router in `src/fastapi/v1/routes.py` (and `desktop/routes.py` if the desktop
   app needs it).

## Conventions

* **Use cases take ports, not sessions.** `get_overview(..., list_project_storage_fn=...)`,
  not `get_overview(session)`. That is what makes them testable without a database.
* **A port is a `Callable` alias** (or a `Protocol` when it has keyword arguments); the
  provider returns a closure over the request's session.
* **Routes are thin.** If a route does arithmetic or branches on data, it is a use case.
* **Cross-slice reads** (the organization overview) are a read model: a port plus an
  adapter function that returns domain objects, kept in its own file
  (`organizations/sqlalchemy/reports.py`).
* **A response is built by `from_domain`** on its schema. When it needs something the
  domain does not hold (a decrypted email), the route passes it in.
* **One wire contract.** The conversation stream's payloads are deliberately the REST
  schemas (`conversations/events.py`); give the stream its own types only if they must differ.

## Where adapters are used directly

Rule 6 is about routes. Two kinds of code legitimately wire adapters themselves, because
there is no request to inject from:

* **Task and job entry points** -- `conversations/tasks.py`, `background/jobs.py`,
  `documents/tasks.py`, `projects/load_brands.py`: they open their own session and bind
  adapters to ports for a run. This is the worker's composition root.
* **Command-line tools** -- `skills/usage.py`.

The assistant's tools are *not* on that list. A run's `ToolContext` carries `files` (the
`ProjectFiles` file system over a `ProjectStore`) and `ports` (a `ToolPorts` of the same
function-ports the use cases take). `assistants/sql.py` binds them to a session once per
run -- `sql_tool_context(session, ...)` -- and a test binds them to fakes. A tool, and
`ProjectFiles`, never see a session; the architecture test enforces it.

## Known debt

* **One settings class** (`core/settings.py`) holds every slice's knobs. Some are shared
  (`INVITATION_ACCEPT_URL` is read by `downloads`, `PUBLIC_API_URL` by projects and HTML
  pages), so splitting it needs a decision about who owns what.
* **Large modules** are split by concern once they stop reading as one thing, as `auth`,
  `projects` and `conversations` are (`use_cases/` and `fastapi/routes/` packages). The
  biggest left are `projects/files.py` (the `ProjectFiles` facade -- now unit-tested over a
  fake store, so it is safe to split), `render/checks.py` and the `cx_dashboard` insights and
  metrics modules.
* **Worker flows that take a session directly** (`background/approvals.py`,
  `documents/summaries.py`, `documents/training.py`, `conversations/relay.py`): they run
  inside a worker's own transaction rather than serving a tool or a request. They could take
  ports like everything else; nothing forces it yet.

## Checking a change

Unit tests need no services and include the architecture rules:

```
pytest tests/unit
```

The integration tests run against real Postgres, Redis and an S3-compatible bucket. They
drop the schema of the database they run against, so the suite refuses any database whose
name does not end in `_test`. Point it at a throwaway one -- never at real data.
