import ast
from pathlib import Path

PROJECT_ROOT = Path(__file__).parents[1]
SOURCE_ROOT = PROJECT_ROOT / "src" / "ashare_lab"
MAX_PRODUCTION_FILE_LINES = 250


def test_required_engineering_structure_exists() -> None:
    # Given: the repository root and target modular-monolith architecture.
    required_paths = (
        PROJECT_ROOT / "AGENTS.md",
        PROJECT_ROOT / "CONTRIBUTING.md",
        PROJECT_ROOT / "Makefile",
        PROJECT_ROOT / "docs" / "ENGINEERING_STANDARDS.md",
        PROJECT_ROOT / "docs" / "ML_SYSTEM_ARCHITECTURE.md",
        SOURCE_ROOT / "governance" / "__init__.py",
        SOURCE_ROOT / "ml" / "__init__.py",
        SOURCE_ROOT / "portfolio" / "__init__.py",
        SOURCE_ROOT / "research" / "datasets" / "__init__.py",
        SOURCE_ROOT / "research" / "features" / "__init__.py",
        SOURCE_ROOT / "research" / "labels" / "__init__.py",
        SOURCE_ROOT / "research" / "splits" / "__init__.py",
        SOURCE_ROOT / "research" / "experiments" / "__init__.py",
    )

    # When: the expected engineering skeleton is checked.
    missing = tuple(path.relative_to(PROJECT_ROOT) for path in required_paths if not path.exists())

    # Then: every architectural boundary and governing document exists.
    assert missing == ()


def test_domain_layer_does_not_import_outer_layers() -> None:
    # Given: domain modules and the outer-layer package names.
    forbidden = {
        "api",
        "backtest",
        "data",
        "governance",
        "ml",
        "portfolio",
        "research",
        "services",
        "strategies",
    }
    violations: list[str] = []

    # When: imports are parsed from the Python syntax tree.
    for path in (SOURCE_ROOT / "domain").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or node.module is None:
                continue
            parts = node.module.split(".")
            if len(parts) >= 2 and parts[0] == "ashare_lab" and parts[1] in forbidden:
                violations.append(f"{path.name}:{node.lineno} imports {node.module}")

    # Then: domain remains independent from orchestration and infrastructure.
    assert violations == []


def test_production_python_files_stay_within_size_boundary() -> None:
    # Given: every production Python module.
    oversized: list[str] = []

    # When: physical line counts are checked.
    for path in SOURCE_ROOT.rglob("*.py"):
        line_count = len(path.read_text(encoding="utf-8").splitlines())
        if line_count > MAX_PRODUCTION_FILE_LINES:
            oversized.append(f"{path.relative_to(PROJECT_ROOT)}: {line_count}")

    # Then: responsibilities remain small enough to review in one pass.
    assert oversized == []


def test_training_implementation_has_one_service_entrypoint() -> None:
    # Given: the internal Trainer capability and the approved orchestration module.
    allowed_importer = SOURCE_ROOT / "services" / "training.py"
    violations: list[str] = []

    # When: production imports of the internal training contract are inspected.
    for path in SOURCE_ROOT.rglob("*.py"):
        if path == allowed_importer or path == SOURCE_ROOT / "ml" / "contracts.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        violations.extend(
            f"{path.relative_to(PROJECT_ROOT)}:{node.lineno}"
            for node in ast.walk(tree)
            if (
                isinstance(node, ast.ImportFrom)
                and node.module == "ashare_lab.ml.contracts"
                and any(alias.name == "Trainer" for alias in node.names)
            )
        )

    # Then: generated code cannot create a second direct Trainer entrypoint.
    assert violations == []


def test_runtime_code_never_references_legacy_database() -> None:
    # Given: all production source files.
    # When: the quarantined legacy database name is searched in runtime code.
    violations = [
        str(path.relative_to(PROJECT_ROOT))
        for path in SOURCE_ROOT.rglob("*.py")
        if "tradingagentscn" in path.read_text(encoding="utf-8")
    ]

    # Then: no supported execution path can read the legacy database.
    assert violations == []
