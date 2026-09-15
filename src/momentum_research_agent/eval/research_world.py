"""Approved, deterministic research worlds for autonomous policy evaluation."""

from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from datetime import date, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from momentum_research_agent.models.schemas import (
    EvidenceCategory,
    EvidenceStance,
    MomentumCapability,
)
from momentum_research_agent.tools import PROFILE_TOOLS, RESEARCH_PROFILES

CAPABILITY_TAXONOMY = frozenset(
    {
        "SOURCE_DISCOVERY",
        "SOURCE_QUALITY",
        "CONTRADICTION_SEARCH",
        "ENGINE_GROUNDING",
        "CLAIM_WITHHOLDING",
        "AS_OF_DISCIPLINE",
        "CROWDING_CONFIRMATION",
        "REPLAN_FAILURE",
    }
)
_SUPPORTED_TOOLS = frozenset({"web_search", "read_url", "engine_query"})
_TOKEN_RE = re.compile(r"[a-z0-9]+")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _validate_iso(value: str) -> str:
    try:
        datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("must be an ISO date or timestamp") from exc
    return value


class FrozenSource(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    url: str = Field(min_length=1)
    title: str = Field(min_length=1)
    text: str = Field(min_length=1)
    published_at: str
    quality: float = Field(ge=0.0, le=1.0)
    keywords: list[str] = Field(default_factory=list)

    _published_at_is_iso = field_validator("published_at")(_validate_iso)


class HiddenFact(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    fact_id: str = Field(min_length=1)
    source_url: str = Field(min_length=1)
    quote: str = Field(min_length=1)
    claim: str = Field(min_length=1)
    stance: EvidenceStance
    category: EvidenceCategory
    required: bool = True


class PublicResearchWorld(BaseModel):
    """Agent-visible data. This type deliberately has no evaluator fields."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    world_id: str
    research_question: str
    as_of: str
    allowed_profiles: list[str]
    allowed_tools: list[str]
    engine_observation: dict[str, Any]
    sources: list[FrozenSource]
    delivery_contract: str


class FrozenResearchWorld(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    world_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    research_question: str = Field(min_length=1)
    as_of: str
    capability: MomentumCapability
    capabilities: list[str]
    allowed_profiles: list[str]
    allowed_tools: list[str]
    engine_observation: dict[str, Any]
    sources: list[FrozenSource]
    hidden_facts: list[HiddenFact]
    delivery_contract: str = Field(min_length=1)
    provenance: str = Field(min_length=1)
    guard: bool
    require_withholding: bool = False
    missing_evidence: list[str] = Field(default_factory=list)
    contradiction_fact_ids: list[str] = Field(default_factory=list)

    @field_validator("as_of")
    @classmethod
    def as_of_is_iso_date(cls, value: str) -> str:
        try:
            date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("as_of must be an ISO date") from exc
        return value

    @field_validator("capabilities")
    @classmethod
    def capabilities_are_stable(cls, value: list[str]) -> list[str]:
        unknown = set(value) - CAPABILITY_TAXONOMY
        if unknown:
            raise ValueError(f"unknown capabilities: {sorted(unknown)}")
        if not value or len(value) != len(set(value)):
            raise ValueError("capabilities must be non-empty and unique")
        return value

    @field_validator("allowed_tools")
    @classmethod
    def tools_are_frozen_adapter_tools(cls, value: list[str]) -> list[str]:
        unknown = set(value) - _SUPPORTED_TOOLS
        if unknown:
            raise ValueError(f"unsupported frozen tools: {sorted(unknown)}")
        if not value or len(value) != len(set(value)):
            raise ValueError("allowed_tools must be non-empty and unique")
        return value

    @field_validator("allowed_profiles")
    @classmethod
    def profiles_are_authorized_research_profiles(cls, value: list[str]) -> list[str]:
        unknown = set(value) - RESEARCH_PROFILES
        if unknown:
            raise ValueError(f"unknown research profiles: {sorted(unknown)}")
        if not value or len(value) != len(set(value)):
            raise ValueError("allowed_profiles must be non-empty and unique")
        return value

    @model_validator(mode="after")
    def hidden_facts_bind_to_sources(self) -> FrozenResearchWorld:
        sources = {source.url: source for source in self.sources}
        if not self.sources:
            raise ValueError("a world must contain at least one source")
        if len(sources) != len(self.sources):
            raise ValueError("duplicate source URL")
        for source in self.sources:
            published = datetime.fromisoformat(source.published_at).date()
            if published > date.fromisoformat(self.as_of):
                raise ValueError(f"source published after world as_of: {source.url}")
        authorized_tools = set().union(
            *(set(PROFILE_TOOLS[profile]) for profile in self.allowed_profiles)
        )
        unauthorized = set(self.allowed_tools) - authorized_tools
        if unauthorized:
            raise ValueError(
                f"tools not authorized by allowed research profiles: {sorted(unauthorized)}"
            )
        fact_ids: set[str] = set()
        for fact in self.hidden_facts:
            if fact.fact_id in fact_ids:
                raise ValueError(f"duplicate hidden fact id: {fact.fact_id}")
            fact_ids.add(fact.fact_id)
            source = sources.get(fact.source_url)
            if source is None:
                raise ValueError(f"hidden fact uses unknown source: {fact.source_url}")
            sentences = {
                sentence.strip()
                for sentence in re.split(r"(?<=[.!?])\s+", source.text.strip())
                if sentence.strip()
            }
            if fact.quote.strip() not in sentences:
                raise ValueError(
                    f"hidden fact quote is not an exact source sentence: {fact.fact_id}"
                )
        if not set(self.contradiction_fact_ids).issubset(fact_ids):
            raise ValueError("contradiction_fact_ids must reference hidden facts")
        if self.require_withholding and not self.missing_evidence:
            raise ValueError("withholding worlds must identify missing evidence")
        return self

    @property
    def content_hash(self) -> str:
        payload = json.dumps(
            self.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def public_world(self) -> PublicResearchWorld:
        return PublicResearchWorld(
            world_id=self.world_id,
            research_question=self.research_question,
            as_of=self.as_of,
            allowed_profiles=deepcopy(self.allowed_profiles),
            allowed_tools=deepcopy(self.allowed_tools),
            engine_observation=deepcopy(self.engine_observation),
            sources=[source.model_copy(deep=True) for source in self.sources],
            delivery_contract=self.delivery_contract,
        )


class FrozenWorldAdapter:
    """Deterministic, no-network tool adapter over agent-visible world data."""

    def __init__(self, world: PublicResearchWorld) -> None:
        self._world = world.model_copy(deep=True)
        self._sources = {source.url: source for source in self._world.sources}

    def call(self, tool: str, arguments: dict[str, Any]) -> str:
        if tool not in self._world.allowed_tools or tool not in _SUPPORTED_TOOLS:
            raise ValueError(f"unsupported frozen tool: {tool}")
        if not isinstance(arguments, dict):
            raise ValueError("tool arguments must be an object")  # noqa: TRY004 -- uniform adapter contract error
        if tool == "web_search":
            result = self._web_search(arguments)
        elif tool == "read_url":
            result = self._read_url(arguments)
        else:
            result = self._engine_query(arguments)
        return json.dumps(result, sort_keys=True, separators=(",", ":"))

    def _web_search(self, arguments: dict[str, Any]) -> dict[str, Any]:
        if set(arguments) - {"query", "top_k", "max_results"}:
            raise ValueError("web_search received unsupported arguments")
        query = arguments.get("query")
        if not isinstance(query, str) or not query.strip() or len(query) > 1000:
            raise ValueError(
                "query must be a non-empty string of at most 1000 characters"
            )
        if "top_k" in arguments and "max_results" in arguments:
            raise ValueError("supply only one of top_k or max_results")
        top_k = arguments.get("top_k", arguments.get("max_results", 5))
        if (
            isinstance(top_k, bool)
            or not isinstance(top_k, int)
            or not 1 <= top_k <= 10
        ):
            raise ValueError("top_k must be an integer from 1 through 10")
        query_tokens = set(_TOKEN_RE.findall(query.lower()))
        ranked: list[tuple[int, float, str, FrozenSource]] = []
        for source in self._world.sources:
            title_tokens = _TOKEN_RE.findall(source.title.lower())
            keyword_tokens = _TOKEN_RE.findall(" ".join(source.keywords).lower())
            text_tokens = _TOKEN_RE.findall(source.text.lower())
            score = sum(token in query_tokens for token in text_tokens)
            score += 3 * sum(token in query_tokens for token in title_tokens)
            score += 4 * sum(token in query_tokens for token in keyword_tokens)
            if score:
                ranked.append((score, source.quality, source.url, source))
        ranked.sort(key=lambda item: (-item[0], -item[1], item[2]))
        sources = [
            {
                "url": source.url,
                "title": source.title,
                "published_at": source.published_at,
                "quality": source.quality,
            }
            for _, _, _, source in ranked[:top_k]
        ]
        return {
            "status": "ok",
            "evidence_kind": "source_discovery",
            "provider": "frozen_world",
            "query": query,
            "sources": sources,
            "results": sources,
        }

    def _read_url(self, arguments: dict[str, Any]) -> dict[str, Any]:
        if set(arguments) != {"url"} or not isinstance(arguments.get("url"), str):
            raise ValueError("read_url accepts exactly one string url")
        source = self._sources.get(arguments["url"])
        if source is None:
            raise ValueError("unknown frozen URL")
        return {
            **source.model_dump(mode="json"),
            "status": "ok",
            "evidence_kind": "page_content",
            "requested_url": source.url,
        }

    def _engine_query(self, arguments: dict[str, Any]) -> dict[str, Any]:
        if set(arguments) - {"end"}:
            raise ValueError("engine_query received unsupported arguments")
        end = arguments.get("end", self._world.as_of)
        if end != self._world.as_of:
            raise ValueError("engine_query end must equal the frozen world as_of")
        observation = deepcopy(self._world.engine_observation)
        observation["as_of"] = self._world.as_of
        observation["simulation"] = True
        observation["delivery_contract"] = {
            "verdict": "simulation_only",
            "note": "Frozen evaluation observation; never valid for live delivery.",
        }
        return observation


def load_approved_worlds(fixture_dir: Path | None = None) -> list[FrozenResearchWorld]:
    """Load only worlds whose complete evaluator payload is pinned by manifest."""

    root = fixture_dir or Path(__file__).with_name("fixtures") / "research_worlds"
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1 or not isinstance(
        manifest.get("worlds"), dict
    ):
        raise ValueError("invalid approved-world manifest")
    if not manifest["worlds"]:
        raise ValueError("approved-world manifest must contain at least one world")
    worlds: list[FrozenResearchWorld] = []
    world_ids: set[str] = set()
    for filename, approved_hash in manifest["worlds"].items():
        if Path(filename).name != filename or not _SHA256_RE.fullmatch(
            str(approved_hash)
        ):
            raise ValueError("invalid approved-world manifest entry")
        world = FrozenResearchWorld.model_validate_json(
            (root / filename).read_text(encoding="utf-8")
        )
        if world.content_hash != approved_hash:
            raise ValueError(f"world content hash mismatch: {filename}")
        if world.world_id in world_ids:
            raise ValueError(f"duplicate approved world_id: {world.world_id}")
        world_ids.add(world.world_id)
        worlds.append(world)
    return worlds


__all__ = [
    "CAPABILITY_TAXONOMY",
    "FrozenResearchWorld",
    "FrozenSource",
    "FrozenWorldAdapter",
    "HiddenFact",
    "PublicResearchWorld",
    "load_approved_worlds",
]
