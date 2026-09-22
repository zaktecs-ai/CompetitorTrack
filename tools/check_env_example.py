#!/usr/bin/env python3
"""Verify that ``.env.example``'s ``[api]`` section and ``app/config.py`` agree.

A documented variable the code ignores is a lie; an environment variable the
code reads and nobody documented is an outage waiting for the next deploy. P1's
Definition of Done asks for a script that catches both directions, so this is it.

Run it from anywhere:

    python3 tools/check_env_example.py

Exits 0 when the two sides match, 1 with a printed diff when they do not. CI
runs it, and ``apps/api/tests/test_env_example_parity.py`` runs it again as a
unit test so a mismatch fails locally before it reaches CI.

Implementation notes. The script **parses** ``config.py`` with ``ast`` instead of
importing it: importing would require the api's dependencies and a valid
environment, and this must run on a bare interpreter. It also stays Python 3.9+
compatible, like everything else in ``tools/`` (D0.2), so it works on whatever
the server happens to ship.
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple  # noqa: UP035 - 3.9 compatibility

REPO_ROOT = Path(__file__).resolve().parents[1]
ENV_EXAMPLE = REPO_ROOT / ".env.example"
CONFIG_MODULE = REPO_ROOT / "apps" / "api" / "app" / "config.py"

#: Section markers in .env.example look exactly like this, on their own line.
SECTION_PREFIX = "# ["
SECTION_SUFFIX = "]"

#: The section whose contents must match Settings, field for field.
API_SECTION = "api"

#: Class-body assignments that are not environment variables.
NOT_SETTINGS = frozenset({"model_config"})


def parse_settings_fields(path: Path) -> List[str]:
    """Field names of the ``Settings`` class, in declaration order."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "Settings":
            fields = []
            for statement in node.body:
                if isinstance(statement, ast.AnnAssign) and isinstance(
                    statement.target, ast.Name
                ):
                    name = statement.target.id
                    if name not in NOT_SETTINGS:
                        fields.append(name)
            return fields
    raise SystemExit(f"{path}: no class named Settings found")


def parse_env_example(path: Path) -> Tuple[Dict[str, List[str]], List[str]]:
    """Return ``{section: [keys]}`` plus any structural problems found."""
    sections: Dict[str, List[str]] = {}
    problems: List[str] = []
    current: Optional[str] = None
    seen_keys: Dict[str, int] = {}

    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if line.startswith(SECTION_PREFIX) and line.endswith(SECTION_SUFFIX):
            current = line[len(SECTION_PREFIX) : -len(SECTION_SUFFIX)].strip()
            sections.setdefault(current, [])
            continue
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            problems.append(f"{path.name}:{lineno}: not a KEY=VALUE line: {line!r}")
            continue
        key = line.split("=", 1)[0].strip()
        if not key:
            problems.append(f"{path.name}:{lineno}: empty key")
            continue
        if current is None:
            problems.append(f"{path.name}:{lineno}: {key} appears before any '# [section]' marker")
            continue
        if key in seen_keys:
            problems.append(
                f"{path.name}:{lineno}: {key} is defined twice (first at line {seen_keys[key]})"
            )
        seen_keys[key] = lineno
        sections[current].append(key)

    return sections, problems


def check(verbose: bool = False) -> List[str]:
    """Return a list of human-readable problems; empty means the check passed."""
    problems: List[str] = []
    for path in (ENV_EXAMPLE, CONFIG_MODULE):
        if not path.exists():
            problems.append(f"missing file: {path}")
    if problems:
        return problems

    fields = parse_settings_fields(CONFIG_MODULE)
    sections, structural = parse_env_example(ENV_EXAMPLE)
    problems.extend(structural)

    if API_SECTION not in sections:
        problems.append(
            f"{ENV_EXAMPLE.name}: no '# [{API_SECTION}]' section marker; "
            "the file must group variables exactly as the §A12 table does"
        )
        return problems

    documented = sections[API_SECTION]
    missing = [name for name in fields if name not in documented]
    extra = [name for name in documented if name not in fields]

    for name in missing:
        problems.append(
            f"{name}: read by app/config.py but absent from the [{API_SECTION}] "
            f"section of {ENV_EXAMPLE.name}"
        )
    for name in extra:
        problems.append(
            f"{name}: documented in the [{API_SECTION}] section of {ENV_EXAMPLE.name} "
            "but no such field on Settings"
        )

    if not problems and documented != fields and verbose:
        print(
            "note: the [api] section lists the same variables as Settings but in a "
            "different order; keeping them aligned makes review easier."
        )

    if verbose and not problems:
        print(
            "ok: {} variables in [{}] match app/config.py exactly".format(
                len(fields), API_SECTION
            )
        )
        other = {name: len(keys) for name, keys in sections.items() if name != API_SECTION}
        print("     other documented sections: {}".format(other))

    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-q", "--quiet", action="store_true", help="only print problems")
    args = parser.parse_args()

    problems = check(verbose=not args.quiet)
    if problems:
        print("env parity check FAILED:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
