# ============================================================
# L09: Unstructured.io and Real-World Document Processing
# ============================================================
# WHAT: How to actually extract usable text from the messy document
#       formats RAG systems have to deal with in practice — PDFs (with
#       multi-column layouts, embedded tables, scanned images), Word
#       docs, HTML, PowerPoint — using Unstructured.io's layout-aware
#       parsing, plus table extraction and OCR fallback for scanned content.
# WHY: Every prior lesson assumed clean, already-extracted text. In
#      reality, a huge fraction of RAG project time goes into just
#      getting USABLE text out of real documents — a badly-parsed PDF
#      (garbled column order, a table flattened into meaningless text)
#      poisons every downstream stage (chunking, embedding, retrieval)
#      no matter how good those later stages are.
# LEVEL: Intermediate (Phase 2 of 7)
# ============================================================

"""
CONCEPT OVERVIEW:
Naive PDF text extraction (e.g. a basic `pdftotext`-style tool) reads
text in RAW POSITIONAL order, which breaks badly on multi-column layouts
(interleaving text from two side-by-side columns into a nonsensical
sequence) and completely loses TABLE structure (a table's rows/columns
become a flat, meaningless stream of numbers and words with no
indication of which value belonged to which row/column header).

UNSTRUCTURED.IO addresses this with LAYOUT-AWARE parsing — using a
document layout detection model to identify structural ELEMENTS (titles,
narrative text, list items, tables, images) and their reading order
BEFORE extracting text, rather than a naive linear scan. This produces a
list of typed "Element" objects (Title, NarrativeText, Table,
ListItem, etc.) instead of one undifferentiated text blob — letting
downstream chunking (L04-L08) respect actual document structure (e.g.
chunk boundaries aligned with detected titles/sections) rather than
guessing from raw character positions.

TABLE EXTRACTION specifically preserves ROW/COLUMN structure (often as
HTML or a structured representation) rather than flattening a table into
plain text — critical because a flattened table (numbers and headers
jumbled together with no structural markers) is frequently WORSE than
having no table data at all, since an LLM reading the flattened mess can
confidently generate a wrong answer that LOOKS grounded in the source.

OCR (Optical Character Recognition) FALLBACK handles scanned documents
(images of text, with no underlying selectable text layer at all) —
Unstructured automatically detects when a PDF page has no extractable
text layer and falls back to OCR (via Tesseract or a similar engine) to
extract text from the rendered image instead.

PRODUCTION USE CASE:
A financial-reports RAG system ingests 10-K filings containing dense
multi-column text, embedded financial tables, and occasionally scanned
signature pages — Unstructured's layout detection correctly separates
narrative sections from tables (feeding tables through a distinct,
structure-preserving extraction path), and its OCR fallback handles the
scanned pages without a manual, per-document special case.

COMMON MISTAKES:
- Using a naive PDF-to-text extraction on multi-column academic papers
  or financial reports and being surprised when retrieval quality is
  poor — the root cause is often GARBLED TEXT from column interleaving,
  not a problem with the embedding model or chunking strategy at all;
  debugging retrieval quality should always start by inspecting the
  actual extracted text.
- Flattening tables into plain text without preserving row/column
  structure — an LLM given a flattened table can hallucinate incorrect
  associations between values and their actual row/column headers,
  producing confidently wrong, table-derived answers.
- Assuming every PDF has a text layer and skipping OCR entirely — a
  meaningful fraction of real-world documents (scanned contracts, old
  reports, faxed documents) have NO extractable text layer at all
  without OCR, and silently getting empty/near-empty extraction results
  for those documents is a common, easy-to-miss failure mode.
"""

import textwrap


# ------------------------------------------------------------------
# 1. Layout-aware parsing — typed elements instead of a raw text blob
# ------------------------------------------------------------------
UNSTRUCTURED_BASIC_EXAMPLE = textwrap.dedent("""\
    from unstructured.partition.auto import partition

    # `partition` auto-detects the file type and uses the appropriate
    # layout-aware parser (PDF, DOCX, HTML, PPTX, etc.) — returning a
    # list of TYPED elements, not one undifferentiated string.
    elements = partition(filename="quarterly_report.pdf")

    for el in elements[:5]:
        print(f"{type(el).__name__}: {str(el)[:80]}")
    # Example output:
    #   Title: Q3 2026 Financial Results
    #   NarrativeText: Revenue increased 12% year-over-year...
    #   Table: <preserves row/column structure, see below>
    #   ListItem: Key highlights include...
""")

