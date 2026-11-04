"""Keep repository navigation and native deployment boundaries coherent."""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_documentation_local_links_resolve():
    documents = [ROOT / "README.md", ROOT / "CONTRIBUTING.md", *(ROOT / "docs").rglob("*.md")]
    broken = []
    for document in documents:
        for target in re.findall(r"\]\(([^\s)]+)\)", document.read_text(encoding="utf-8")):
            if re.match(r"[A-Za-z]+:", target) or target.startswith("#"):
                continue
            if not (document.parent / target.split("#")[0]).exists():
                broken.append((document.relative_to(ROOT).as_posix(), target))
    assert not broken, broken


def test_migration_targets_exist_inside_repository():
    migration = json.loads((ROOT / "docs/architecture/path-migration.json").read_text())
    for old, new in migration["paths"].items():
        target = (ROOT / new).resolve()
        assert target.is_relative_to(ROOT) and target.is_file(), (old, new)
        assert not (ROOT / old).exists(), old


def test_native_quoted_includes_resolve_without_test_runtime_dependencies():
    for folder in (ROOT / "mql5", ROOT / "tests/native"):
        for source in folder.rglob("*"):
            if source.suffix not in {".mq5", ".mqh"}:
                continue
            for name in re.findall(r'#include "([^"]+)"', source.read_text(encoding="utf-8")):
                target = (source.parent / name).resolve()
                assert target.is_file(), (source, name)
                if source.is_relative_to(ROOT / "mql5"):
                    assert target.is_relative_to(ROOT / "mql5"), (source, name)
