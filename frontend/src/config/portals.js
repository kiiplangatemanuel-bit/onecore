const ENV = import.meta.env || {};
const KEYS = {
  publicSite: "VITE_PUBLIC_SITE_URL", app: "VITE_APP_URL",
  developers: "VITE_DEVELOPER_URL", docs: "VITE_DOCS_URL",
  careers: "VITE_CAREERS_URL", partners: "VITE_PARTNERS_URL",
  api: "VITE_API_BASE_URL",
};
const INTEGRATED_ROUTES = Object.freeze({
  support: "/support",
  trust: "/trust",
  community: "/community",
  status: "/status",
  events: "/events",
  admin: "/admin",
});
function normalize(value) {
  if (typeof value !== "string" || !value.trim()) return "";
  try {
    const url = new URL(value.trim());
    if (!["https:", ...(ENV.DEV ? ["http:"] : [])].includes(url.protocol)) return "";
    if (url.username || url.password) return "";
    return url.origin + url.pathname.replace(/\/$/, "") + url.search + url.hash;
  } catch {
    return "";
  }
}
export const portals = Object.freeze(Object.fromEntries(
  Object.entries(KEYS).map(([key, envName]) => [key, normalize(ENV[envName])])
));
export function portalUrl(key, path = "") {
  const integratedPath = INTEGRATED_ROUTES[key];
  const base = integratedPath
    ? (portals.publicSite || (typeof window !== "undefined" ? window.location.origin : ""))
    : key === "app" ? (portals.app || portals.publicSite) : portals[key];
  if (!base) return "";
  try {
    const destination = integratedPath ? integratedPath : path.replace(/^\//, "");
    const target = new URL(destination, base.endsWith("/") ? base : base + "/");
    if (target.origin !== new URL(base).origin) return "";
    return target.href;
  } catch { return ""; }
}
export function portalLink(key, path = "") {
  return portalUrl(key, path) || "#contact";
}
export function portalConfiguration() {
  return Object.entries(KEYS).filter(([key]) => key !== "api")
    .map(([key, envName]) => ({ key, envName, configured: Boolean(portals[key]) }));
}
