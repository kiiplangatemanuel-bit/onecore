import React from "react";
import {createRoot} from "react-dom/client";
import PortalApp from "../../../src/PortalApp.jsx";
createRoot(document.getElementById("root")).render(<React.StrictMode><PortalApp portal="admin"/></React.StrictMode>);
