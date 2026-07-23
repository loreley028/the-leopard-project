# PDF upload workflow

1. Admin selects or drops a PDF.
2. Backend rejects unsafe paths, non-PDF MIME, invalid `%PDF-` headers and files above the versioned size limit.
3. Backend computes SHA-256. An existing hash returns the existing report with an explicit duplicate flag.
4. The sanitized storage name is a generated identifier under ignored `var/uploads/`; the client filename is retained only as metadata.
5. Local text-layer parsing extracts explicit fields, candidate date, sector mentions and unmapped terms.
6. Admin reviews raw text and structured fields, resolves terms and explicitly confirms the report date.
7. The report moves to ready and is explicitly published.

Upload time is never the report date. Sunday uploads are not remapped to another trading day. Friday and Saturday have no expected report and no missing alert. Embedded scripts are not executed, links are not followed and content is never sent to a third party.
