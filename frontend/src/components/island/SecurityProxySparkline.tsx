import type { ViewerSecurityProxyRecentClose } from "../../types";

export function SecurityProxySparkline({ closes }: { closes: ViewerSecurityProxyRecentClose[] }) {
  if (!closes.length) return <p className="proxy-history-empty">近10个交易日：暂无足够历史</p>;
  const values = closes.map(item => item.close);
  const minimum = Math.min(...values); const span = Math.max(...values) - minimum || 1;
  const points = closes.length === 1 ? "50,20" : closes.map((item, index) => `${(index / (closes.length - 1)) * 100},${38 - ((item.close - minimum) / span) * 30}`).join(" ");
  return <svg className="security-proxy-sparkline" viewBox="0 0 100 42" role="img" aria-label="近十个交易日收盘价走势">
    <polyline points={points} fill="none" stroke="#5b3b97" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    {closes.map((item, index) => <circle key={item.trading_date} cx={closes.length === 1 ? 50 : (index / (closes.length - 1)) * 100} cy={38 - ((item.close - minimum) / span) * 30} r="1.7" fill="#5b3b97" />)}
  </svg>;
}
