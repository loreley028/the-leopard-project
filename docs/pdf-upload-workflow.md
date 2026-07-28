# PDF upload-to-interpretation workflow

验收修订要求上传后先完成PDF忠实还原和证据质量检查。管理端默认只列异常，并以PDF页码和原文摘录对照；`blocking_parse_error` fail closed，不能进入发布。Viewer始终只读取`published`。全流程不调用外部LLM或OCR。

Phase 2A-0 的普通用户主流程只有：

```text
选择或拖入PDF → 上传并解读 → 查看结构化结果 → 确认并发布
```

系统在单次 `POST /api/v1/admin/reports/interpret` 中依次完成文件类型、`%PDF-` 文件头、大小和SHA-256检查，保存原始PDF，读取文本层，识别标题与报告日期，恢复核心观点、大盘路径、风险提示、重点板块、历史路径和板块详细汇总，匹配既有66板块，并生成置信度及少量待确认项。不同内部解析阶段不作为主界面按钮暴露。

重复SHA-256返回原报告，不重复保存或创建报告。解析失败也保留原始PDF，并将用户可见状态标为 `failed`。PDF和文本不会发送到第三方；默认不使用OCR，外部LLM调用为0。

## 日期

`report_date`优先从PDF标题或正文完整日期识别，其次使用文件名。高置信结果直接填入；中置信结果显示轻量检查提示；只有低置信或日期冲突才阻断发布并要求人工确认。上传时间永远不自动确认为报告日期。

`market_as_of_date`只是辅助行情候选，不参与PDF解读成功判断。没有行情日期或行情快照时仍可发布，Viewer明确显示“行情辅助数据尚未附加”。

## 结果与高级复核

结果页默认只显示PDF明确提及、状态变化、存在详细解读或需要确认的板块。confirmed映射不进入待确认列表；全部66板块仍以`not_mentioned`等状态保存，但只在“查看全部66个板块路径”折叠区展示。原始文本、重新解析、日期手调、完整路径编辑和解析诊断都位于默认收起的“高级操作”。

周五、周六没有报告属于正常节奏，不产生缺报告告警。
## Upload response and revisions

`POST /api/v1/admin/reports` returns JSON and navigates to the interpretation result. Preview metadata uses `GET /reports/{id}/pdf/preview`, with per-page PNGs under `/pdf/preview/pages/{page}`; explicit download alone uses `/pdf/download`. Identical SHA-256 returns the existing report. A different file for the same `report_date` creates the next revision and does not replace the current Viewer report until publication.

The frontend does not mount a PDF iframe or request the original PDF during page load, refresh or section navigation. It requests server-rendered page images only after the user clicks the preview control; the attachment endpoint is reached only through the explicit download link. This separation avoids browser PDF preferences turning ordinary page visits into downloads.
