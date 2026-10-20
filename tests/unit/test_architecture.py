"""The layering rules, checked on the code itself (docs/ARCHITECTURE.md explains them).

Each test reads every source file's imports and fails with the file and line of any import
that crosses a boundary. They need no services and take well under a second.
"""

import ast
import re
from collections.abc import Callable, Iterator
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src"

# Imports that are knowingly outside a rule: (file relative to src, module) -> why. An
# entry is debt; the reason says what would pay it off. Keep it empty if you can.
EXCEPTIONS: dict[tuple[str, str], str] = {}

FEATURE_FASTAPI = re.compile(r"^src\.[a-z_]+\.fastapi(\.|$)")
FEATURE_SQLALCHEMY = re.compile(r"^src\.[a-z_]+(\.[a-z_]+)*\.sqlalchemy(\.|$)")


def source_files() -> Iterator[Path]:
    for path in sorted(SRC.rglob("*.py")):
        if "__pycache__" not in path.parts:
            yield path


def parts_of(path: Path) -> tuple[str, ...]:
    return path.relative_to(SRC).parts


def imported_modules(path: Path) -> Iterator[tuple[str, int]]:
    """Every module a file imports, as an absolute dotted name, with its line. For
    `from a import b` both `a` and `a.b` are given, since `b` may be a module."""
    package = ["src", *parts_of(path)[:-1]]
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name, node.lineno
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                base = node.module or ""
            else:
                kept = package[: len(package) - (node.level - 1)]
                base = ".".join([*kept, *([node.module] if node.module else [])])
            yield base, node.lineno
            for alias in node.names:
                yield f"{base}.{alias.name}", node.lineno


def under(name: str, *roots: str) -> bool:
    return any(name == root or name.startswith(f"{root}.") for root in roots)


def web_framework(name: str) -> bool:
    return under(name, "fastapi", "starlette")


def violations(
    applies: Callable[[tuple[str, ...]], bool], forbidden: Callable[[str], bool]
) -> list[str]:
    """`file:line imports module` for each import `forbidden` rejects, in each file
    `applies` selects."""
    found = []
    for path in source_files():
        if not applies(parts_of(path)):
            continue
        relative = "/".join(parts_of(path))
        for name, line in imported_modules(path):
            if forbidden(name) and (relative, name) not in EXCEPTIONS:
                found.append(f"{relative}:{line} imports {name}")
    return sorted(set(found))


def is_inner(parts: tuple[str, ...]) -> bool:
    """A feature's domain, ports, use cases and service: what everything else depends on."""
    if parts[0] in {"core", "fastapi"} or len(parts) < 2:
        return False
    return parts[-1] in {"domain.py", "ports.py", "use_cases.py", "service.py"} or "use_cases" in parts[:-1]


def test_core_depends_on_no_feature():
    found = violations(
        applies=lambda parts: parts[0] == "core",
        forbidden=lambda name: under(name, "src") and not under(name, "src.core"),
    )

    assert found == [], "core must not import a feature or the app:\n" + "\n".join(found)


def test_core_is_free_of_the_web_framework():
    found = violations(applies=lambda parts: parts[0] == "core", forbidden=web_framework)

    assert found == [], "core must not import FastAPI or Starlette:\n" + "\n".join(found)


def test_only_core_database_touches_the_orm_inside_core():
    found = violations(
        applies=lambda parts: parts[0] == "core" and parts[1:2] != ("database",),
        forbidden=lambda name: under(name, "sqlalchemy"),
    )

    assert found == [], "outside core/database, core must not import SQLAlchemy:\n" + "\n".join(found)


def test_persistence_adapters_know_nothing_of_http():
    found = violations(
        applies=lambda parts: "sqlalchemy" in parts[:-1],
        forbidden=lambda name: web_framework(name)
        or under(name, "src.fastapi")
        or bool(FEATURE_FASTAPI.match(name)),
    )

    assert found == [], "a sqlalchemy/ adapter must not import the HTTP layer:\n" + "\n".join(found)


def test_the_inner_layers_know_neither_http_nor_the_database():
    found = violations(
        applies=is_inner,
        forbidden=lambda name: web_framework(name)
        or under(name, "sqlalchemy", "src.fastapi")
        or bool(FEATURE_FASTAPI.match(name))
        or bool(FEATURE_SQLALCHEMY.match(name)),
    )

    assert found == [], (
        "domain, ports, use cases and service must not import FastAPI or SQLAlchemy "
        "(they take ports):\n" + "\n".join(found)
    )


def test_routes_reach_the_database_only_through_ports():
    """A feature's fastapi/ code wires adapters to ports in dependencies.py and nowhere else."""
    found = violations(
        applies=lambda parts: "fastapi" in parts[1:-1] and parts[-1] != "dependencies.py",
        forbidden=lambda name: bool(FEATURE_SQLALCHEMY.match(name)),
    )

    assert found == [], (
        "outside dependencies.py, fastapi/ code must use ports, not a sqlalchemy adapter:\n"
        + "\n".join(found)
    )


def test_tools_and_the_project_file_system_use_ports_not_the_database():
    """The assistant's tools and ProjectFiles work through ports (ToolContext.ports and a
    ProjectStore); only assistants/sql.py and the workers bind them to a session."""

    def applies(parts):
        return (
            parts[-1] == "tools.py"
            or parts[-2:] == ("projects", "files.py")
            or parts[-2:] == ("assistants", "context.py")
            or parts[-2:] == ("assistants", "catalog.py")
        )

    found = violations(
        applies=applies,
        forbidden=lambda name: under(name, "sqlalchemy")
        or bool(FEATURE_SQLALCHEMY.match(name))
        or under(name, "src.core.database"),
    )

    assert found == [], (
        "tools and ProjectFiles must not import the database; take a port from "
        "ToolContext.ports or a ProjectStore:\n" + "\n".join(found)
    )
