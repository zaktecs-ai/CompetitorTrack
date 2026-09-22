"""`.env.example` must document exactly the variables `app/config.py` reads.

CI runs the script directly too, but having it as a test means the mismatch is
caught by `pytest` locally, before a push.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
CHECKER = REPO_ROOT / "tools" / "check_env_example.py"


def _load_checker():
    spec = importlib.util.spec_from_file_location("ct_check_env_example", CHECKER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_checker_exists() -> None:
    assert CHECKER.is_file(), f"missing {CHECKER}"


def test_env_example_matches_settings() -> None:
    problems = _load_checker().check(verbose=False)
    assert problems == [], "\n".join(problems)


def test_env_example_ships_no_real_secret() -> None:
    """The template must stay a template."""
    text = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    for variable in ("JWT_SECRET", "MASTER_ENCRYPTION_KEYS", "POSTGRES_PASSWORD"):
        line = next(raw for raw in text.splitlines() if raw.startswith(f"{variable}="))
        assert "CHANGE-ME" in line, f"{variable} in .env.example must stay a placeholder"
