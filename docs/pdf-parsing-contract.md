# PDF parsing contract

The parser prefers the PDF text layer through local `pypdf`; a deterministic fixture marker supports offline tests. OCR, external LLMs and online AI services are disabled.

Outputs distinguish:

- `explicit`: present in extracted text;
- `unconfirmed`: section cannot be reliably extracted;
- `unresolved`: term is not in the canonical or confirmed-alias map;
- `manually_modified`: administrator changed a mapped result.

The parser attempts title, candidate date, core view, market path, risk warning, focus sectors, 66-sector mentions and unmapped terms. Raw text remains linked to structured records. Failure retains the original PDF and enters `parse_failed`; successful parsing still enters `needs_review`. Absence from one report never invalidates an earlier opinion.

Compressed or image-only PDFs that yield no reliable text require later OCR design and stay in human review/failure; this is a known MVP limitation.
