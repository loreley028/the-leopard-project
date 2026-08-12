import { useState } from "react";
import { useNavigate } from "../routes/router";
import { IslandButton } from "../components/island/IslandButton";
import { IslandCard } from "../components/island/IslandCard";
import { IslandField } from "../components/island/IslandField";
import { useAuth } from "../features/auth/AuthContext";
export function AdminLoginPage() { const { adminLogin } = useAuth(); const navigate = useNavigate(); const [username, setUsername] = useState(""); const [password, setPassword] = useState(""); const [error, setError] = useState(""); return <div className="page admin-login-page"><IslandCard title="Admin 登录"><p className="muted">报告上传、解读与发布仅限管理员操作。</p><form className="stack" onSubmit={async event => { event.preventDefault(); try { await adminLogin(username, password); navigate("/admin"); } catch { setError("管理员用户名或密码不正确"); } }}><IslandField label="管理员用户名" value={username} onChange={event => setUsername(event.target.value)} /><IslandField label="管理员密码" type="password" value={password} onChange={event => setPassword(event.target.value)} />{error && <p role="alert">{error}</p>}<IslandButton type="submit">进入管理区</IslandButton></form><p className="muted">普通读者可直接浏览网站内容；不提供注册或找回密码。</p></IslandCard></div>; }
