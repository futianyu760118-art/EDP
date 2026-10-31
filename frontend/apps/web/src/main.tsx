import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { AppMain } from "./app/main";
import { setupMsw } from "./mocks/msw-setup";
import "./styles/tokens.css";
import "./styles/app.css";

void setupMsw().finally(() => {
  createRoot(document.getElementById("root")!).render(
    <StrictMode>
      <AppMain />
    </StrictMode>,
  );
});
