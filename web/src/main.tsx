import "@fontsource-variable/geist";
import "@fontsource-variable/geist-mono";
import "./globals.css";

import { lazy, StrictMode, Suspense } from "react";
import { createRoot } from "react-dom/client";
const DashboardApp = lazy(() =>
  import("./App").then((module) => ({ default: module.App })),
);
const Society = lazy(() => import("./society/Society"));
const isSociety = window.location.pathname.replace(/\/$/, "") === "/society";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <Suspense
      fallback={
        <div
          style={{
            padding: 40,
            color: "#315445",
            background: "#f4f3eb",
            minHeight: "100vh",
          }}
        >
          {isSociety ? "Opening the society…" : "Opening EloPhanto…"}
        </div>
      }
    >
      {isSociety ? <Society /> : <DashboardApp />}
    </Suspense>
  </StrictMode>,
);
