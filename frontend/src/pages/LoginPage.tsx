import { useState } from "react";
import { useNavigate } from "../routes/router";
import { IslandButton } from "../components/island/IslandButton";
import { IslandCard } from "../components/island/IslandCard";
import { IslandField } from "../components/island/IslandField";
import { useAuth } from "../features/auth/AuthContext";
export function LoginPage() { const { login } = useAuth(); const navigate = useNavigate(); const [username, setUsername] = useState(""); const [password, setPassword] = useState(""); const [error, setError] = useState(""); return <div className="page"><IslandCard title="登录研究手册"><form className="stack" onSubmit={async event => { event.preventDefault(); try { await login(username, password); navigate("/"); } catch { setError("用户名或密码不正确"); } }}><IslandField label="用户名" value={username} onChange={event => setUsername(event.target.value)} /><IslandField label="密码" type="password" value={password} onChange={event => setPassword(event.target.value)} />{error && <p role="alert">{error}</p>}<IslandButton type="submit">登录</IslandButton></form><p className="muted">当前为本地研究 MVP，不提供注册或找回密码。</p></IslandCard></div>; }
