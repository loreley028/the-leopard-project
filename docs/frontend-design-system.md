# Island research design system

信息优先于装饰。历史矩阵使用配置化实心状态色、高密度表格和内部滚动；板块研究使用紧凑路径块及0轴涨跌柱；报告详细行可展开最近观点、行情图和PDF来源。390px视口不得产生整页横向溢出，键盘可操作所有矩阵单元格，并保留reduced-motion规则。

增强页面继续使用 `animal-island-ui@1.3.0` 并通过 Island 适配层组合。视觉保留温暖岛屿研究风，但首页减少装饰占比，直播观点、路径状态与客观数据成为视觉主体，不改成传统券商行情终端。

历史矩阵具有 sticky 日期/板块列、文字状态、caption、键盘焦点及移动端折叠替代视图。涨跌不只依赖红绿；目标断点为 1440px 桌面与 390px 移动端，页面无横向溢出，矩阵内部可滚动。

The design language is an “island research notebook”: warm sand background, cream cards, leaf and ocean surfaces, bark text, soft borders and restrained depth. Phase 2A-0 integrates selected `animal-island-ui` 1.3.0 components under CC BY-NC 4.0 while preserving the project's research-first information architecture.

Tokens live in `frontend/src/styles/tokens.css`; global responsive/accessibility rules live in `global.css`. The single third-party stylesheet import lives in `main.tsx`. Components under `components/island/` remain the application boundary: Button, Card, Tag, Modal, Select and single-line Input adapt the library; Shell, Header, Nav, captioned Table, textarea, StatusBadge, EmptyState, UploadZone and Timeline retain original business implementations.

Content hierarchy dominates decoration. Status badges include text and a symbol, so positive/negative/proxy/short-history/unsupported/intraday states never depend on red/green alone. Controls retain visible focus, upload is keyboard operable, layouts collapse on mobile and `prefers-reduced-motion` suppresses motion.

The captioned table is intentionally not replaced because the library Table API has no caption or table-level accessible-name prop. Multiline fields retain a native textarea because the library exports only a single-line Input. Desktop composition targets approximately 1440px while remaining usable on narrow mobile screens. Library motion is constrained by the existing `prefers-reduced-motion` rule.
