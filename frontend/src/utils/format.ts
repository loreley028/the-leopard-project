export function formatShanghaiDateTime(value: string | null | undefined) {
  if (!value) return "—";
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date(value)).replaceAll("/", "-");
}

/** Quote timestamps keep provider-supplied seconds visible to Reader users. */
export function formatShanghaiQuoteDateTime(value: string | null | undefined) {
  if (!value) return "—";
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(new Date(value)).replaceAll("/", "-");
}

export function formatPct(value: number | null | undefined) {
  if (value == null) return "历史不足";
  return `${value >= 0 ? "+" : ""}${value.toFixed(2)}%`;
}

export function formatNumber(value: number | null | undefined, digits = 2) {
  return value == null ? "历史不足" : value.toFixed(digits);
}

/** Keep quote, completed-close, and MA precision readable and consistent. */
export function formatSecurityPrice(value: number | null | undefined) {
  if (value == null) return "—";
  const digits = Math.abs(value) < 10 ? 3 : 2;
  return value.toLocaleString("zh-CN", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}
