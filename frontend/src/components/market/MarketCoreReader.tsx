import { SecurityProxySparkline } from "../island/SecurityProxySparkline";
import type { MarketCoreBroadMarket, MarketCoreHistoryRow, MarketCoreIndicators, MarketCoreLiveQuote, MarketCoreProxyGroup, MarketCoreShanghai } from "../../types";
import { formatPct, formatSecurityPrice, formatShanghaiDateTime } from "../../utils/format";

const tone = (value: number | null | undefined) => value == null || value === 0 ? "a-share-neutral" : value > 0 ? "a-share-positive" : "a-share-negative";
const liveMessage = (quote: MarketCoreLiveQuote) => quote.freshness === "stale" ? "当前实时行情已结束" : "当前实时行情暂不可用";

export function MarketCoreIndicatorsView({ indicators }: { indicators: MarketCoreIndicators }) {
  const rows: Array<[string, number | null, number | null]> = [
    ["MA5", indicators.ma5, indicators.distance_to_ma5_pct],
    ["MA10", indicators.ma10, indicators.distance_to_ma10_pct],
    ["MA20", indicators.ma20, indicators.distance_to_ma20_pct],
  ];
  return <dl className="reader-market-indicators">
    {rows.map(([label, value, distance]) => <div key={label}>
        <dt>{label}</dt><dd>{value == null ? "—" : formatSecurityPrice(value)}</dd>
        <small className={tone(distance)}>{distance == null ? "—" : `相对均线 ${formatPct(distance)}`}</small>
      </div>)}
  </dl>;
}

export function CompletedHistoryTable({ history, label = "最近10个完整交易日" }: { history: MarketCoreHistoryRow[]; label?: string }) {
  const rows = history.slice(-10);
  return <section className="reader-completed-history" aria-label={label}>
    <div className="reader-completed-history-heading"><h4>{label}</h4><span>仅完整收盘</span></div>
    {rows.length ? <div className="reader-completed-history-table" role="table" aria-label={label}>
      <div className="reader-completed-history-row reader-completed-history-header" role="row"><span>交易日</span><span>收盘</span><span>日涨跌</span></div>
      {rows.map(item => <div className="reader-completed-history-row" role="row" key={item.trading_date}>
        <div role="cell"><small>交易日</small><strong>{item.trading_date}</strong></div>
        <div role="cell"><small>收盘</small><strong>{formatSecurityPrice(item.close)}</strong></div>
        <div role="cell"><small>日涨跌</small><strong className={tone(item.pct_change)}>{item.pct_change == null ? "—" : formatPct(item.pct_change)}</strong></div>
      </div>)}
    </div> : <p className="reader-market-empty">暂无完整收盘记录。</p>}
  </section>;
}

export function MarketCoreShanghaiReader({ market, includeHistory = true }: { market: MarketCoreShanghai | null; includeHistory?: boolean }) {
  if (!market) return <p className="reader-market-empty">市场锚点暂不可用；报告观点仍按报告日期独立展示。</p>;
  const { live, latest_completed: latest, indicators, coverage } = market;
  return <section className="reader-market-anchor" aria-label="客观市场锚点">
    <div className="reader-market-anchor-head"><div><p className="eyebrow">客观市场锚点</p><h3>{market.name}</h3><small className="reader-security-code">000001.SH</small></div><span>独立于报告</span></div>
    <div className="reader-live-summary">
      <div><small>当前行情</small><strong>{live.status === "available" ? formatSecurityPrice(live.current) : "—"}</strong><em className={tone(live.pct_change)}>{live.status === "available" && live.pct_change != null ? formatPct(live.pct_change) : "—"}</em></div>
      <div><small>最近完整收盘</small><strong>{latest ? formatSecurityPrice(latest.close) : "—"}</strong><em>{latest?.trading_date ?? "—"}</em></div>
    </div>
    {live.status === "available" ? <p className="reader-market-time">行情时间：{formatShanghaiDateTime(live.quote_datetime)}</p> : <p className="reader-market-time">{liveMessage(live)}；最近完整收盘、历史与均线继续可用。</p>}
    <MarketCoreIndicatorsView indicators={indicators} />
    {includeHistory && <><CompletedHistoryTable history={market.history} label="最近10个完整交易日上证行情" />
      <p className="reader-market-coverage">已积累 {coverage.available_days} 个真实完成交易日。数据说明：当前行情来自腾讯公开行情；历史日线来自新浪公开行情。</p></>}
  </section>;
}

function BroadAnchorCard({ instrument }: { instrument: MarketCoreBroadMarket["anchors"][number] }) {
  const visiblePrice = instrument.live.status === "available" ? instrument.live.current : instrument.latest_completed?.close;
  const visiblePct = instrument.live.status === "available" ? instrument.live.pct_change : instrument.latest_completed?.pct_change;
  return <article className="broad-market-card">
    <h4>{instrument.name}</h4><small className="reader-security-code">{instrument.security_code}</small>
    <strong>{formatSecurityPrice(visiblePrice)}</strong><em className={tone(visiblePct)}>{visiblePct == null ? "—" : formatPct(visiblePct)}</em>
    <small>{instrument.live.status === "available" ? `行情时间：${formatShanghaiDateTime(instrument.live.quote_datetime)}` : `最近完整收盘：${instrument.latest_completed?.trading_date ?? "—"}`}</small>
    <div className="broad-market-ma"><span className={tone(instrument.indicators.distance_to_ma5_pct)}>MA5 {instrument.indicators.distance_to_ma5_pct == null ? "—" : formatPct(instrument.indicators.distance_to_ma5_pct)}</span><span className={tone(instrument.indicators.distance_to_ma10_pct)}>MA10 {instrument.indicators.distance_to_ma10_pct == null ? "—" : formatPct(instrument.indicators.distance_to_ma10_pct)}</span><span className={tone(instrument.indicators.distance_to_ma20_pct)}>MA20 {instrument.indicators.distance_to_ma20_pct == null ? "—" : formatPct(instrument.indicators.distance_to_ma20_pct)}</span></div>
  </article>;
}

