import requests
import pandas as pd
from pathlib import Path
import json
import pymupdf
import pymupdf4llm
import re
import hashlib
from tqdm import tqdm
from urllib.parse import urljoin, urlparse
from typing import Any
from datetime import datetime, timezone
from jinja2 import Environment, StrictUndefined
import trafilatura
from bs4 import BeautifulSoup


TRANSLATIONS = {
    "Gemeente": "municipality",
    "Provincie": "province",
    "RES/Warmte regio": "region",
    "Inwoneraantal 2025 CBS": "number_users",
    "Evt. link naar WP": "url",
}


def parse_excel(path: Path | str) -> list[dict[str, Any]]:
    if not isinstance(path, Path):
        path = Path(path)
    df = pd.read_excel(path)
    df = df.rename(columns=TRANSLATIONS)
    return df.to_dict(orient="records")


def validate_pdf(data: bytes) -> tuple[bool, str]:
    if not data.startswith(b"%PDF-"):
        return False, f"not a pdf: {data[:16]!r}"
    if b"%%EOF" not in data[-2048:]:
        return False, "truncated (no trailing %%EOF)"
    try:
        with pymupdf.open(stream=data, filetype="pdf") as doc:
            if doc.page_count == 0:
                return False, "zero pages"
            if doc.is_encrypted and not doc.authenticate(""):
                return False, "encrypted"
    except (pymupdf.FileDataError, pymupdf.EmptyFileError) as e:
        return False, f"unparseable: {e}"
    return True, "ok"


def pdf_to_md(
    data: bytes,
    stem: str,
    path: Path,
    dpi: int = 150,
    ref_prefix: str = "../assets",
) -> str:
    """PDF bytes in, markdown out. Assets written to <path>/<stem>/.

    ref_prefix is how the md file reaches the assets dir (md and assets are
    siblings under processed/, so the default walks up one level).
    """
    assets_dir = Path(path) / stem
    assets_dir.mkdir(exist_ok=True, parents=True)

    with pymupdf.open(stream=data, filetype="pdf") as doc:
        md = pymupdf4llm.to_markdown(
            doc,
            write_images=True,
            image_path=str(assets_dir),
            image_format="png",
            dpi=dpi,
            force_text=False,
            show_progress=False,
        )

    seen: dict[str, str] = {}
    rename: dict[str, str] = {}
    for p in sorted(assets_dir.glob("*.png")):
        sha = hashlib.sha256(p.read_bytes()).hexdigest()[:12]
        target = f"{stem}-{sha}.png"
        if sha in seen:
            p.unlink()                          # byte-identical duplicate
        elif p.name != target:
            p.replace(assets_dir / target)
            seen[sha] = target
        else:
            seen[sha] = target
        rename[p.name] = target

    md = re.sub(
        r"!\[\]\((?:.*?[/\\])?([^/\\]+\.png)\)",
        lambda m: f"![]({ref_prefix}/{stem}/{rename.get(m.group(1), m.group(1))})",
        md,
    )

    # drop boilerplate images referenced on most of the document
    refs = re.findall(rf"!\[\]\({re.escape(ref_prefix)}/{re.escape(stem)}/([^)]+)\)", md)
    total = len(refs) or 1
    for name in {n for n in set(refs) if refs.count(n) / total > 0.5}:
        md = re.sub(
            rf"\n*!\[\]\({re.escape(ref_prefix)}/{re.escape(stem)}/{re.escape(name)}\)\n*",
            "\n\n",
            md,
        )
        (assets_dir / name).unlink(missing_ok=True)

    return md


def normalize_url(url: str, base: str | None = None) -> str:
    url = (url or "").strip()
    if not url:
        raise ValueError("empty url")
    if url.startswith("//"):
        return "https:" + url
    if urlparse(url).scheme:
        return url
    if base:
        return urljoin(base, url)          # handles "x.pdf", "/x.pdf", "../x.pdf"
    if re.match(r"^[\w-]+(\.[\w-]+)+(/|$|\?)", url):
        return "https://" + url            # looks like a bare host
    raise ValueError(f"relative url with no base: {url!r}")



UA = "Mozilla/5.0 (compatible; deltares-heat-transition-research/0.1)"

_JUNK = re.compile(r"cookie|privacy|disclaimer|toegankelijk|proclaimer|sitemap|colofon", re.I)
_HINT = re.compile(r"download|bekijk|lees|open|pdf|document|bijlage", re.I)


