"""Conversation orchestration: safety -> retrieval -> LLM -> grounding verification.

Stateless by design: every call receives the full message history and derives
everything (retrieval query, current shortlist, turn count) from it. No
per-conversation state is stored anywhere in this service.

Shortlist continuity across stateless turns: when we return recommendations,
we embed the verified URLs in a hidden HTML comment appended to the `reply`
text. Because clients echo the `reply` back as the assistant message on the
next call, this marker travels in the message history. `_infer_current_shortlist`
extracts URLs from the marker, giving deterministic continuity rather than the
fragile name-scanning heuristic.

  Format: <!-- __SHORTLIST__: url1|url2|url3 -->
"""
from __future__ import annotations

import logging
import re

from app.config import Settings
from app.data.catalog_loader import CatalogItem
from app.models.schemas import ChatResponse, Message, Recommendation
from app.prompts.system_prompt import COMPARISON_HINT, SYSTEM_PROMPT, build_user_prompt
from app.retrieval.retriever import MetadataFilter, Retriever, tokenize
from app.services.llm_client import LLMClient, LLMError
from app.services.safety import check_message

logger = logging.getLogger("shl_recommender.conversation")

_COMPARE_TRIGGERS = re.compile(
    r"\bdifference between\b|\bcompare\b|\bvs\.?\b|\bversus\b|\bhow (does|do).{1,40}differ\b",
    re.IGNORECASE,
)

_SHORTLIST_MARKER_RE = re.compile(r"<!--\s*__SHORTLIST__:\s*(.*?)\s*-->", re.DOTALL)


def _embed_shortlist_marker(reply: str, urls: list[str]) -> str:
    """Append a hidden HTML comment marker carrying recommended URLs.
    This marker is invisible in rendered HTML but survives the stateless
    round-trip when the client echoes the reply back as an assistant message.
    """
    if not urls:
        return reply
    marker = "<!-- __SHORTLIST__: " + "|".join(urls) + " -->"
    return reply.rstrip() + "\n" + marker


def _clean_reply_for_history(text: str) -> str:
    """Strip the hidden marker when building conversation history for the LLM,
    so the LLM sees clean, readable conversation text."""
    return _SHORTLIST_MARKER_RE.sub("", text).rstrip()


