import pytest


@pytest.fixture(autouse=True)
def _disable_pipeline_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep FakeClient coordinator tests off live run_mvp unless a test opts in."""
    monkeypatch.setenv("MOMENTUM_DISABLE_PIPELINE", "1")
