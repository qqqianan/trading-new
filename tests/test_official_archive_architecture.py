import ast
from pathlib import Path

PROJECT_ROOT = Path(__file__).parents[1]
DATA_ROOT = PROJECT_ROOT / "src" / "ashare_lab" / "data"


def test_cninfo_endpoint_urls_have_one_client_owner() -> None:
    # Given: official CNInfo endpoint fragments and their sole adapter owner.
    owner = DATA_ROOT / "cninfo_client.py"
    protected = (
        "cninfo.com.cn/new/information/topSearch/query",
        "cninfo.com.cn/new/hisAnnouncement/query",
        "static.cninfo.com.cn",
    )
    violations: list[str] = []

    # When: production source is inspected for direct endpoint access.
    for path in DATA_ROOT.glob("*.py"):
        if path == owner:
            continue
        content = path.read_text(encoding="utf-8")
        if any(endpoint in content for endpoint in protected):
            violations.append(path.name)

    # Then: future CLI and batch code must reuse the paced client.
    assert violations == []


def test_official_archive_audits_cannot_import_database_or_research_layers() -> None:
    # Given: source-only official archive modules and forbidden persistence layers.
    paths = tuple(DATA_ROOT.glob("*industry_archiv*.py")) + tuple(DATA_ROOT.glob("cninfo_*.py"))
    forbidden = ("pymongo", "ashare_lab.research", "ashare_lab.services")
    violations: list[str] = []

    # When: imports are parsed from every source-audit module.
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            module = _imported_module(node)
            if module is not None and module.startswith(forbidden):
                violations.append(f"{path.name}:{node.lineno}:{module}")

    # Then: audits cannot persist or enter research orchestration.
    assert violations == []


def _imported_module(node: ast.AST) -> str | None:
    match node:
        case ast.ImportFrom(module=module) if module is not None:
            return module
        case ast.Import(names=names) if names:
            return names[0].name
        case _:
            return None
