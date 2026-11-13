import React, { useEffect } from "react";
import { portalUrl } from "./config/portals";

export default function LegacyPortalRedirect({ route }) {
  const destination = portalUrl("publicSite", route);
  useEffect(() => {
    if (destination) window.location.replace(destination);
  }, [destination]);
  return <main style={{fontFamily:"system-ui,sans-serif",maxWidth:640,margin:"12vh auto",padding:24,lineHeight:1.6}}>
    <h1>This OneCore module has moved</h1>
    <p>It is now part of the main OneCore website. Use the link below to continue.</p>
    {destination ? <a href={destination}>Open the OneCore {route.slice(1)} module ↗</a> : <p>Set the public <code>VITE_PUBLIC_SITE_URL</code> environment variable for this legacy deployment to enable the redirect.</p>}
  </main>;
}
