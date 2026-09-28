"""Extract a deterministic audit inventory from the designated final manuscript.

The script is read-only with respect to the manuscript.  It records paragraphs,
tables, captions, references, embedded media hashes, and key OOXML review state
so later numerical and reference checks can point to stable source locations.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import zipfile
from pathlib import Path

from docx import Document
from docx.document import Document as DocumentObject
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph


REFERENCE_HEADING = re.compile(r"^references\s*$", re.IGNORECASE)
NUMBERED_REFERENCE = re.compile(r"^\s*(\d+)\.\s+(.+)$")
CAPTION = re.compile(r"^(?:Figure|Table|Supplementary\s+(?:Figure|Table))\s+[A-Z]?\d+\b", re.IGNORECASE)
BRACKET_CITATION = re.compile(r"\[(\d+(?:\s*[-–,]\s*\d+)*)\]")


def iter_block_items(parent: DocumentObject):
    for child in parent.element.body.iterchildren():
        if child.tag == qn("w:p"):
            yield Paragraph(child, parent)
        elif child.tag == qn("w:tbl"):
            yield Table(child, parent)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def extract(docx_path: Path) -> dict:
    document = Document(docx_path)
    blocks: list[dict] = []
    paragraphs: list[dict] = []
    tables: list[dict] = []
    captions: list[dict] = []
    references: list[dict] = []
    citations: list[dict] = []
    in_references = False

    for block_index, block in enumerate(iter_block_items(document), start=1):
        if isinstance(block, Paragraph):
            text = block.text.strip()
            item = {
                "block": block_index,
                "kind": "paragraph",
                "paragraph": len(paragraphs) + 1,
                "style": block.style.name if block.style else "",
                "text": text,
            }
            paragraphs.append(item)
            blocks.append(item)
            if REFERENCE_HEADING.match(text):
                in_references = True
                continue
            match = NUMBERED_REFERENCE.match(text) if in_references else None
            if match:
                references.append(
                    {
                        "number": int(match.group(1)),
                        "text": match.group(2).strip(),
                        "paragraph": item["paragraph"],
                        "block": block_index,
                    }
                )
            if not in_references:
                for cite in BRACKET_CITATION.finditer(text):
                    citations.append(
                        {
                            "raw": cite.group(0),
                            "numbers": cite.group(1),
                            "paragraph": item["paragraph"],
                            "context": text,
                        }
                    )
            if CAPTION.match(text):
                captions.append(item)
        else:
            rows = [[cell.text.strip() for cell in row.cells] for row in block.rows]
            item = {
                "block": block_index,
                "kind": "table",
                "table": len(tables) + 1,
                "rows": rows,
                "n_rows": len(rows),
                "n_columns": max((len(row) for row in rows), default=0),
            }
            tables.append(item)
            blocks.append(item)

    with zipfile.ZipFile(docx_path) as archive:
        names = set(archive.namelist())
        media = []
        for name in sorted(n for n in names if n.startswith("word/media/")):
            data = archive.read(name)
            media.append({"name": name, "bytes": len(data), "sha256": sha256(data)})
        document_xml = archive.read("word/document.xml")
        comments_count = 0
        if "word/comments.xml" in names:
            comments_count = archive.read("word/comments.xml").count(b"<w:comment ")
        tracked_insertions = len(re.findall(br"<w:ins(?:\s|>)", document_xml))
        tracked_deletions = len(re.findall(br"<w:del(?:\s|>)", document_xml))
        alt_texts = []
        for element in document.element.body.iter():
            if element.tag == qn("wp:docPr"):
                alt_texts.append(
                    {
                        "name": element.get("name", ""),
                        "title": element.get("title", ""),
                        "description": element.get("descr", ""),
                    }
                )

    props = document.core_properties
    return {
        "file": str(docx_path.resolve()),
        "file_bytes": docx_path.stat().st_size,
        "file_sha256": sha256(docx_path.read_bytes()),
        "core_properties": {
            "title": props.title or "",
            "subject": props.subject or "",
            "author": props.author or "",
            "keywords": props.keywords or "",
            "last_modified_by": props.last_modified_by or "",
        },
        "counts": {
            "paragraphs": len(paragraphs),
            "tables": len(tables),
            "captions": len(captions),
            "references": len(references),
            "bracket_citation_occurrences": len(citations),
            "embedded_media": len(media),
            "comments": comments_count,
            "tracked_insertions": tracked_insertions,
            "tracked_deletions": tracked_deletions,
        },
        "blocks": blocks,
        "paragraphs": paragraphs,
        "tables": tables,
        "captions": captions,
        "references": references,
        "citations": citations,
        "media": media,
        "image_alt_text": alt_texts,
    }


def write_markdown(report: dict, path: Path) -> None:
    counts = report["counts"]
    lines = [
        "# Final manuscript extraction audit",
        "",
        f"- File: `{report['file']}`",
        f"- SHA-256: `{report['file_sha256']}`",
        f"- Paragraphs: {counts['paragraphs']}",
        f"- Tables: {counts['tables']}",
        f"- Captions: {counts['captions']}",
        f"- References: {counts['references']}",
        f"- Embedded media: {counts['embedded_media']}",
        f"- Comments: {counts['comments']}",
        f"- Tracked insertions/deletions: {counts['tracked_insertions']}/{counts['tracked_deletions']}",
        "",
        "## Captions",
        "",
    ]
    lines.extend(f"- P{item['paragraph']}: {item['text']}" for item in report["captions"])
    lines.extend(["", "## References", ""])
    lines.extend(f"{item['number']}. {item['text']}" for item in report["references"])
    lines.extend(["", "## Tables", ""])
    for table in report["tables"]:
        lines.append(f"### Table object {table['table']} ({table['n_rows']} x {table['n_columns']})")
        lines.append("")
        for row in table["rows"]:
            lines.append(" | ".join(cell.replace("\n", " / ") for cell in row))
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("docx", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    report = extract(args.docx)
    json_path = args.output_dir / "final_manuscript_inventory.json"
    md_path = args.output_dir / "final_manuscript_inventory.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    write_markdown(report, md_path)
    print(json_path)
    print(md_path)


if __name__ == "__main__":
    main()
