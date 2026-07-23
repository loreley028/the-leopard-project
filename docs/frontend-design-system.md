# Island research design system

The design language is an “island research notebook”: warm sand background, cream cards, leaf and ocean surfaces, bark text, soft borders and restrained depth. Phase 2A-0 integrates selected `animal-island-ui` 1.3.0 components under CC BY-NC 4.0 while preserving the project's research-first information architecture.

Tokens live in `frontend/src/styles/tokens.css`; global responsive/accessibility rules live in `global.css`. The single third-party stylesheet import lives in `main.tsx`. Components under `components/island/` remain the application boundary: Button, Card, Tag, Modal, Select and single-line Input adapt the library; Shell, Header, Nav, captioned Table, textarea, StatusBadge, EmptyState, UploadZone and Timeline retain original business implementations.

Content hierarchy dominates decoration. Status badges include text and a symbol, so positive/negative/proxy/short-history/unsupported/intraday states never depend on red/green alone. Controls retain visible focus, upload is keyboard operable, layouts collapse on mobile and `prefers-reduced-motion` suppresses motion.

The captioned table is intentionally not replaced because the library Table API has no caption or table-level accessible-name prop. Multiline fields retain a native textarea because the library exports only a single-line Input. Desktop composition targets approximately 1440px while remaining usable on narrow mobile screens. Library motion is constrained by the existing `prefers-reduced-motion` rule.
