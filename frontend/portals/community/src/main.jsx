import React from "react";
import { createRoot } from "react-dom/client";
import LegacyPortalRedirect from "../../../src/LegacyPortalRedirect.jsx";

createRoot(document.getElementById("root")).render(
  <React.StrictMode><LegacyPortalRedirect route="/community" /></React.StrictMode>
);
