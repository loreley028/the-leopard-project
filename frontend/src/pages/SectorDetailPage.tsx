import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../api/client";
import { IslandCard } from "../components/island/IslandCard";
import { IslandStatusBadge } from "../components/island/IslandStatusBadge";
import { IslandTimeline } from "../components/island/IslandTimeline";
import type { Sector } from "../types";
export function SectorDetailPage() { const { sectorKey = "" } = useParams(); const [sector, setSector] = useState<Sector | null>(); useEffect(() => { api.sector(sectorKey).then(setSector).catch(() => setSector(null)); }, [sectorKey]); if (!sector) return <p role="status">加载板块资料…</p>; return <div className="page"><header><p className="eyebrow">{sector.group_name}</p><h1>{sector.sector_name}</h1><IslandStatusBadge status={sector.data_status} /><p>{sector.market_status_detail}</p></header><IslandCard title="直播观点时间线">{sector.timeline?.length ? <IslandTimeline items={sector.timeline.map(item => ({ date: item.report_date, title: item.report_title, content: item.summary }))} /> : <p>暂无已发布观点。</p>}</IslandCard><p className="notice">研究辅助数据，非生产级行情服务。</p></div>; }