def find_pdf_link(html: str, base_url: str) -> str | None:
    """Pick the most plausible PDF link on a landing page, or None."""
    soup = BeautifulSoup(html, "html.parser")
    title = (soup.title.get_text() if soup.title else "").lower()
    title_words = set(re.findall(r"\w{4,}", title))

    best, best_score = None, 0.0
    for a in soup.find_all("a", href=True):
        href, text = a["href"], a.get_text(" ", strip=True)
        if ".pdf" not in href.lower() and not _HINT.search(text):
            continue
        if _JUNK.search(href) or _JUNK.search(text):
            continue

        score = 1.0 if ".pdf" in href.lower() else 0.3
        if _HINT.search(text):
            score += 0.5
        words = set(re.findall(r"\w{4,}", text.lower()))
        if title_words and words:
            score += 2.0 * len(words & title_words) / len(title_words)
        if a.find_parent(["footer", "nav"]):
            score -= 1.0
        if a.find_parent(["main", "article"]):
            score += 0.5

        if score > best_score:
            best, best_score = href, score

    return normalize_url(best, base_url) if best and best_score >= 1.0 else None


def resolve(url: str, session: requests.Session) -> tuple[str, bytes, str]:
    """Return (kind, payload, final_url); kind is 'pdf' or 'html'."""
    r = session.get(url, timeout=60, headers={"User-Agent": UA})
    r.raise_for_status()

    if r.content.startswith(b"%PDF-"):
        return "pdf", r.content, r.url

    pdf_url = find_pdf_link(r.text, r.url)
    if pdf_url:
        pr = session.get(pdf_url, timeout=60, headers={"User-Agent": UA})
        if pr.ok and pr.content.startswith(b"%PDF-"):
            return "pdf", pr.content, pr.url

    return "html", r.content, r.url


def html_to_md(data: bytes, url: str) -> str:
    return trafilatura.extract(
        data, url=url, output_format="markdown",
        include_tables=True, include_links=False,
    ) or ""


def _clean(value) -> str:
    """Blank for missing values; drop pandas' float formatting on whole numbers."""
    if value is None or value != value:  # None or NaN
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)

def render_md(row: dict, text: str) -> str:
    """Render one document to markdown: id, metadata block, then the text."""
    return MD_TEMPLATE.render(
        id=row.get("id"),
        municipality=row.get("municipality"),
        province=row.get("province"),
        region=row.get("region"),
        number_users=row.get("number_users"),
        url=row.get("url"),
        text=text,
    )


_env = Environment(autoescape=False, undefined=StrictUndefined, keep_trailing_newline=True)
_env.filters["clean"] = _clean
MD_TEMPLATE = _env.from_string(
"""{{ id | clean }}

MUNICIPALITY: {{ municipality | clean }}

PROVINCE: {{ province | clean }}

REGION: {{ region | clean }}

NUMBER OF USERS: {{ number_users | clean }}

URL: {{ url | clean }}

TEXT:

{{ text }}
"""
)

def download_pdfs(path: Path | str, out_path: Path | str, to_md: bool = False, restart: bool = False):

    if not isinstance(out_path, Path):
        out_path = Path(out_path)

    out_pdf_path = out_path / "corpus"
    out_pdf_path.mkdir(exist_ok=True, parents=True)

    if to_md:
        out_md_path = out_path / "processed/md"
        out_md_path.mkdir(exist_ok=True, parents=True)
        out_assets_path = out_path / "processed/assets"
        out_assets_path.mkdir(exist_ok=True, parents=True)

    data = parse_excel(path)

    session = requests.Session()

    corpus_ids = [doc.stem for doc in out_pdf_path.iterdir()]

    for i, row in enumerate(tqdm(data)):
        row["id"] = str(i+1)
        row["fetched_at"] = datetime.now(timezone.utc).isoformat()

        if row["id"] in corpus_ids and not restart:
            continue

        raw = row.get("url")
        if not isinstance(raw, str) or not raw.strip():
            row.update(ok=False, reason="no url in sheet", source_type=None)
            continue

        try:
            url = normalize_url(raw)
            kind, payload, final_url = resolve(url, session)
            row["source_type"] = kind
            row["final_url"] = final_url

            if kind == "pdf":
                ok, reason = validate_pdf(payload)
                row.update(ok=ok, reason=reason)
                if not ok:
                    continue
                (out_pdf_path / f"{row['id']}.pdf").write_bytes(payload)
            else:
                row.update(ok=True, reason="html page (no pdf found)")

            if to_md:
                if kind == "pdf":
                    md = pdf_to_md(payload, row["id"], out_assets_path)
                else:
                    md = html_to_md(payload, final_url)

                if len(md.strip()) < 200:
                    row.update(ok=False, reason=f"near-empty extraction ({len(md.strip())} chars)")
                    continue

                md = render_md(row, md)

                md_file = out_md_path / f"{row['id']}.md"
                md_file.write_text(md, encoding="utf-8")

                row["md_path"] = str(md_file.relative_to(out_path))
                row["chars"] = len(md)
                data[i] = row

        except Exception as e:
            row.update(ok=False, reason=repr(e))

    with open(out_path/"data.jsonl", "w", encoding="utf-8") as f:
        for row in data:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


if __name__ == "__main__":

    pass