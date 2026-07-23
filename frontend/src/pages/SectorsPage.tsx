import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { IslandCard } from "../components/island/IslandCard";
import { IslandStatusBadge } from "../components/island/IslandStatusBadge";
import type { Sector } from "../types";
export function SectorsPage() { const [sectors, setSectors] = useState<Sector[]>([]); useEffect(() => { api.sectors().then(setSectors); }, []); const groups = sectors.reduce<Map<string, Sector[]>>((result, item) => { const current = result.get(item.group_name) ?? []; current.push(item); result.set(item.group_name, current); return result; }, new Map()); return <div className="page"><header><h1>66 个业务板块</h1><p>直播观点覆盖完整目录；自动行情支持口径保持 65/1。</p></header>{Array.from(groups).map(([group, items]) => <section key={group}><h2>{group}</h2><div className="grid">{items.map(item => <IslandCard key={item.sector_key}><h3><Link to={`/sectors/${item.sector_key}`}>{item.sector_name}</Link></h3><IslandStatusBadge status={item.data_status} /><p>{item.latest_view || "暂无已发布观点"}</p><small>{item.mentioned_in_latest_published ? `本期已提及 · ${item.latest_view_date}` : `本期未提及 · 最近观点 ${item.latest_view_date ?? "暂无"}`}</small><br /><small>{item.market_status_detail}</small></IslandCard>)}</div></section>)}</div>; }
