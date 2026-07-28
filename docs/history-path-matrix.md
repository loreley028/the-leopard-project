# 历史路径矩阵

桌面端默认最近20期，并支持10/20/40/全部；66板块严格按现有8个一级分组集中排列。每个状态使用配置化实心色和中文文字，日期升序、最新列突出，表头与板块列sticky，横向滚动限制在矩阵内部。移动端改用最近5期时间线。

矩阵是原生可访问表格，不是截图。桌面端固定板块列与日期表头，矩阵内部横向滚动；支持最近 5 期、10 期、全部、板块搜索和状态筛选。单元格包含中文状态和配置色，键盘可聚焦，点击后显示报告日期、明确提及标志、当日判断和来源入口。

移动端在 760px 以下切换为按板块折叠的时间线，页面本身不横向溢出。表格提供 caption，reduced-motion 规则继续有效。
## Freeze-and-append and daily return

For the accepted V2.4 report, history through 2026-07-26 is frozen and only 2026-07-27 is appended after equality checks. Each Web cell contains the reported status and an optional real `daily_return` tied to `market_as_of_date`. Missing data is null/`—`. The matrix is catalog-version driven and can expand beyond the current 66 entries.

The canonical source is the latest reliable complete PDF matrix persisted into `SectorPathHistoryEntry`, not the number of uploaded `Report` or `SectorAssessment` rows. The 2026-07-27 V2.4 PDF restores 35 report dates across all 66 sectors. Dates without a detailed uploaded PDF display “仅有路径记录，尚未补充该期原始报告” and never invent judgement text or provenance.

Matrix ranges are 10, 20, 40 and all available periods. Each column returns `report_date`, separately frozen `market_as_of_date`, weekday and weekend metadata. A Sunday header therefore shows “报告 07-26 周日 / 行情 07-24 周五”. Cell returns are frozen `eod_complete` values; intraday refresh cannot alter the matrix.

Initial import records PDF hash, template version and source report. Later complete PDFs compare the frozen region: equal rows append only new dates; differences are listed by sector/date/old/new status, small sets require attention and large rewrites block. Frozen rows are never silently replaced.

Desktop date columns are fixed at 80px with reduced padding; complete dates and semantics remain in tooltips/details. Mobile continues to use a timeline rather than compressing the table.