function AlignedBroadMarketTable({ shanghai, broad }: { shanghai: MarketCoreShanghai; broad: MarketCoreBroadMarket }) {
  const dates = shanghai.history.slice(-10).map(item => item.trading_date);
  const assets = [{ name: shanghai.name, history: shanghai.history }, ...broad.anchors.map(item => ({ name: item.name, history: item.history }))];
  return <section className="aligned-broad-market" aria-label="最近10个完整交易日宽基市场">
    <div className="reader-completed-history-heading"><h4>最近10个完整交易日 · 宽基市场</h4><span>按交易日精确对齐</span></div>
    <div className="aligned-broad-market-scroll"><div className="aligned-broad-market-table" role="table">
      <div className="aligned-broad-market-row aligned-broad-market-header" role="row"><span>交易日</span>{assets.map(asset => <span key={asset.name}>{asset.name}</span>)}</div>
      {dates.map(day => <div className="aligned-broad-market-row" role="row" key={day}><strong>{day.slice(5)}</strong>{assets.map(asset => {
        const row = asset.history.find(item => item.trading_date === day);
        return <span key={asset.name}>{row ? <><b className={tone(row.pct_change)}>{row.pct_change == null ? "—" : formatPct(row.pct_change)}</b><small>{formatSecurityPrice(row.close)}</small></> : "—"}</span>;
      })}</div>)}
    </div></div>
  </section>;
}

export function BroadMarketOverview({ shanghai, broad }: { shanghai: MarketCoreShanghai | null; broad: MarketCoreBroadMarket | null }) {
  if (!shanghai) return <p className="reader-market-empty">市场总览暂不可用；报告观点仍按报告日期独立展示。</p>;
  return <section className="broad-market-overview" aria-label="市场总览">
    {broad ? <><div className="broad-market-anchor-grid">{broad.anchors.map(item => <BroadAnchorCard key={item.symbol} instrument={item} />)}</div><AlignedBroadMarketTable shanghai={shanghai} broad={broad} /></> : <p className="reader-market-empty">宽基市场观察暂不可用。</p>}
  </section>;
}

function ProxyInstrument({ instrument }: { instrument: MarketCoreProxyGroup["instruments"][number] }) {
  const recent = instrument.history.slice(-10).map(item => ({ trading_date: item.trading_date, close: item.close, change_pct_from_previous_close: item.pct_change }));
  return <article className="reader-proxy-card">
    <header><div><small className="proxy-role">{instrument.role === "etf" ? "代理ETF" : "核心公司"}</small><h4>{instrument.name}</h4><small className="reader-security-code">{instrument.security_code}</small>{instrument.coverage_type === "partial" && <small>部分覆盖</small>}</div>
      <div className="reader-proxy-live"><strong>{instrument.live.status === "available" ? formatSecurityPrice(instrument.live.current) : "—"}</strong><em className={tone(instrument.live.pct_change)}>{instrument.live.status === "available" && instrument.live.pct_change != null ? formatPct(instrument.live.pct_change) : "—"}</em></div>
    </header>
    <p className="reader-proxy-time">{instrument.live.status === "available" ? `行情时间：${formatShanghaiDateTime(instrument.live.quote_datetime)}` : `${liveMessage(instrument.live)}；展示最近完整收盘。`}</p>
    <p className="reader-proxy-completed">最近完整收盘：{instrument.latest_completed ? `${instrument.latest_completed.trading_date} · ${formatSecurityPrice(instrument.latest_completed.close)}` : "—"}</p>
    <SecurityProxySparkline closes={recent} />
    <MarketCoreIndicatorsView indicators={instrument.indicators} />
    <CompletedHistoryTable history={instrument.history} />
    <p className="reader-proxy-coverage">真实完成日：{instrument.coverage.available_days}</p>
  </article>;
}

export function MarketCoreProxyObservation({ groups, disclosure }: { groups: MarketCoreProxyGroup[]; disclosure: string | null }) {
  return <section className="reader-proxy-observation" aria-label="固定代理证券观察">
    <div className="reader-proxy-heading"><div><p className="eyebrow">客观行情辅助</p><h2>固定代理证券观察</h2></div><span>不生成主题综合涨跌</span></div>
    {groups.map(group => <section className="reader-proxy-group" key={group.proxy_set}><h3>{group.display_name}</h3><div className="reader-proxy-grid">{group.instruments.map(instrument => <ProxyInstrument key={instrument.symbol} instrument={instrument} />)}</div></section>)}
    <p className="reader-proxy-disclosure">{disclosure ?? "代理证券用于观察相关标的表现，不代表官方板块指数或完整行业表现。"}</p>
    <p className="reader-provider-note">数据说明：当前行情来自腾讯公开行情；历史日线来自新浪公开行情。</p>
  </section>;
}
