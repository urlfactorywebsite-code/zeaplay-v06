"""Only this new project is collected; existing application tests never import."""

import tempfile
from pathlib import Path

import pytest


def pytest_configure(config):
    # A shared pytest-of-<user> root prunes earlier runs from other projects.
    # Pytest may clear --basetemp, so supply only our newly created empty root.
    if config.option.basetemp is None:
        owned = Path(tempfile.mkdtemp(prefix="zeaplay-phase2a-pytest-")).resolve()
        if owned.parent != Path(tempfile.gettempdir()).resolve():
            raise RuntimeError("Unexpected Phase 2A temporary root")
        config.option.basetemp = str(owned)


@pytest.fixture
def anyio_backend():
    return "asyncio"
