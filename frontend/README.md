# The Leopard Project Web MVP

React + TypeScript + Vite frontend for the Phase 2A-0 research MVP. Public read-only pages and the separate Admin management area consume only `/api/v1/`.

`public/robots.txt` and the HTML `noindex,nofollow` meta directive reduce search-engine discovery only. They are not an access control mechanism: every mutation remains protected by server-side Admin authorization.

Selected primitives use the exact `animal-island-ui` 1.3.0 npm dependency through `src/components/island/`. The package stylesheet is imported once in `src/main.tsx`; business pages do not import the library directly. Button, Card, Tag, Modal, Select and single-line Input are adapted. Original business components remain for the shell, navigation, upload, timeline, status, empty state, captioned tables and multiline fields. The approved scope is private and noncommercial; no third-party source tree or official game asset is copied into this repository.
