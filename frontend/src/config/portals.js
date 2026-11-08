const ENV = import.meta.env || {};
const KEYS = {
  publicSite: "VITE_PUBLIC_SITE_URL", app: "VITE_APP_URL", admin: "VITE_ADMIN_URL",
  developers: "VITE_DEVELOPER_URL", docs: "VITE_DOCS_URL", support: "VITE_SUPPORT_URL",
  status: "VITE_STATUS_URL", community: "VITE_COMMUNITY_URL", trust: "VITE_TRUST_URL",
  events: "VITE_EVENTS_URL", careers: "VITE_CAREERS_URL", partners: "VITE_PARTNERS_URL",
  api: "VITE_API_BASE_URL",
};
function normalize(value, key) {
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
  Object.entries(KEYS).map(([key, envName]) => [key, normalize(ENV[envName], key)])
));
export function portalUrl(key, path = "") {
  const base = portals[key];
  if (!base) return "";
  try {
    const target = new URL(path.replace(/^\//, ""), base.endsWith("/") ? base : base + "/");
    if (target.origin !== new URL(base).origin) return "";
    return target.href;
  } catch { return ""; }
}
export function portalLink(key, path = "") {
  return portalUrl(key, path) || "#portal-configuration";
}
export function portalConfiguration() {
  return Object.entries(KEYS).filter(([key]) => key !== "api")
    .map(([key, envName]) => ({ key, envName, configured: Boolean(portals[key]) }));
}
