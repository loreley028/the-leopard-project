import type { PathStatus } from "../types";

const STATUS_WORDS: Record<PathStatus, string[]> = {
  avoid: ["不碰", "回避"], strong_watch: ["强观", "强观察"], watch: ["观察"],
  weak_watch: ["弱观", "弱观察"], turn_hold: ["转持", "转为持有"], hold: ["持有", "继续持有"],
  turn_weak: ["转弱", "转为弱势"], exit: ["离场", "退出"], not_mentioned: ["未提", "未提及"],
};

const clean = (value: string) => value.trim().replace(/[。！!；;]+$/g, "").replace(/\s+/g, "");

export function judgementDetail(status: PathStatus, judgement: string) {
  const normalized = clean(judgement);
  return STATUS_WORDS[status].some(word => clean(word) === normalized) ? "" : judgement.trim();
}

export function pdfGroup(status: PathStatus) {
  if (["hold", "turn_hold"].includes(status)) return "B1 继续持有";
  if (["strong_watch", "watch", "weak_watch", "turn_weak"].includes(status)) return "B2 重点观察区";
  return "B3 当前不碰";
}
