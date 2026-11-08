const configured = (import.meta.env.VITE_API_BASE_URL || "").trim();
export const API_BASE = (configured || (import.meta.env.DEV ? "http://localhost:8000" : window.location.origin)).replace(/\/$/, "");
const TOKEN_KEY = "onecore.access_token";
export const getToken = () => sessionStorage.getItem(TOKEN_KEY);
export const setToken = token => sessionStorage.setItem(TOKEN_KEY, token);
export const clearToken = () => sessionStorage.removeItem(TOKEN_KEY);

export async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (options.body && !(options.body instanceof FormData) && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  let response;
  try { response = await fetch(`${API_BASE}${path.startsWith("/") ? path : `/${path}`}`, { ...options, headers }); }
  catch { throw new Error(`Cannot reach OneCore API at ${API_BASE}. Check VITE_API_BASE_URL and backend CORS settings.`); }
  const type = response.headers.get("content-type") || "";
  const payload = type.includes("application/json") ? await response.json() : await response.text();
  if (!response.ok) {
    const message = typeof payload === "object" ? (payload.detail || payload.message || response.statusText) : (payload || response.statusText);
    throw new Error(typeof message === "string" ? message : JSON.stringify(message));
  }
  return payload;
}

export async function login(email, password) {
  const body = new URLSearchParams({ username: email, password });
  const result = await api("/api/v1/auth/login", { method: "POST", body, headers: { "Content-Type": "application/x-www-form-urlencoded" } });
  if (!result.access_token) throw new Error("The API did not return an access token.");
  setToken(result.access_token);
  return api("/api/v1/auth/me");
}
