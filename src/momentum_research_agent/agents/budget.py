"""Per-run budgets for the ReAct loop."""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class LoopBudget:
    max_turns: int = 8
    overall_deadline_s: float = 45.0
    llm_timeout_s: float = 20.0
    tool_timeout_s: float = 10.0

    def __post_init__(self) -> None:
        if not isinstance(self.max_turns, int) or isinstance(self.max_turns, bool):
            raise ValueError("max_turns must be a positive integer")
        if self.max_turns <= 0:
            raise ValueError("max_turns must be a positive integer")
        for label, value in (
            ("overall_deadline_s", self.overall_deadline_s),
            ("llm_timeout_s", self.llm_timeout_s),
            ("tool_timeout_s", self.tool_timeout_s),
        ):
            if (
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or not math.isfinite(value)
                or value <= 0
            ):
                raise ValueError(f"{label} must be finite and positive")
