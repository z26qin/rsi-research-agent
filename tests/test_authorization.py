from __future__ import annotations

import pytest

from momentum_research_agent.errors import UnauthorizedTool
from momentum_research_agent.tools import (
    authorize_tools,
    tools_for_profile,
)


def test_unknown_profile_rejected() -> None:
    with pytest.raises(UnauthorizedTool, match="Unknown profile"):
        tools_for_profile("quant_intern")
    with pytest.raises(UnauthorizedTool, match="Unknown profile"):
        authorize_tools("quant_intern")


def test_requested_unauthorized_tool_rejected() -> None:
    with pytest.raises(UnauthorizedTool, match="shell"):
        authorize_tools("momentum_analyst", ["engine_query", "shell"])
