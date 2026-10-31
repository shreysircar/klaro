"""
Human-Readable Executive Summary Renderer for Klaro.

Transforms machine-readable executive summary JSON (e.g., executive_summary_v1.json)
into clean Markdown (.md) and self-contained HTML (.html) reports without modifying content.
"""

import html
import json
import sys
from pathlib import Path
from typing import Dict, List, Any, Union


LOCALES_DIR = Path(__file__).resolve().parent / "locales"


def load_locale(language: str) -> dict[str, Any]:
    """Load report labels for the requested language."""
    if not language or not language.strip():
        raise ValueError("Language cannot be empty.")

    locale_path = LOCALES_DIR / f"{language}.json"

    if not locale_path.is_file():
        available = sorted(
            path.stem for path in LOCALES_DIR.glob("*.json")
        )
        raise ValueError(
            f"Unsupported language '{language}'. "
            f"Available languages: {', '.join(available)}"
        )

    with locale_path.open("r", encoding="utf-8-sig") as file:
        locale = json.load(file)

    required_keys = {
        "report_title",
        "report_subtitle",
        "no_information",
        "page",
        "pages",
        "sections",
    }

    missing = required_keys - locale.keys()
    if missing:
        raise ValueError(
            f"Locale file '{locale_path}' is missing: "
            f"{', '.join(sorted(missing))}"
        )

    return locale


def format_page_suffix_md(pages: Any, locale: dict[str, Any]) -> str:
    if isinstance(pages, int):
        pages = [pages]
    elif not isinstance(pages, list):
        pages = []

    clean_pages = [p for p in pages if isinstance(p, int)]
    if not clean_pages:
        return ""

    if len(clean_pages) == 1:
        return f" *({locale['page']} {clean_pages[0]})*"

    pages_str = ", ".join(str(p) for p in sorted(clean_pages))
    return f" *({locale['pages']} {pages_str})*"



def format_page_suffix_html(
    pages: Any,
    locale: dict[str, Any],
) -> str:
    if isinstance(pages, int):
        pages = [pages]
    elif not isinstance(pages, list):
        pages = []

    clean_pages = [p for p in pages if isinstance(p, int)]
    if not clean_pages:
        return ""

    if len(clean_pages) == 1:
        return (
            f' <span class="page-tag">'
            f'{locale["page"]} {clean_pages[0]}</span>'
        )

    pages_str = ", ".join(str(p) for p in sorted(clean_pages))
    return (
        f' <span class="page-tag">'
        f'{locale["pages"]} {pages_str}</span>'
    )

def extract_item_info(item: Any) -> tuple[str, Any]:
    """Extract text and page information from a string or dictionary."""
    if isinstance(item, str):
        return item.strip(), []
    elif isinstance(item, dict):
        text = str(item.get("text", "")).strip()
        pages = item.get("pages", item.get("page", []))
        return text, pages
    return str(item).strip(), []

def render_markdown(
    data: Dict[str, Any],
    language: str = "en",
) -> str:
    locale = load_locale(language)
    lines = [f"# {locale['report_title']}\n"]

    for key, title in locale["sections"].items():

        lines.append(f"## {title}\n")
        val = data.get(key)

        if not val:
            lines.append(f"_{locale['no_information']}_\n")
            continue

        if key == "issuing_organization" and isinstance(val, str):
            suffix = format_page_suffix_md(pages, locale)
        elif key == "overview":
            if isinstance(val, str):
                lines.append(f"{val}\n")
            elif isinstance(val, dict):
                text, pages = extract_item_info(val)
                suffix = format_page_suffix_md(pages, locale)
                lines.append(
                    f"{text}{suffix}\n"
                    if text
                    else f"_{locale['no_information']}_\n"
                )
        elif isinstance(val, list):
            if len(val) == 0:
                lines.append(f"_{locale['no_information']}_\n")
            else:
                for item in val:
                    text, pages = extract_item_info(item)
                    if text:
                        suffix = format_page_suffix_md(pages, locale)
                        lines.append(f"- {text}{suffix}")
                lines.append("")  # Blank newline after list
        elif isinstance(val, str):
            lines.append(f"{val}\n")
        else:
            lines.append(f"_{locale['no_information']}_\n")

    return "\n".join(lines).strip() + "\n"


