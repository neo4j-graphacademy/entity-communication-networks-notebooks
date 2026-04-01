# Entity Communication Networks

Companion notebooks for the [Neo4j GraphAcademy](https://graphacademy.neo4j.com/) course: **Entity Communication Networks**.

Extract text from 4,911 Enron email PDFs, parse headers into structured records, and import a communication network into Neo4j.

This is the first of three courses:
1. **Entity Communication Networks** (this course) — extraction, parsing, and import
2. **Entity Extraction for Communication Networks** — entity and topic extraction from email body text
3. **Entity Resolution for Communication Networks** — deduplication and identity resolution

## Notebooks

### Module 1: Extraction
| # | Notebook | What it covers |
|---|----------|---------------|
| 1.1 | `1.1_extracting_with_pymupdf.ipynb` | PyMuPDF text extraction, PDF classification |
| 1.2 | `1.2_extracting_with_ocr.ipynb` | Tesseract OCR, re-OCR on garbled text layers |
| 1.3 | `1.3_extracting_with_docling.ipynb` | Combined extraction with Docling |
| 1.4 | `1.4_extracting_with_vision.ipynb` | Vision LLM extraction, corrections approach |
| 1.5 | `1.5_full_extraction.ipynb` | Full corpus extraction pipeline |

### Module 2: Parsing & Import
| # | Notebook | What it covers |
|---|----------|---------------|
| 2.1 | `2.1_whats_in_your_documents.ipynb` | Document investigation |
| 2.2 | `2.2_layout_aware_extraction.ipynb` | Docling doc.texts, DocumentExtractor |
| 2.3 | `2.3_parsing_libraries.ipynb` | email.parser, RFC reconstruction |
| 2.4 | `2.4_rule_based_parsing.ipynb` | Regex, templates, greedy vs strict |
| 2.5 | `2.5_ml_based_parsing.ipynb` | spaCy NER, GLiNER2 |
| 2.6 | `2.6_parsing_with_llm.ipynb` | LLM parsing, Batch API |
| 2.7 | `2.7_hybrid_pipeline.ipynb` | Templates + NER + LLM pipeline, CSV export |
| 2.8 | `2.8_cleaning_and_normalization.ipynb` | Unicode, artifact stripping, OCR domain correction |
| 2.9 | `2.9_import_to_neo4j.ipynb` | Neo4j Aura Free, constraints, MERGE import |

## Setup

**Codespace (recommended):** Open in GitHub Codespaces — the `.devcontainer` configures everything.

**Local:**
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m spacy download en_core_web_sm
```

Copy `env.template` to `.env` and add your credentials:
```
NEO4J_URI=neo4j+s://xxxxxxxx.databases.neo4j.io
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=your-password
OPENAI_API_KEY=sk-...
```

## Data

- `enron_pdfs/` — 4,911 Enron email PDFs
- `data/extracted_text/` — pre-extracted text files (or regenerate with notebook 1.5)
- `data/ner_training/` — NER annotations and training configs
- `helpers/enron_templates.py` — template-based email header parser

## License

The Enron email corpus is public domain. Course materials are provided for educational use.
