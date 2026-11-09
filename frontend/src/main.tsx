import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./app/App";
import { applyTheme, getTheme } from "./shared/lib/theme";
import { registerPwa } from "./shared/pwa/updater";
import "./index.css";

applyTheme(getTheme());
void registerPwa();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
