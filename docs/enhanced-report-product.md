# 增强报告产品定位

Viewer最终验收呈现见 [Viewer验收保真口径](viewer-acceptance-fidelity.md)：默认20期历史矩阵、66板块密集研究表和可展开的五字段详细观点共同构成已发布增强报告正文。

The Leopard Project 当前 MVP 是“大盘猎豹直播总结的动态加强版”。PDF 是证据和业务主线；报告列表、原始 PDF 与 66 板块目录是归档及入口；每期增强报告才是产品主体。

增强报告由报告概览、历史路径矩阵、当期状态汇总、板块详细解读、发布时行情快照、确定性跨期对比和原始 PDF 组成。行情只解释直播观点所处的客观环境，不判断观点对错，也不构成投资建议。

板块纵向研究页保存最新明确观点、本期状态、历次路径和解读、报告发布快照与当前最新行情。`not_mentioned` 只表示本期未明确提及，不使最近明确观点失效。

首版保持 66/65/1：恒生科技可展示观点和路径，但行情仍为 `unsupported`；酒店餐饮为 `proxy`；玻璃基板为 `short_history`。
## Primary Admin workflow

The ordinary operation is now “上传并解读”: one local request validates and stores the PDF, extracts its text layer, recognizes dates and V2.3 sections, creates the 66-sector structure and opens a populated interpretation result. The user does not need to understand the local/enhanced parser split.

The result page shows only actual mentions and genuine attention items. Raw text, the full 66-sector matrix, reparse controls, manual date overrides and market snapshot operations remain available under collapsed advanced review. Market data is optional research context and cannot make PDF interpretation fail.
## Complete latest report

`/` directly renders title, the three date concepts, overview, 10/20/40/all history matrix, five-field detailed assessment and optional market assistance. Status is presented once; basis and observation condition stay directly readable. The original PDF is not requested until the user explicitly loads the inline preview, and Viewer omits provenance excerpts that remain available to Admin.

The matrix stays complete when older detailed PDFs are absent. Path-only dates provide status and frozen EOD context; judgement, basis, conditions and original source links appear only when a matching detailed report exists. Sunday reports visibly pair the Sunday report date with the prior complete Friday market date.

Compact headers render `7/15 三` or `7/26 日 / 行7/24 五`. Sector research distinguishes cached intraday, latest complete EOD and immutable report snapshots, and exposes strict/broad holding interpretations separately.