# ------------------------------------------------------------------
# 2. Structure-aware chunking, built on typed elements
# ------------------------------------------------------------------
CHUNK_BY_TITLE_EXAMPLE = textwrap.dedent("""\
    from unstructured.chunking.title import chunk_by_title

    # Instead of L04's character-count chunking (which has no idea where
    # a section actually begins/ends), chunk_by_title uses the DETECTED
    # Title elements as natural chunk boundaries — a chunk never
    # straddles two different document sections, because the layout
    # model already told us exactly where those sections start.
    chunks = chunk_by_title(elements, max_characters=1000, combine_text_under_n_chars=200)
""")

# ------------------------------------------------------------------
# 3. Table extraction — preserving structure, not flattening
# ------------------------------------------------------------------
TABLE_EXTRACTION_EXAMPLE = textwrap.dedent("""\
    from unstructured.partition.pdf import partition_pdf

    elements = partition_pdf(
        filename="quarterly_report.pdf",
        infer_table_structure=True,   # extract tables as structured HTML,
                                        # not flattened text
    )

    tables = [el for el in elements if el.category == "Table"]
    for table in tables:
        print(table.metadata.text_as_html)
        # <table><tr><th>Quarter</th><th>Revenue</th></tr>
        #        <tr><td>Q1</td><td>$4.2M</td></tr>...</table>
        #
        # Feeding THIS structured HTML representation to an LLM (rather
        # than a flattened "Quarter Revenue Q1 $4.2M Q2 $4.8M..." string)
        # lets the model correctly associate each value with its actual
        # row/column header — a meaningful, measurable accuracy
        # difference on table-heavy documents.
""")

# ------------------------------------------------------------------
# 4. OCR fallback for scanned documents
# ------------------------------------------------------------------
OCR_FALLBACK_NOTE = textwrap.dedent("""\
    elements = partition_pdf(
        filename="scanned_contract.pdf",
        strategy="hi_res",   # triggers layout detection + OCR fallback
                               # for pages with no extractable text layer
    )

    # Unstructured automatically detects pages with NO underlying text
    # layer (a pure image of text, common in scanned/faxed documents)
    # and routes them through OCR (Tesseract by default) instead of
    # returning empty/garbage extraction — this must be EXPLICITLY
    # enabled via the "hi_res" strategy; the faster "fast" strategy
    # skips OCR entirely and will silently miss scanned-page content.
""")

STRATEGY_COMPARISON = {
    "fast": "Quick text-layer extraction only, NO OCR fallback — fast, "
        "but silently misses scanned/image-only pages entirely.",
    "hi_res": "Full layout detection model + OCR fallback for pages "
        "without a text layer — slower, but handles scanned documents "
        "and produces more accurate element typing/ordering.",
    "ocr_only": "Forces OCR on every page regardless of whether a text "
        "layer exists — useful when a document's embedded text layer is "
        "known to be unreliable (e.g. a badly-generated PDF with "
        "incorrect character encoding).",
}


if __name__ == "__main__":
    print(UNSTRUCTURED_BASIC_EXAMPLE)
    print(CHUNK_BY_TITLE_EXAMPLE)
    print(TABLE_EXTRACTION_EXAMPLE)
    print(OCR_FALLBACK_NOTE)
    print("=== Parsing strategy comparison ===")
    for strategy, note in STRATEGY_COMPARISON.items():
        print(f"{strategy}: {note}\n")

"""
PRODUCTION CONTEXT EXAMPLE:
A due-diligence RAG tool ingesting hundreds of scanned legal contracts
(many faxed decades ago, with no text layer at all) initially used the
"fast" extraction strategy and silently returned near-empty results for
roughly a third of the corpus — switching to "hi_res" with OCR fallback
recovered that missing third, and preserving detected table structure
in the financial exhibits attached to several contracts fixed a separate
class of retrieval errors where the LLM had been confidently
misattributing dollar amounts to the wrong contract clause after reading
a flattened table.
"""
