# Product MVP scope

本轮最低产品要求是PDF忠实还原，网页信息密度不得低于PDF。解析无法确认时fail closed；行情仍是研究辅助数据，不启用`production_primary`、自动采集或调度，也不调用外部LLM。

当前 MVP 的正式定位是“大盘猎豹直播总结的动态加强版”。归档和板块目录是入口层；每期增强报告是主体；板块纵向研究页是跨期研究层。PDF 继续是最终证据，行情仅为研究辅助数据。

增强范围包括版本化历史路径、五字段板块解读、report/market/intraday日期分离、完整 EOD 指标、缺口补齐、不可变报告快照、五分钟服务器盘中缓存和确定性报告对比。仍无生产主数据源、生产调度、外部 LLM 或恒生科技行情。

Phase 2A-0 is a small internal research product for roughly ten read-only viewers and one primary administrator. The product is organized around published PDF research, not real-time quotes.

Viewer can read the latest and historical published reports, open the published PDF, browse all 66 sectors and follow published opinion timelines. Viewer never sees drafts or withdrawn reports.

Admin can upload a PDF, run local parsing, confirm the report date, edit controlled structured fields, resolve an unmapped term to an existing sector, mark ready, publish and withdraw. The formal sector catalog is not editable in the Web MVP.

Viewer and Admin share one React application, one FastAPI backend and one SQLite repository. Phase 2A-0 is local only: no cloud deployment, public access, production database, production scheduler, external LLM, HSTECH integration or Phase 1B-2 observation. In `real_local`, one process-local five-minute research cache may refresh automatically during controlled A-share sessions; Viewer remains cache-only and no Provider is promoted.
## Upload-to-Interpretation acceptance scope

For the current private noncommercial MVP, the repeated user job is: upload an already generated V2.3/V2.3.1/V2.4 live-summary PDF, inspect the automatically populated Web interpretation, and explicitly publish it. Raw transcripts, OCR, external LLM interpretation, production market collection and automatic publication are outside scope.

Archives and the 66-sector catalog remain entry layers. Automatic interpretation does not remove the original PDF or the advanced review capabilities, and it does not infer investment advice or judge whether a host was right.
## Daily-use product boundary

The product is the dynamic enhanced version of the live-summary PDF. The PDF remains authoritative; history and real market snapshots only add context. The Viewer root is the latest full report, while the report library is archival. Missing market data is shown as `—` and never replaced by fixtures.
