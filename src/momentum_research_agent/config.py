"""Environment, client factory, and DeepSeek cost estimates."""

from __future__ import annotations

import os
from pathlib import Path

from openai import AsyncOpenAI

from momentum_research_agent.models.schemas import UsageSummary

DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEFAULT_SUB_MODEL = "deepseek-chat"
DEFAULT_COORDINATOR_MODEL = "deepseek-reasoner"

# USD per 1M tokens. User-specified chat/reasoner rates plus current V4 list
# prices (off-peak, cache miss) from https://api-docs.deepseek.com/quick_start/pricing
# as of 2026-09. Cache-hit and peak/off-peak splits are ignored for a simple estimate.
PRICE_PER_MILLION: dict[str, tuple[float, float]] = {
    "deepseek-chat": (0.27, 1.10),
    "deepseek-reasoner": (0.55, 2.19),
    "deepseek-v4-flash": (0.22, 0.66),
    "deepseek-v4-pro": (0.66, 1.98),
}


def find_project_root(start: Path | None = None) -> Path:
    current = (start or Path.cwd()).resolve()
    for candidate in [current, *current.parents]:
        if (candidate / "pyproject.toml").exists():
            return candidate
    return current


def reports_root(project_root: Path | None = None) -> Path:
    return (project_root or find_project_root()) / "reports"


def load_env(project_root: Path | None = None) -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    root = project_root or find_project_root()
    load_dotenv(root / ".env")
    if shared := os.environ.get("MOMENTUM_ENV_FILE"):
        load_dotenv(Path(shared).expanduser())
    load_dotenv()


def deepseek_api_key() -> str | None:
    return os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("DeepSeekAPI")


def sub_agent_model() -> str:
    return os.environ.get("SUB_AGENT_MODEL", DEFAULT_SUB_MODEL)


def coordinator_model() -> str:
    return os.environ.get("COORDINATOR_MODEL", DEFAULT_COORDINATOR_MODEL)


def make_client() -> AsyncOpenAI:
    api_key = deepseek_api_key()
    if not api_key:
        raise RuntimeError(
            "DEEPSEEK_API_KEY is not set. Copy .env.example to .env and add your key."
        )
    return AsyncOpenAI(
        api_key=api_key,
        base_url=os.environ.get("DEEPSEEK_BASE_URL", DEEPSEEK_BASE_URL),
    )


def estimate_cost_usd(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    input_rate, output_rate = PRICE_PER_MILLION.get(model, PRICE_PER_MILLION["deepseek-chat"])
    return (prompt_tokens / 1_000_000) * input_rate + (completion_tokens / 1_000_000) * output_rate


def usage_cost_usd(summary: UsageSummary) -> float:
    return sum(
        estimate_cost_usd(model, bucket["prompt_tokens"], bucket["completion_tokens"])
        for model, bucket in summary.totals().items()
    )