class ConversationService:
    def __init__(self, retriever: Retriever, llm_client: LLMClient, settings: Settings) -> None:
        self.retriever = retriever
        self.llm_client = llm_client
        self.settings = settings

    # ---------------------------------------------------------------- utils

    @staticmethod
    def _format_history(messages: list[Message]) -> str:
        lines = []
        for m in messages:
            speaker = "User" if m.role == "user" else "Assistant"
            content = _clean_reply_for_history(m.content)
            lines.append(f"{speaker}: {content}")
        return "\n".join(lines)

    @staticmethod
    def _last_user_message(messages: list[Message]) -> str:
        for m in reversed(messages):
            if m.role == "user":
                return m.content
        return ""

    def _recent_query_text(self, messages: list[Message], window: int = 4) -> str:
        user_msgs = [m.content for m in messages if m.role == "user"]
        return " ".join(user_msgs[-window:])

    def _infer_current_shortlist(self, messages: list[Message]) -> list[str]:
        """Reconstruct the previously-shown shortlist URLs from the hidden marker
        embedded in assistant replies. Falls back to name-scanning for backward
        compatibility with messages that don't have the marker yet.
        """
        assistant_msgs = [m.content for m in messages if m.role == "assistant"]
        if not assistant_msgs:
            return []

        # Primary: look for the hidden marker (most recent wins)
        for reply in reversed(assistant_msgs):
            match = _SHORTLIST_MARKER_RE.search(reply)
            if match:
                raw = match.group(1).strip()
                urls = [u.strip() for u in raw.split("|") if u.strip()]
                valid = [u for u in urls if self.retriever.get_by_url(u) is not None]
                if valid:
                    return valid

        # Fallback: scan last assistant reply for catalog product-name mentions
        last_reply = assistant_msgs[-1].lower()
        urls: list[str] = []
        for item in self.retriever.items:
            if item.name.lower() in last_reply:
                urls.append(item.url)
        return urls

    def _extract_named_assessments(self, text: str) -> list[CatalogItem]:
        """Pulls out catalog items explicitly named in a comparison/refine query."""
        found: list[CatalogItem] = []
        lowered = text.lower()
        query_tokens = set(tokenize(text))
        for item in self.retriever.items:
            name_lower = item.name.lower()
            if len(name_lower) >= 4 and (name_lower in lowered or lowered in name_lower):
                found.append(item)
                continue
            name_tokens = tokenize(item.name)
            # Match alphanumeric acronyms like OPQ32r, G+, SVAR
            distinctive = [
                t for t in name_tokens
                if len(t) >= 3 and (any(c.isdigit() for c in t) or t.isupper())
            ]
            if distinctive and any(t in query_tokens for t in distinctive):
                found.append(item)
        return found

    def _build_metadata_filter(self, text: str) -> MetadataFilter | None:
        lowered = text.lower()
        max_duration = None
        m = re.search(r"under (\d+)\s*minutes?", lowered) or re.search(
            r"less than (\d+)\s*minutes?", lowered
        )
        if m:
            max_duration = int(m.group(1))
        require_remote = True if "remote" in lowered else None
        require_adaptive = True if "adaptive" in lowered else None
        if not any([max_duration, require_remote, require_adaptive]):
            return None
        return MetadataFilter(
            max_duration_minutes=max_duration,
            require_remote=require_remote,
            require_adaptive=require_adaptive,
        )

    # ------------------------------------------------------------- pipeline

    async def handle_chat(self, messages: list[Message]) -> ChatResponse:
        if not messages:
            return ChatResponse(
                reply="Hi! Tell me about the role you're hiring for and I'll help you find the right SHL assessments.",
                recommendations=None,
                end_of_conversation=False,
            )

        last_user_text = self._last_user_message(messages)

        # --- 1. Deterministic safety pre-filter ---
        verdict = check_message(last_user_text)
        if not verdict.allowed:
            return ChatResponse(
                reply=verdict.reason or "I can't help with that.",
                recommendations=None,
                end_of_conversation=False,
            )

        # --- 2. Build retrieval query + candidates ---
        query_text = self._recent_query_text(messages)
        metadata_filter = self._build_metadata_filter(last_user_text)
        scored = self.retriever.search(
            query_text, top_k=self.settings.top_k_retrieval, metadata_filter=metadata_filter
        )
        candidates: dict[str, CatalogItem] = {s.item.url: s.item for s in scored}

        is_comparison = bool(_COMPARE_TRIGGERS.search(last_user_text))
        if is_comparison:
            for item in self._extract_named_assessments(last_user_text):
                candidates[item.url] = item

        # Always inject current shortlist items into candidates so the LLM
        # can refine them without them dropping out of context.
        current_shortlist_urls = self._infer_current_shortlist(messages)
        for url in current_shortlist_urls:
            item = self.retriever.get_by_url(url)
            if item:
                candidates[item.url] = item

        candidate_list = [c.to_llm_context() for c in candidates.values()]

        # --- 3. Turn count ---
        # user_turns: for the LLM prompt's awareness of where we are
        # total_messages: for the turn-cap safety net (assignment counts all messages)
        turn_number = sum(1 for m in messages if m.role == "user")
        total_messages = len(messages)

        # --- 4. Call the LLM ---
        conversation_text = self._format_history(messages)
        user_prompt = build_user_prompt(
            conversation_text,
            candidate_list,
            current_shortlist_urls,
            turn_number=turn_number,
            max_turns=self.settings.max_turns,
        )
        if is_comparison:
            user_prompt += COMPARISON_HINT

        try:
            parsed = await self.llm_client.complete_json(SYSTEM_PROMPT, user_prompt)
        except LLMError as exc:
            logger.error("LLM call failed: %s", exc)
            return ChatResponse(
                reply=(
                    "I'm having trouble reaching the recommendation engine right now. "
                    "Could you repeat that, or try again in a moment?"
                ),
                recommendations=None,
                end_of_conversation=False,
            )

        action = str(parsed.get("action", "")).lower()
        reply_text = (
            str(parsed.get("reply", "")).strip()
            or "Could you tell me more about the role you're hiring for?"
        )
        raw_urls = parsed.get("recommended_urls") or []
        end_of_conversation = bool(parsed.get("end_of_conversation", False))

        # --- 5. Grounding verification ---
        recommendations: list[Recommendation] | None = None
        verified_urls: list[str] = []

        if action in ("recommend", "refine") and raw_urls:
            recs: list[Recommendation] = []
            for url in raw_urls:
                item = self.retriever.get_by_url(url)
                if item is None:
                    logger.warning("Dropping ungrounded URL: %s", url)
                    continue
                recs.append(Recommendation(name=item.name, url=item.url, test_type=item.test_type))
                verified_urls.append(item.url)
                if len(recs) >= self.settings.max_recommendations:
                    break
            if recs:
                recommendations = recs
            else:
                action = "clarify"
                end_of_conversation = False

        # --- 6. Embed shortlist marker in reply for stateless continuity ---
        # This marker travels in the message history so that _infer_current_shortlist
        # can reconstruct the shortlist deterministically on the next call.
        if verified_urls:
            reply_text = _embed_shortlist_marker(reply_text, verified_urls)

        # --- 7. Turn-cap safety net ---
        # Use total message count (user + assistant) + 1 for this reply,
        # matching the assignment's 8-turn cap definition.
        projected_turns = total_messages + 1
        if projected_turns >= self.settings.max_turns and not recommendations and candidates:
            fallback_items = list(candidates.values())[: self.settings.max_recommendations]
            recommendations = [
                Recommendation(name=i.name, url=i.url, test_type=i.test_type)
                for i in fallback_items
            ]
            fallback_urls = [i.url for i in fallback_items]
            if not reply_text or action not in ("recommend", "refine"):
                reply_text = (
                    "Here's my best shortlist based on what you've shared so far."
                )
            reply_text = _embed_shortlist_marker(reply_text, fallback_urls)
            end_of_conversation = True

        if recommendations is None:
            end_of_conversation = False

        # Strip the shortlist marker before returning — it's only for history continuity,
        # not something the API consumer should ever see.
        clean_reply = _clean_reply_for_history(reply_text)

        return ChatResponse(
            reply=clean_reply,
            recommendations=recommendations,
            end_of_conversation=end_of_conversation,
        )
