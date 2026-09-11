import pymupdf4llm
from pathlib import Path
from tqdm import tqdm


if __name__ == "__main__":

    corpus_path = Path(__file__).parents[1] / "data/corpus"

    pdf_dir = corpus_path / "pdfs"
    md_dir  = corpus_path / "mds_nl"
    md_dir.mkdir(parents=True, exist_ok=True)

    for pdf in tqdm(pdf_dir.glob("*.pdf"), desc="Processing PDFs"):
        md = pymupdf4llm.to_markdown(str(pdf))
        (md_dir / pdf.with_suffix(".md").name).write_text(md, encoding="utf-8")
        print(f"{pdf.name} -> {len(md):,} chars")

