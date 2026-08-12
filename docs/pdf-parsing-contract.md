# PDF parsing contract

详细的结构证据、质量分类与发布阻断规则见 [PDF解析质量闸门](pdf-parse-quality-gate.md)。V2.3/V2.3.1/V2.4表格不得只依赖连续文本顺序；必须使用页码和字符坐标恢复行列，并防止相邻板块内容串行。

增强解析在既有 pypdf 文本层基础上尝试提取标题、日期、大盘路径、核心观点、风险提示、路径图标题/分组/日期/状态，以及板块解读的历史路径、当期判断、主要依据和观察条件。

表格置信度不足、跨页丢行、合并单元格失败、未知状态或未知板块必须进入人工复核。不得默认 OCR、调用外部 LLM、编造缺失单元格或创建第 67 个板块。复杂表格可使用人工矩阵编辑或受控 JSON/CSV 中间结果，并明确区分自动提取与人工修改。

The parser prefers the PDF text layer through local `pypdf`; a deterministic fixture marker supports offline tests. OCR, external LLMs and online AI services are disabled.

Outputs distinguish:

- `explicit`: present in extracted text;
- `unconfirmed`: section cannot be reliably extracted;
- `unresolved`: term is not in the canonical or confirmed-alias map;
- `manually_modified`: administrator changed a mapped result.

The parser attempts title, candidate date, core view, market path, risk warning, focus sectors, 66-sector mentions and unmapped terms. Raw text remains linked to structured records. Failure retains the original PDF and enters `parse_failed`; successful parsing still enters `needs_review`. Absence from one report never invalidates an earlier opinion.

Compressed or image-only PDFs that yield no reliable text require later OCR design and stay in human review/failure; this is a known MVP limitation.
## Upload-to-Interpretation simplification

Phase 2A-0 accepts an already structured V2.3/V2.3.1/V2.4 live-summary PDF, not raw audio or a raw transcript. A successful upload automatically runs text-layer extraction and deterministic section recovery. Supported variants include merged or split B1 headings, repeated headers and a five-column table continued across pages. Matching tolerates full/half-width spaces, split glyphs and line wrapping and never depends on a fixed page number.

For title, report date, core view, market path, risk notes, sector status, judgement, basis and observation condition, the result stores extraction method, source page/range where available, confidence and manual-modification state. Unknown statuses and ambiguous/unmapped terms become attention items; the parser never creates a 67th sector and never fills missing PDF opinions from general knowledge.

Confirmed canonical names and confirmed aliases are silent successes. Only probable, unmapped and conflict results appear in default review. Complex merged cells may remain for manual review; this is reported rather than disguised as 100% extraction.
## Template routing through V2.9

V2.3, V2.3.1, V2.4, V2.8 and V2.9 are first-class routes. V2.4 and later use PDF text, layout and coordinates without OCR or an external LLM. The historical matrix is isolated from the detailed table; the explicit 当日判断 cell is authoritative and explanatory basis/condition text never reclassifies it. B3 can cover the remaining catalog through the 本场未更新 list. Frozen history is compared through the declared freeze date and only the report-date column is appended. V2.9 may place its frozen-history date near the title, so the declared dated live-summary heading remains the report-date authority.

Ordinary `warning` and `needs_attention` results remain visible and require explicit Admin confirmation, but do not become hard blockers. Only absent/conflicting report date, unreadable body, fewer than 60 reliable history rows, conflicting explicit states, severe cross-row corruption, large unresolved-term sets or unauthorized frozen-history rewrites block publication. Specification backup files are never read by this parser.
