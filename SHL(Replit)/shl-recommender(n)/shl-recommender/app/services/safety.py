"""Safety layer: prompt-injection detection and domain-restriction guard.

This runs as a fast, deterministic pre-filter *before* the LLM call, so
injection attempts and clearly out-of-scope requests are rejected without
ever reaching (or being interpretable by) the main reasoning prompt. This is
defense-in-depth: the system prompt also instructs the LLM to refuse, but we
don't rely on the LLM alone, since instructions embedded in user text can
sometimes sway a model that only has prompt-level defenses.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_INJECTION_PATTERNS = [
    r"ignore (all|the|any) (previous|prior|above) instructions",
    r"disregard (all|the|any) (previous|prior|above)",
    r"you are now",
    r"act as (?!.*shl)",
    r"system prompt",
    r"reveal your (instructions|prompt|system prompt)",
    r"print your (instructions|prompt)",
    r"new instructions?:",
    r"forget (everything|all) (you|above)",
    r"jailbreak",
    r"do anything now",
    r"\bdan\b mode",
    r"override your (rules|guidelines|instructions)",
    r"pretend (you are|to be)",
    r"developer mode",
    r"admin (mode|override)",
    r"bypass (your|the) (safety|restrictions|filters)",
]

_OFF_TOPIC_HARD_BLOCKS = [
    (r"\b(write|debug|fix)\b.*\b(code|python|javascript|sql query|function)\b", "programming_help"),
    (r"\bis it legal\b|\blegally required\b|\bsue\b|\blawsuit\b|\bcompliance obligation\b", "legal_question"),
    (r"\bdiagnos(e|is)\b|\bmedication\b|\bsymptoms of\b|\btreat(ment)? for\b", "medical_question"),
    (r"\bstock (price|tip)\b|\binvest(ment)? advice\b|\bcrypto\b", "financial_advice"),
    (r"\bwrite (me )?a poem\b|\btell me a joke\b|\bwho (won|is the president)\b", "general_chitchat"),
]

_GENERAL_HIRING_ADVICE_PATTERNS = [
    r"how (do|should) i (interview|onboard|fire|terminate|negotiate salary)",
    r"what salary should i (offer|pay)",
    r"how to write a job description",
    r"interview questions to ask",
]


@dataclass
class SafetyVerdict:
    allowed: bool
    reason: str | None = None
    category: str | None = None


def _matches_any(text: str, patterns: list[str]) -> str | None:
    lowered = text.lower()
    for pattern in patterns:
        if re.search(pattern, lowered):
            return pattern
    return None


def check_message(text: str) -> SafetyVerdict:
    """Deterministic pre-filter. Returns allowed=False for clear violations."""
    if _matches_any(text, _INJECTION_PATTERNS):
        return SafetyVerdict(
            allowed=False,
            category="prompt_injection",
            reason=(
                "I can't follow instructions embedded in a message that try to change my "
                "behavior. I'm here to help you find SHL assessments -- what role or skills "
                "are you hiring for?"
            ),
        )

    for pattern, category in _OFF_TOPIC_HARD_BLOCKS:
        if re.search(pattern, text.lower()):
            return SafetyVerdict(
                allowed=False,
                category=category,
                reason=_refusal_message(category),
            )

    if _matches_any(text, _GENERAL_HIRING_ADVICE_PATTERNS):
        return SafetyVerdict(
            allowed=False,
            category="general_hiring_advice",
            reason=_refusal_message("general_hiring_advice"),
        )

    return SafetyVerdict(allowed=True)


def _refusal_message(category: str) -> str:
    messages = {
        "programming_help": "I can't help with writing or debugging code -- I'm scoped to recommending SHL assessments. Want help finding a technical knowledge test instead?",
        "legal_question": "That's a legal question outside what I can advise on. I can help you select assessments, but not interpret legal or regulatory obligations -- your legal/compliance team is the right resource for that.",
        "medical_question": "I can't help with medical questions. I'm scoped to SHL assessment recommendations -- happy to help with that.",
        "financial_advice": "I don't give financial or investment advice. I can help you find the right SHL assessments for a hiring need, though.",
        "general_chitchat": "I'm focused specifically on helping you find SHL assessments -- what role are you hiring for?",
        "general_hiring_advice": "General hiring process advice (interviewing, compensation, onboarding) is outside my scope -- I only help select SHL assessments. What role or skills are you assessing for?",
    }
    return messages.get(
        category,
        "That's outside what I can help with. I'm scoped to recommending SHL Individual Test Solutions -- what role are you hiring for?",
    )
