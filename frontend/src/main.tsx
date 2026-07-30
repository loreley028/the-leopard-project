import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "./routes/router";
import 'animal-island-ui/style';
import { App } from "./App";
import { AuthProvider } from "./features/auth/AuthContext";
import "./styles/global.css";

createRoot(document.getElementById("root")!).render(<StrictMode><BrowserRouter><AuthProvider><App /></AuthProvider></BrowserRouter></StrictMode>);
