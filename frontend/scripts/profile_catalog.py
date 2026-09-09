"""Static profile discovery without importing the research runtime."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

from artifact_io import diagnostic, read_text


def _profile_tools(tree: ast.AST) -> Any:
    for node in getattr(tree, "body", []):
        target = None
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
        elif isinstance(node, ast.AnnAssign):
            target = node.target
        if isinstance(target, ast.Name) and target.id == "PROFILE_TOOLS":
            return ast.literal_eval(node.value)
    return None


def load_profile_catalog(project_root: Path) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    tools_path = project_root / "src/momentum_research_agent/tools/__init__.py"
    if not tools_path.is_file() or tools_path.is_symlink():
        return [], [
            diagnostic(tools_path, project_root, "profile_tools_missing", "PROFILE_TOOLS source was not found")
        ]

    source, diagnostics = read_text(tools_path, project_root)
    if source is None:
        return [], diagnostics
    try:
        catalog = _profile_tools(ast.parse(source, filename=tools_path.as_posix()))
    except (SyntaxError, ValueError, TypeError):
        catalog = None
    if not isinstance(catalog, dict):
        diagnostics.append(
            diagnostic(
                tools_path,
                project_root,
                "profile_tools_missing",
                "PROFILE_TOOLS must be a literal dictionary",
            )
        )
        return [], diagnostics
    if not all(
        isinstance(name, str)
        and isinstance(tools, list)
        and all(isinstance(tool, str) for tool in tools)
        for name, tools in catalog.items()
    ):
        diagnostics.append(
            diagnostic(
                tools_path,
                project_root,
                "profile_tools_invalid",
                "PROFILE_TOOLS entries must map string names to string lists",
            )
        )
        return [], diagnostics

    profiles: list[dict[str, Any]] = []
    profiles_root = project_root / "src/momentum_research_agent/agents/profiles"
    for name in sorted(catalog):
        tools = catalog[name]
        markdown_path = profiles_root / f"{name}.md"
        description = ""
        if markdown_path.is_file() and not markdown_path.is_symlink():
            markdown, markdown_diagnostics = read_text(markdown_path, project_root)
            diagnostics.extend(markdown_diagnostics)
            if markdown:
                description = next((line.strip() for line in markdown.splitlines() if line.strip()), "")
        else:
            diagnostics.append(
                diagnostic(
                    markdown_path,
                    project_root,
                    "profile_missing",
                    f"Profile Markdown for {name} was not found",
                )
            )
        profiles.append(
            {
                "name": name,
                "displayName": name.replace("_", " ").title(),
                "description": description,
                "tools": list(tools),
                "kind": "verification" if name == "verifier" else "research",
            }
        )
    return profiles, diagnostics