def render_html(
    data: Dict[str, Any],
    language: str = "en",
) -> str:
    locale = load_locale(language)
    sections_html = []
    for key, title in locale["sections"].items():
        val = data.get(key)
        sec_title = html.escape(title)

        if not val:
            content_html =f'<p class="empty-notice"><em>{html.escape(locale["no_information"])}</em></p>'
        elif key == "issuing_organization" and isinstance(val, str):
            content_html = (
                f'<p>{html.escape(val)}'
                f'{format_page_suffix_html(data.get("issuing_organization_pages", []), locale)}'
                f'</p>'
            )
        elif key == "overview":
            if isinstance(val, str):
                content_html = f'<p>{html.escape(val)}</p>'
            elif isinstance(val, dict):
                text, pages = extract_item_info(val)
                if text:
                    suffix = format_page_suffix_html(pages, locale)
                    content_html = f'<p>{html.escape(text)}{suffix}</p>'
                else:
                    content_html = (
                        f'<p class="empty-notice"><em>{html.escape(locale["no_information"])}</em></p>'
                    )
        elif isinstance(val, list):
            if len(val) == 0:
                content_html = f'<p class="empty-notice"><em>{html.escape(locale["no_information"])}</em></p>'
            else:
                items_html = []
                for item in val:
                    text, pages = extract_item_info(item)
                    if text:
                        suffix = format_page_suffix_html(pages, locale)
                        items_html.append(
                            f'  <li>{html.escape(text)}{suffix}</li>'
                        )

                if items_html:
                    content_html = (
                        '<ul>\n'
                        + '\n'.join(items_html)
                        + '\n</ul>'
                    )
                else:
                    content_html = (
                        f'<p class="empty-notice"><em>{html.escape(locale["no_information"])}</em></p>'
                    )
        elif isinstance(val, str):
            content_html = f'<p>{html.escape(val)}</p>'
        else:
            content_html = f'<p class="empty-notice"><em>{html.escape(locale["no_information"])}</em></p>'

        sections_html.append(
            f'''  <section class="summary-section">
    <h2>{sec_title}</h2>
    {content_html}
  </section>'''
        )

    body_content = "\n".join(sections_html)

    html_document = f'''<!DOCTYPE html>
<html lang="{language}">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Klaro — {html.escape(locale["report_title"])}</title>
  <style>
    :root {{
      --font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      --bg-color: #f8fafc;
      --card-bg: #ffffff;
      --text-color: #1e293b;
      --heading-color: #0f172a;
      --accent-color: #2563eb;
      --muted-color: #64748b;
      --border-color: #e2e8f0;
      --tag-bg: #eff6ff;
      --tag-text: #1d4ed8;
      --tag-border: #bfdbfe;
    }}
    body {{
      font-family: var(--font-family);
      background-color: var(--bg-color);
      color: var(--text-color);
      margin: 0;
      padding: 2rem 1rem;
      line-height: 1.6;
    }}
    .container {{
      max-width: 900px;
      margin: 0 auto;
      background: var(--card-bg);
      border: 1px solid var(--border-color);
      border-radius: 12px;
      padding: 2.5rem 3rem;
      box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05),
                  0 2px 4px -1px rgba(0, 0, 0, 0.03);
    }}
    header {{
      border-bottom: 2px solid var(--border-color);
      padding-bottom: 1.5rem;
      margin-bottom: 2rem;
    }}
    h1 {{
      color: var(--heading-color);
      font-size: 2.25rem;
      margin: 0 0 0.5rem 0;
      font-weight: 700;
      letter-spacing: -0.025em;
    }}
    .subtitle {{
      color: var(--muted-color);
      font-size: 0.95rem;
      margin: 0;
    }}
    .summary-section {{
      margin-bottom: 2rem;
    }}
    h2 {{
      color: var(--accent-color);
      font-size: 1.35rem;
      margin: 0 0 0.75rem 0;
      padding-bottom: 0.35rem;
      border-bottom: 1px solid var(--border-color);
      font-weight: 600;
    }}
    p {{
      margin: 0 0 1rem 0;
      font-size: 1rem;
    }}
    ul {{
      margin: 0 0 1rem 0;
      padding-left: 1.5rem;
    }}
    li {{
      margin-bottom: 0.6rem;
      font-size: 0.98rem;
    }}
    .empty-notice {{
      color: var(--muted-color);
      font-style: italic;
    }}
    .page-tag {{
      display: inline-block;
      font-size: 0.78rem;
      font-weight: 600;
      background-color: var(--tag-bg);
      color: var(--tag-text);
      border: 1px solid var(--tag-border);
      border-radius: 4px;
      padding: 0.1rem 0.4rem;
      margin-left: 0.4rem;
      vertical-align: middle;
      white-space: nowrap;
    }}
    @media (max-width: 640px) {{
      .container {{
        padding: 1.5rem;
      }}
      h1 {{
        font-size: 1.75rem;
      }}
    }}
  </style>
</head>
<body>
  <div class="container">
    <header>
      <h1>{html.escape(locale["report_title"])}</h1>
      <p class="subtitle">{html.escape(locale["report_subtitle"])}</p> 
    </header>
    <main>
{body_content}
    </main>
  </div>
</body>
</html>
'''
    return html_document


def render_summary_files(
    json_path: Path,
    output_dir: Path | None = None,
    language: str = "en",
) -> tuple[Path, Path]:
    if not json_path.exists():
        raise FileNotFoundError(
            f"Input JSON file not found: {json_path}"
        )

    with open(json_path, "r", encoding="utf-8-sig") as f:
        data = json.load(f)

    md_content = render_markdown(data, language=language)
    html_content = render_html(data, language=language)

    if output_dir is None:
        output_dir = json_path.parent

    output_dir.mkdir(parents=True, exist_ok=True)

    base_name = json_path.stem
    md_path = output_dir / f"{base_name}.md"
    html_path = output_dir / f"{base_name}.html"

    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md_content)

    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    return md_path, html_path


if __name__ == "__main__":
    if len(sys.argv) > 1:
        target_path = Path(sys.argv[1])
    else:
        target_path = Path(
            "data/evaluation/executive_summary_v1.json"
        )

    try:
        out_md, out_html = render_summary_files(target_path)

        print("=" * 70)
        print("EXECUTIVE SUMMARY RENDERED SUCCESSFULLY")
        print(f"Input JSON: {target_path}")
        print(f"Markdown:   {out_md}")
        print(f"HTML:       {out_html}")
        print("=" * 70)

    except Exception as e:
        print(
            f"Error rendering summary: {e}",
            file=sys.stderr,
        )
        sys.exit(1)