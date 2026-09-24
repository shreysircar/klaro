import json
import re
import time
from backend.config import MODEL_TAG, llm

from backend.llm.executive_summary.schema import PassBInformation
from backend.llm.executive_summary.prompts import (
    PASS_B_SYSTEM_PROMPT,
    build_pass_b_user_prompt,
)

MODEL = MODEL_TAG


def run_pass_b(page_text: str, chunk_id: int, pages: list[int]) -> tuple[PassBInformation, float, bool, str | None]:
    """
    Executes Pass B (Commercial / Contractual Information Extraction: important_dates, commercial_requirements, project_duration, important_conditions).
    Returns (PassBInformation, elapsed_seconds, success_flag, error_message).
    """
    user_prompt = build_pass_b_user_prompt(page_text, chunk_id, pages)
    fallback_page = pages[0] if pages else 1

    start_time = time.time()
    error_msg = None
    success = False

    try:
        response = llm.chat(
            model=MODEL,
            think=False,
            format="json",
            messages=[
                {"role": "system", "content": PASS_B_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
        )

        elapsed = time.time() - start_time
        raw_content = response.message.content.strip() if response.message and response.message.content else ""

        info = parse_pass_b_response(raw_content, fallback_page)
        success = True
        return info, round(elapsed, 2), success, None

    except Exception as e:
        elapsed = time.time() - start_time
        error_msg = str(e)
        print(f"  [Pass B Error on Chunk {chunk_id}]: {error_msg}")
        return PassBInformation(), round(elapsed, 2), False, error_msg


def parse_pass_b_response(raw_content: str, fallback_page: int) -> PassBInformation:
    raw_clean = raw_content.strip()
    if raw_clean.startswith("```"):
        raw_clean = raw_clean.split("\n", 1)[-1]
    if raw_clean.endswith("```"):
        raw_clean = raw_clean.rsplit("\n", 1)[0]
    raw_clean = raw_clean.strip()

    start_idx = raw_clean.find("{")
    end_idx = raw_clean.rfind("}")

    if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
        json_str = raw_clean[start_idx : end_idx + 1]
    else:
        json_str = raw_clean

    data = {}
    try:
        data = json.loads(json_str)
    except json.JSONDecodeError:
        categories = ["important_dates", "commercial_requirements", "project_duration", "important_conditions"]
        for cat in categories:
            match = re.search(rf'"{cat}"\s*:\s*\[(.*?)\]', raw_clean, re.DOTALL)
            if match:
                array_body = match.group(1).strip()
                objs = re.findall(r'\{[^{}]*\}', array_body)
                cat_items = []
                for o in objs:
                    try:
                        cat_items.append(json.loads(o))
                    except Exception:
                        pass
                data[cat] = cat_items

    info_dict = {}
    for cat in ["important_dates", "commercial_requirements", "project_duration", "important_conditions"]:
        items_list = data.get(cat, [])
        valid_items = []
        if isinstance(items_list, list):
            for item in items_list:
                if isinstance(item, dict):
                    text_val = str(item.get("text", item.get("statement", ""))).strip()
                    page_val = item.get("page", fallback_page)
                    try:
                        page_val = int(page_val)
                    except (ValueError, TypeError):
                        page_val = fallback_page
                    if text_val:
                        valid_items.append({"text": text_val, "page": page_val})
                elif isinstance(item, str) and item.strip():
                    valid_items.append({"text": item.strip(), "page": fallback_page})
        info_dict[cat] = valid_items

    return PassBInformation.model_validate(info_dict)
