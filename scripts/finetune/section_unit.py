"""The per-section training unit (8 GB path): the pages a section cites -> that section's bullets.

Not the app's summary stage (which writes the whole summary in one call from facts). Built only from
data/golden/extracted and data/golden/summaries. Nothing here is ever truncated: a section whose pages do not
fit the token budget is split into groups of page-adjacent bullets, and a bullet whose pages alone do not fit is
dropped and reported.
"""

import json
from typing import Callable

from scripts.golden_lib import LIST_KEYS, NOT_SPECIFIED

SECTIONS = ["overview", "issuing_organization", *LIST_KEYS]

SYSTEM_PROMPT = """You write one section of a bidder-side RFP summary from the RFP pages you are given.
Rules:
- Use only the pages given. Never invent or infer. Cite in "pages" the PAGE numbers from the markers where each fact is stated.
- Copy every number, date, amount and percentage exactly as written on the page.
- Mandatory wording (shall, must, required) becomes "must"; desirable wording (should, may, preferred) becomes "desirable".
- Only obligations on the bidder count as requirements. One fact per bullet, plain paraphrase, 35 words or fewer.
Answer with JSON only, in the shape asked for."""

RULES = {
    "overview": 'Reply {"overview": {"text": "...", "pages": [n]}}. 2 to 4 sentences, at most 80 words: who buys what, why, contract length, location, reference number.',
    "issuing_organization": 'Reply {"issuing_organization": "...", "issuing_organization_pages": [n]}. Exact legal name of the buyer; department or office; tender or reference number; contact office. One string, parts separated by "; ", at most 300 characters.',
    "scope": 'Reply {"scope": [{"text": "...", "pages": [n]}]}. Deliverables and services, one bullet each: what, how much, where. At most 8 bullets.',
    "key_requirements": 'Reply {"key_requirements": [{"text": "...", "pages": [n]}]}. The most important mandatory technical and functional requirements on the bidder, pass/fail items first. At most 10 bullets.',
    "eligibility": 'Reply {"eligibility": [{"text": "...", "pages": [n]}]}. Pre-qualification criteria: turnover, experience, similar projects, certifications, registrations, JV rules, blacklisting. At most 8 bullets.',
    "important_dates": 'Reply {"important_dates": [{"text": "...", "pages": [n]}]}. One bullet per dated event: release, pre-bid meeting, query deadline, submission deadline, bid opening, bid validity.',
    "project_duration": 'Reply {"project_duration": [{"text": "...", "pages": [n]}]}. Contract duration, extension terms, delivery milestones and periods.',
    "commercial_requirements": 'Reply {"commercial_requirements": [{"text": "...", "pages": [n]}]}. EMD or bid security, performance security, tender fee, payment terms, price basis, liquidated damages and penalties, warranty. At most 8 bullets.',
    "important_conditions": 'Reply {"important_conditions": [{"text": "...", "pages": [n]}]}. Each bullet starts with exactly one of "Evaluation: ", "Submission: ", "Risk: ". Evaluation and Submission together at most 8, Risk at most 6, each pointing at a concrete clause.',
}


def bullets_of(summary: dict, key: str) -> list[dict]:
    """The section as a list of {text, pages}, golden order. A bullet that says the document is silent and cites no page
    is left out: it has no pages to build an input from."""
    if key == "overview":
        items = [summary["overview"]]
    elif key == "issuing_organization":
        items = [{"text": summary["issuing_organization"], "pages": summary.get("issuing_organization_pages", [])}]
    else:
        items = summary.get(key, [])
    for b in items:
        if not b["pages"] and NOT_SPECIFIED not in b["text"]:
            raise ValueError(f"{key}: a bullet with no page that is not a 'not specified' bullet: {b['text'][:60]!r}")
    return [{"text": b["text"], "pages": list(b["pages"])} for b in items if b["pages"]]


def answer_obj(key: str, bullets: list[dict]) -> dict:
    if key == "overview":
        return {"overview": bullets[0]}
    if key == "issuing_organization":
        return {"issuing_organization": bullets[0]["text"], "issuing_organization_pages": bullets[0]["pages"]}
    return {key: bullets}


def messages_for(key: str, pages: list[int], page_text: dict[int, str], bullets: list[dict] | None) -> list[dict]:
    block = "\n".join(f"--- [PAGE {p}] ---\n{page_text[p]}\n" for p in pages)
    msgs = [{"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"SECTION: {key}\n{RULES[key]}\n\nRFP PAGES:\n{block}"}]
    if bullets is not None:
        msgs.append({"role": "assistant", "content": json.dumps(answer_obj(key, bullets), ensure_ascii=False, indent=2)})
    return msgs


def build_examples(key: str, summary: dict, page_text: dict[int, str], count: Callable[[list[dict]], int],
                   max_len: int) -> tuple[list[dict], list[dict], bool]:
    """-> (examples, dropped, no_pages). count(messages) is the exact token length of prompt + answer.
    An example is {group, groups, pages, tokens, bullets, messages}; bullets are exact copies of the golden ones."""
    bullets = bullets_of(summary, key)
    if not bullets:
        return [], [], True

    def make(idx: list[int]) -> dict:
        group = [bullets[i] for i in idx]  # golden order inside a group
        pages = sorted({p for b in group for p in b["pages"]})
        msgs = messages_for(key, pages, page_text, group)
        return {"pages": pages, "tokens": count(msgs), "bullets": group, "messages": msgs}

    everything = make(list(range(len(bullets))))
    if everything["tokens"] <= max_len:
        return [{**everything, "group": 1, "groups": 1}], [], False

    dropped, groups, cur = [], [], []
    for i in sorted(range(len(bullets)), key=lambda i: (min(bullets[i]["pages"]), max(bullets[i]["pages"]), i)):
        if cur and make(sorted(cur + [i]))["tokens"] <= max_len:
            cur.append(i)
            continue
        if cur:
            groups.append(sorted(cur))
        cur = [i]
        alone = make([i])
        if alone["tokens"] > max_len:  # even this bullet's pages alone do not fit: dropped, never cut
            dropped.append({"section": key, "bullet": i + 1, "pages": alone["pages"], "tokens": alone["tokens"]})
            cur = []
    if cur:
        groups.append(sorted(cur))
    return [{**make(g), "group": n, "groups": len(groups)} for n, g in enumerate(groups, start=1)], dropped, False
