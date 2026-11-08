const configured=(import.meta.env.VITE_API_BASE_URL||"").trim();
export const API_BASE=(configured||(import.meta.env.DEV?"http://localhost:8000":window.location.origin)).replace(/\/$/,"");
const TOKEN_KEY="onecore.access_token",ORG_KEY="onecore.organization_id";
export const getToken=()=>sessionStorage.getItem(TOKEN_KEY);
export const setToken=token=>sessionStorage.setItem(TOKEN_KEY,token);
export const clearToken=()=>{sessionStorage.removeItem(TOKEN_KEY);sessionStorage.removeItem(ORG_KEY)};
export const setActiveOrganization=id=>{if(id)sessionStorage.setItem(ORG_KEY,String(id));else sessionStorage.removeItem(ORG_KEY)};
export const getActiveOrganization=()=>sessionStorage.getItem(ORG_KEY);
export async function api(path,options={}){const headers=new Headers(options.headers||{});const token=getToken();if(token)headers.set("Authorization",`Bearer ${token}`);const org=getActiveOrganization();if(org&&!headers.has("X-Organization-ID"))headers.set("X-Organization-ID",org);if(options.body&&!(options.body instanceof FormData)&&!headers.has("Content-Type"))headers.set("Content-Type","application/json");let response;try{response=await fetch(`${API_BASE}${path.startsWith("/")?path:`/${path}`}`,{...options,headers})}catch{throw new Error(`Cannot reach OneCore API at ${API_BASE}. Check VITE_API_BASE_URL and backend CORS settings.`)}const type=response.headers.get("content-type")||"";const payload=type.includes("application/json")?await response.json():await response.text();if(!response.ok){const message=typeof payload==="object"?(payload.detail||payload.message||response.statusText):(payload||response.statusText);throw new Error(typeof message==="string"?message:JSON.stringify(message))}return payload}
export async function login(email,password){
  const supabaseUrl=(import.meta.env.VITE_SUPABASE_URL||"").trim().replace(/\\/$/,"");
  const supabaseKey=(import.meta.env.VITE_SUPABASE_ANON_KEY||"").trim();
  if(supabaseUrl&&supabaseKey){
    let response;
    try{response=await fetch(supabaseUrl+"/auth/v1/token?grant_type=password",{method:"POST",headers:{"Content-Type":"application/json","apikey":supabaseKey},body:JSON.stringify({email,password})});}
    catch{throw new Error("Cannot reach Supabase Auth. Check VITE_SUPABASE_URL and network configuration.");}
    const payload=await response.json().catch(()=>({}));
    if(!response.ok||!payload.access_token)throw new Error(payload.msg||payload.message||payload.error_description||"Supabase sign-in failed.");
    setToken(payload.access_token);
    try{return await api("/api/v1/auth/me");}catch(error){clearToken();throw error;}
  }
  const body=new URLSearchParams({username:email,password});
  const result=await api("/api/v1/auth/login",{method:"POST",body,headers:{"Content-Type":"application/x-www-form-urlencoded"}});
  if(!result.access_token)throw new Error("The API did not return an access token.");
  setToken(result.access_token);return api("/api/v1/auth/me");
}
