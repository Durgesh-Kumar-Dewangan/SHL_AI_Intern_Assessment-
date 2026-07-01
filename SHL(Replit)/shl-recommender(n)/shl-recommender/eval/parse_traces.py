"""Parses the provided C1..C10 markdown conversation traces into a structured
format: per-turn user utterances plus the expected final shortlist (extracted
from the last markdown table in the trace) and the expected end_of_conversation
flag sequence.

Trace format (see eval/traces/*.md):
    ### Turn N
    **User**
    > <user message>
    **Agent**
    <agent reply text>
    | # | Name | Test Type | ... | URL |
    |...|
    _`end_of_conversation`: **true/false**_
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class TraceTurn:
    turn_number: int
    user_message: str
    agent_reply: str
    table_names: list[str] = field(default_factory=list)
    table_urls: list[str] = field(default_factory=list)
    end_of_conversation: bool = False


@dataclass
class Trace:
    trace_id: str
    turns: list[TraceTurn]

    @property
    def final_shortlist_names(self) -> list[str]:
        for turn in reversed(self.turns):
            if turn.table_names:
                return turn.table_names
        return []

    @property
    def final_shortlist_urls(self) -> list[str]:
        for turn in reversed(self.turns):
            if turn.table_urls:
                return turn.table_urls
        return []

    @property
    def user_messages_in_order(self) -> list[str]:
        return [t.user_message for t in self.turns]


_TURN_RE = re.compile(r"### Turn (\d+)\n\n\*\*User\*\*\n\n(.*?)\n\n\*\*Agent\*\*\n\n(.*?)(?=\n### Turn|\Z)", re.DOTALL)
_TABLE_ROW_RE = re.compile(r"^\|\s*\d+\s*\|\s*(.*?)\s*\|.*?\|\s*<?(https://[^\s|>]+)>?\s*\|\s*$", re.MULTILINE)
_EOC_RE = re.compile(r"end_of_conversation.*?\*\*(true|false)\*\*")


def _clean_user_message(raw: str) -> str:
    lines = [l.lstrip("> ").strip() for l in raw.strip().splitlines()]
    return " ".join(l for l in lines if l)


def parse_trace_file(path: Path) -> Trace:
    text = path.read_text(encoding="utf-8")
    turns: list[TraceTurn] = []
    for match in _TURN_RE.finditer(text):
        turn_number = int(match.group(1))
        user_raw = match.group(2)
        agent_block = match.group(3)

        user_message = _clean_user_message(user_raw)

        # Table rows: "| # | Name | Test Type | Keys | Duration | Languages | URL |"
        names, urls = [], []
        for row in _TABLE_ROW_RE.finditer(agent_block):
            names.append(row.group(1).strip())
            urls.append(row.group(2).strip())

        eoc_match = _EOC_RE.search(agent_block)
        end_of_conversation = bool(eoc_match and eoc_match.group(1) == "true")

        # Agent reply text = text before the table (or before the recommendations/eoc annotation)
        reply_text = agent_block.split("|")[0].strip()
        reply_text = re.split(r"_No recommendations|_`end_of_conversation`", reply_text)[0].strip()

        turns.append(
            TraceTurn(
                turn_number=turn_number,
                user_message=user_message,
                agent_reply=reply_text,
                table_names=names,
                table_urls=urls,
                end_of_conversation=end_of_conversation,
            )
        )

    return Trace(trace_id=path.stem, turns=turns)


def load_all_traces(directory: Path) -> list[Trace]:
    return [parse_trace_file(p) for p in sorted(directory.glob("C*.md"))]


if __name__ == "__main__":
    traces_dir = Path(__file__).parent / "traces"
    traces = load_all_traces(traces_dir)
    for t in traces:
        print(f"{t.trace_id}: {len(t.turns)} turns, final shortlist = {t.final_shortlist_names}")
