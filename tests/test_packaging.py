"""Guards against the deployed app running different versions than the tested one.

Vercel's Python builder reads pyproject.toml's [project].dependencies; the
documented local workflow reads requirements.txt. Two sources of truth for the
same list is how a deployment silently diverges from what the suite ran against.
"""

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def requirements_deps() -> list[str]:
    text = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    return [line.strip() for line in text.splitlines() if line.strip() and not line.startswith("#")]


def pyproject_deps() -> list[str]:
    with open(ROOT / "pyproject.toml", "rb") as handle:
        return tomllib.load(handle)["project"]["dependencies"]


def test_dependency_lists_are_identical() -> None:
    assert pyproject_deps() == requirements_deps(), (
        "pyproject.toml [project].dependencies and requirements.txt have diverged. "
        "Vercel installs the former; the README installs the latter."
    )


def test_every_runtime_dependency_is_pinned_exactly() -> None:
    """A floating version means the deployment is not the thing that was tested."""
    unpinned = [d for d in pyproject_deps() if "==" not in d]
    assert unpinned == [], f"unpinned runtime dependencies: {unpinned}"


def test_dev_dependencies_are_not_shipped() -> None:
    """pytest and ruff have no business inside a serverless function."""
    runtime = " ".join(pyproject_deps()).lower()
    for dev_only in ("pytest", "ruff", "watchfiles"):
        assert dev_only not in runtime, f"{dev_only} must live in requirements-dev.txt only"


def test_vercel_entry_point_exposes_the_asgi_app() -> None:
    from api.index import app as vercel_app
    from app.main import app as real_app

    assert vercel_app is real_app
