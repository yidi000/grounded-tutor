import "@fontsource/noto-sans-sc/400.css";
import "@fontsource/noto-serif-sc/600.css";
import "@fontsource/noto-sans-sc/600.css";
import "@fontsource/noto-sans-sc/700.css";
import "@fontsource/ibm-plex-mono/500.css";
import "@fontsource/ibm-plex-mono/600.css";
import "./styles/tokens.css";

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./app";
import { parseAppMode } from "./config";

const root = document.getElementById("root");
if (!root) throw new Error("Missing application root");

const mode = parseAppMode(import.meta.env.VITE_APP_MODE ?? "local");

createRoot(root).render(
  <StrictMode>
    <App mode={mode} />
  </StrictMode>,
);
