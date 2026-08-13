import { useEffect, useState } from "react";
import { api } from "../api/client";
import { IslandCard } from "../components/island/IslandCard";
import type { MarketCoreHistoryRow, MarketCoreIndicators, MarketCoreProxyInstrument, MarketCoreProxies, MarketCoreShanghai } from "../types";
import { formatPct, formatSecurityPrice, formatShanghaiDateTime } from "../utils/format";

const tone = (value: number | null | undefined) => value == null || value === 0 ? "a-share-neutral" : value > 0 ? "a-share-positive" : "a-share-negative";

function Indicators({ value }: { value: MarketCoreIndicators }) {
  return <dl className="market-lab-indicators">
    {[["MA5", value.ma5, value.distance_to_ma5_pct], ["MA10", value.ma10, value.distance_to_ma10_pct], ["MA20", value.ma20, value.distance_to_ma20_pct]].map(([label, average, distance]) => <div key={String(label)}>
      <dt>{label}</dt><dd>{typeof average === "number" ? formatSecurityPrice(average) : "—"}</dd><dd className={tone(typeof distance === "number" ? distance : null)}>{typeof distance === "number" ? formatPct(distance) : "历史不足"}</dd>
    </div>)}
  </dl>;
}

function Coverage({ days, first, latest }: { days: number; first: string | null; latest: string | null }) {
  return <p className="market-lab-coverage"><strong>真实完成日：{days}</strong> · 首日 {first ?? "—"} · 最新 {latest ?? "—"}{days < 20 ? " · 历史不足，MA 不补值" : ""}</p>;
}

function History({ items }: { items: MarketCoreHistoryRow[] }) {
  return <div className="market-lab-history" aria-label="真实完成交易日历史">
    <div className="market-lab-history-row market-lab-history-header"><span>交易日</span><span>收盘</span><span>日涨跌</span><span>来源</span></div>
    {items.length ? items.map(item => <div className="market-lab-history-row" key={item.trading_date}><time>{item.trading_date}</time><strong>{formatSecurityPrice(item.close)}</strong><b className={tone(item.pct_change)}>{item.pct_change == null ? "—" : formatPct(item.pct_change)}</b><small>{item.source ?? "—"}</small></div>) : <p>暂无真实完成收盘记录。</p>}
  </div>;
}

function Live({ name, symbol, quote }: { name: string; symbol: string; quote: MarketCoreShanghai["live"] }) {
  return <section className="market-lab-live"><div><p className="eyebrow">{symbol}</p><h3>{name}</h3></div><div><strong>{formatSecurityPrice(quote.current)}</strong><b className={tone(quote.pct_change)}>{quote.pct_change == null ? "—" : formatPct(quote.pct_change)}</b></div><p>行情时间：{formatShanghaiDateTime(quote.quote_datetime)}</p><p>服务器接收：{formatShanghaiDateTime(quote.server_received_at)}</p><p>Provider：{quote.provider ?? "—"} · {quote.freshness}</p>{quote.status !== "available" && <p className="notice">实时行情暂不可用：{quote.error_code ?? "未返回"}</p>}</section>;
}

function ProxyInstrument({ value }: { value: MarketCoreProxyInstrument }) {
  return <article className="market-lab-proxy"><Live name={value.name} symbol={value.symbol} quote={value.live} /><p className="market-lab-role">{value.role === "etf" ? "代理ETF" : "核心公司"}{value.coverage_type === "partial" ? " · 部分覆盖" : ""}</p><Coverage days={value.coverage.available_days} first={value.coverage.first_date} latest={value.coverage.latest_date} /><p>最近完整收盘：{value.latest_completed ? `${value.latest_completed.trading_date} · ${formatSecurityPrice(value.latest_completed.close)}` : "—"}</p><Indicators value={value.indicators} /><History items={value.history} /></article>;
}

export function MarketLabPage() {
  const [shanghai, setShanghai] = useState<MarketCoreShanghai | null>(null);
  const [proxies, setProxies] = useState<MarketCoreProxies | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { Promise.all([api.marketShanghai(), api.marketProxies()]).then(([anchor, proxySets]) => { setShanghai(anchor); setProxies(proxySets); }).catch(() => setError("市场读模型暂不可用；未使用报告或PDF回退。")); }, []);
  if (error) return <div className="page"><h1>Market Lab</h1><p role="alert">{error}</p></div>;
  if (!shanghai || !proxies) return <div className="page"><p role="status">正在读取独立 Market Core…</p></div>;
  return <div className="page market-lab-page"><header><p className="eyebrow">Market-only acceptance</p><h1>Market Lab</h1><p className="lead">独立市场观察：不读取 PDF、报告、板块观点、攻防线或路径状态。实时与完成日严格分离。</p></header>
    <IslandCard title="上证指数 · 客观市场"><Live name={shanghai.name} symbol={shanghai.symbol} quote={shanghai.live} /><Coverage days={shanghai.coverage.available_days} first={shanghai.coverage.first_date} latest={shanghai.coverage.latest_date} /><p>最近完整收盘：{shanghai.latest_completed ? `${shanghai.latest_completed.trading_date} · ${formatSecurityPrice(shanghai.latest_completed.close)} · ${shanghai.latest_completed.pct_change == null ? "—" : formatPct(shanghai.latest_completed.pct_change)}` : "—"}</p><Indicators value={shanghai.indicators} /><History items={shanghai.history} /></IslandCard>
    <section className="market-lab-proxy-groups"><h2>固定代理证券 · 客观观察</h2><p className="muted">固定注册表、服务器端符号、每批最多 20 只；不生成主题综合涨跌或合成指数。</p>{proxies.groups.map(group => <section className="market-lab-group" key={group.proxy_set}><h3>{group.display_name}</h3><div>{group.instruments.map(item => <ProxyInstrument key={item.symbol} value={item} />)}</div></section>)}</section>
    <IslandCard title="DATA COVERAGE"><p>上证指数：{shanghai.coverage.available_days} 个真实完成交易日。</p>{proxies.groups.flatMap(group => group.instruments).map(item => <p key={item.symbol}>{item.name}（{item.symbol}）：{item.coverage.available_days} 个真实完成交易日；{item.coverage.first_date ?? "—"} 至 {item.coverage.latest_date ?? "—"}。</p>)}<p className="notice">历史不足会原样显示；系统不使用最近可用日、前向填充或盘中值计算 MA。</p></IslandCard>
  </div>;
}
