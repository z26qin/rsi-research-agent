"""Narrow, deterministic missing-evidence concepts for the momentum guard.

This scorer-owned vocabulary is never supplied to research or verification.
Every required concept needs a current explicit unknown assertion, not a question
or a nearby missing cue about another subject. Unrecognized requirements fail.
"""

from __future__ import annotations

import re


_REQUIREMENTS = {
    "broad cross sectional reversal breadth": {"breadth"},
    "preceding bear market drawdown and rebound": {"drawdown", "rebound"},
    "prior loser versus winner beta spread": {"beta_spread"},
}


def _normal(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[-‐‑–—_]", " ", text.casefold())).strip(" .")


_SUBJECTS = {
    "breadth": {
        "broad cross sectional reversal breadth",
        "cross sectional reversal breadth",
        "breadth of the cross sectional reversal",
        "cross sectional breadth of the momentum reversal",
    },
    "drawdown": {
        "preceding bear market drawdown",
        "prior bear market drawdown",
        "previous bear market drawdown",
        "prior bear market decline",
        "preceding bear market decline",
    },
    "rebound": {
        "subsequent market rebound",
        "following market rebound",
        "subsequent market recovery",
        "following market recovery",
    },
    "beta_spread": {
        "prior loser versus winner beta spread",
        "beta difference between prior losers and winners",
        "beta spread between prior losers and winners",
        "prior loser versus prior winner market beta difference",
        "market beta difference between prior losers and winners",
        "beta spread of prior losers relative to winners",
        "beta difference of prior losers relative to winners",
    },
}


def _concepts(text: str) -> set[str]:
    # Whole nominal subjects, not bags of related words. This excludes assertions
    # about who said something, unrelated measurements, and non-market recovery.
    text = re.sub(r"^the ", "", text)
    text = re.sub(r" (?:evidence|data)$", "", text)
    if text == "preceding bear market drawdown and rebound":
        return {"drawdown", "rebound"}
    for drawdown in _SUBJECTS["drawdown"]:
        for rebound in _SUBJECTS["rebound"]:
            if text == drawdown + " and " + rebound:
                return {"drawdown", "rebound"}
    return {concept for concept, aliases in _SUBJECTS.items() if text in aliases}


def _mentioned_concepts(text: str) -> set[str]:
    # A conservative contradiction screen may match a larger clause; positive
    # credit still requires a complete approved subject via _concepts.
    return {
        concept
        for concept, aliases in _SUBJECTS.items()
        if any(alias in text for alias in aliases)
    }


def missing_concepts_acknowledged(
    requirements: list[str], statements: list[str]
) -> bool:
    required = set()
    for requirement in requirements:
        concepts = _REQUIREMENTS.get(_normal(requirement))
        if concepts is None:
            return False
        required.update(concepts)
    unknown, contradicted = set(), set()
    for statement in statements:
        text = _normal(statement)
        # A later-resolution assertion makes an earlier missing statement unsafe
        # to count, even when its object is an anaphor such as "them".
        if re.search(
            r"\b(now|latest|later)\b.*\b(supplies|provides|supplied|provided|available|known|measured)\b",
            text,
        ):
            return False
        clauses = re.split(r"(?<=[.;!?])\s*|\b(?:but|however|although)\b", text)
        for clause in clauses:
            if clause.rstrip().endswith("?"):
                continue
            clause = clause.strip(" ,:.!;")
            concepts = _mentioned_concepts(clause)
            if (
                not concepts
                and "preceding bear market drawdown and rebound" not in clause
            ):
                continue
            if re.search(
                r"\b(no missing|not unavailable|not unknown|not missing|false|untrue)\b",
                clause,
            ):
                contradicted.update(concepts)
                continue
            if re.search(
                r"\b(?:is|are|was|were) (?:available|known|provided|disclosed|measured|established|[+\-]?\d)",
                clause,
            ):
                contradicted.update(concepts)
                continue
            subject = None
            prefix = re.fullmatch(
                r"(?:missing(?: evidence| data)?\s*:|(?:we )?(?:lack|do not have|cannot determine|cannot establish|cannot quantify|cannot verify))\s+(.+)",
                clause,
            )
            suffix = re.fullmatch(
                r"(.+?)\s+(?:is|are|was|were|remains?)\s+(?:unavailable|unknown|missing|not (?:available|provided|disclosed|reported|established|measured))",
                clause,
            )
            if prefix:
                subject = prefix.group(1)
            elif suffix:
                subject = suffix.group(1)
            if subject and not re.search(
                r"\b(whether|if|available|measured|provided|known)\b", subject
            ):
                acknowledged = _concepts(subject)
                if acknowledged:
                    unknown.update(acknowledged)
                    continue
            # The concept is discussed but its status is not an explicitly
            # recognized unknown. Do not guess around conflicting declarations.
            contradicted.update(concepts)
    return required <= unknown and not required.intersection(contradicted)
