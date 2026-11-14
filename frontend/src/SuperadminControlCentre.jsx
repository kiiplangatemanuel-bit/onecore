import React, { useCallback, useEffect, useState } from "react";
import { api } from "./api";

const MODULES = ["accounting","crm","inventory","procurement","pos","hr","payroll","school","hospital","pharmacy","laboratory","sacco","property","hotel","restaurant","reports","documents"];
const TABS = ["overview","organizations","subscriptions","developers","security","incidents","maintenance","audit"];
const label = value => String(value || "").replaceAll("_"," ").split(" ").map(word => word ? word.charAt(0).toUpperCase()+word.slice(1) : word).join(" ");

function Panel({title,children,action}) {
  return <section className="panel"><div className="panel-head"><div><h3>{title}</h3></div>{action}</div>{children}</section>;
}
function Rows({items,empty,render}) {
  return items?.length ? <div className="portal-list">{items.map(render)} </div> : <p className="empty">{empty}</p>;
}

export default function SuperadminControlCentre() {
  const [tab,setTab] = useState("overview");
  const [data,setData] = useState({overview:null,organizations:[],subscriptions:[],plans:[],users:[],credentials:[],audit:[],incidents:[],maintenance:[]});
  const [selectedOrg,setSelectedOrg] = useState("");
  const [entitlements,setEntitlements] = useState([]);
  const [planId,setPlanId] = useState("");
  const [status,setStatus] = useState("active");
  const [reason,setReason] = useState("");
  const [operation,setOperation] = useState({title:"",summary:"",severity:"medium",owner:"",affected_services:""});
  const [busy,setBusy] = useState(false);
  const [error,setError] = useState("");
  const [notice,setNotice] = useState("");

  const refresh = useCallback(async () => {
    setError("");
    const [overview,organizations,subscriptions,plans,users,credentials,audit,incidents,maintenance] = await Promise.all([
      api("/api/v1/admin/platform/overview"),
      api("/api/v1/admin/platform/organizations"),
      api("/api/v1/admin/platform/subscriptions"),
      api("/api/v1/admin/platform/subscription-plans"),
      api("/api/v1/admin/platform/users"),
      api("/api/v1/admin/platform/developer-credentials"),
      api("/api/v1/admin/platform/audit"),
      api("/api/v1/admin/platform/operations/incidents"),
      api("/api/v1/admin/platform/operations/maintenance")
    ]);
    setData({overview,organizations,subscriptions,plans,users,credentials,audit,incidents,maintenance});
    if (!selectedOrg && organizations.length) setSelectedOrg(String(organizations[0].id));
  },[selectedOrg]);

  useEffect(()=>{refresh().catch(e=>setError(e.message));},[refresh]);
  useEffect(()=>{
    if(!selectedOrg)return;
    api("/api/v1/admin/platform/organizations/"+selectedOrg+"/entitlements")
      .then(result=>setEntitlements(result.effective_entitlements?.modules || []))
      .catch(e=>setError(e.message));
  },[selectedOrg]);

  async function act(fn,success) {
    setBusy(true);setError("");setNotice("");
    try { await fn(); await refresh(); setNotice(success); }
    catch(e){setError(e.message);}
    finally{setBusy(false);}
  }
  async function assignPlan(e) {
    e.preventDefault();
    await act(()=>api("/api/v1/admin/platform/organizations/"+selectedOrg+"/subscription",{
      method:"PUT",body:JSON.stringify({plan_id:Number(planId),status})
    }),"Subscription assigned.");
  }
  async function saveEntitlements(e) {
    e.preventDefault();
    await act(()=>api("/api/v1/admin/platform/organizations/"+selectedOrg+"/entitlements",{
      method:"PATCH",body:JSON.stringify({entitlements:{modules:entitlements}})
    }),"Organization entitlements updated.");
  }
  async function changeSubscription(subscriptionId,nextStatus) {
    await act(()=>api("/api/v1/admin/platform/subscriptions/"+subscriptionId+"/lifecycle",{
      method:"PATCH",body:JSON.stringify({status:nextStatus,reason:reason || "Superadmin lifecycle action"})
    }),"Subscription lifecycle updated.");
  }
  async function revokeCredential(id) {
    await act(()=>api("/api/v1/admin/platform/developer-credentials/"+id+"/revoke",{method:"POST"}),"Developer credential revoked.");
  }
  async function revokeSessions(id) {
    await act(()=>api("/api/v1/admin/platform/users/"+id+"/revoke-sessions?reason="+encodeURIComponent(reason || "Superadmin security action"),{method:"POST"}),"User sessions revoked.");
  }
  async function createOperation(kind,e) {
    e.preventDefault();
    const payload={...operation,affected_services:operation.affected_services.split(",").map(x=>x.trim()).filter(Boolean)};
    await act(()=>api("/api/v1/admin/platform/operations/"+kind,{method:"POST",body:JSON.stringify(payload)}),
      kind==="incidents"?"Incident record created as draft.":"Maintenance record created as draft.");
    setOperation({title:"",summary:"",severity:"medium",owner:"",affected_services:""});
  }
  async function transition(kind,id,next) {
    await act(()=>api("/api/v1/admin/platform/operations/"+kind+"/"+id+"/transition",{
      method:"POST",body:JSON.stringify({status:next,note:"Superadmin control-centre transition"})
    }),"Operational record updated.");
  }

  const overview=data.overview||{};
  return <div className="superadmin-centre">
    <div className="page-heading"><div><p className="eyebrow">ONECORE · PLATFORM CONTROL CENTRE</p><h1>Superadmin</h1><p className="muted">One control plane for organizations, entitlements, developer access, security and operations.</p></div><button className="secondary" disabled={busy} onClick={()=>refresh().catch(e=>setError(e.message))}>Refresh control centre</button></div>
    {error&&<div className="alert error" role="alert">{error}</div>}
    {notice&&<div className="notice info" role="status">{notice}</div>}
    <nav className="portal-tabs" aria-label="Superadmin sections">{TABS.map(x=><button key={x} className={tab===x?"active":""} onClick={()=>setTab(x)}>{label(x)}</button>)}</nav>
    {tab==="overview"&&<>
      <div className="stat-grid"><div className="stat-card"><span>Organizations</span><strong>{overview.organizations??"—"}</strong></div><div className="stat-card"><span>Active organizations</span><strong>{overview.active_organizations??"—"}</strong></div><div className="stat-card"><span>Active users</span><strong>{overview.active_users??"—"}</strong></div><div className="stat-card"><span>Active subscriptions</span><strong>{overview.active_subscriptions??"—"}</strong></div></div>
      <div className="two-col"><Panel title="Platform posture"><p>Pending subscription payments: <strong>{overview.pending_subscription_payments??0}</strong></p><p>Audit events today: <strong>{overview.recent_audit_events??0}</strong></p><p>Registered memberships: <strong>{overview.memberships??0}</strong></p></Panel><Panel title="Operational inventory"><p>Developer credentials: <strong>{data.credentials.length}</strong></p><p>Open incident records: <strong>{data.incidents.filter(x=>!["resolved","closed"].includes(x.status)).length}</strong></p><p>Planned maintenance records: <strong>{data.maintenance.length}</strong></p></Panel></div>
    </>}
    {tab==="organizations"&&<>
      <Panel title="Organization lifecycle"><Rows items={data.organizations} empty="No organizations found." render={org=><div className="org-row" key={org.id}><div><strong>{org.name}</strong><small>{org.slug} · {org.industry} · {org.member_count} members</small></div><span className={"status "+(org.is_active?"online":"offline")}>{org.is_active?"Active":"Suspended"}</span><button className="secondary" onClick={()=>setSelectedOrg(String(org.id))}>Manage entitlements</button></div>}/></Panel>
      <Panel title="Organization module entitlements"><label>Organization<select value={selectedOrg} onChange={e=>setSelectedOrg(e.target.value)}>{data.organizations.map(x=><option key={x.id} value={x.id}>{x.name}</option>)}</select></label><form onSubmit={saveEntitlements}><div className="capability-list">{MODULES.map(key=><label key={key}><input type="checkbox" checked={entitlements.includes(key)} onChange={e=>setEntitlements(old=>e.target.checked?[...old,key]:old.filter(x=>x!==key))}/>{label(key)}</label>)}</div><button className="primary" disabled={busy||!selectedOrg}>Save organization override</button></form><p className="tiny">An explicit override replaces the plan's module list for this organization. The backend enforces it on protected business API routes.</p></Panel>
    </>}
    {tab==="subscriptions"&&<>
      <Panel title="Assign or renew subscription"><form className="stack-form" onSubmit={assignPlan}><label>Organization<select required value={selectedOrg} onChange={e=>setSelectedOrg(e.target.value)}>{data.organizations.map(x=><option key={x.id} value={x.id}>{x.name}</option>)}</select></label><label>Plan<select required value={planId} onChange={e=>setPlanId(e.target.value)}><option value="">Choose plan</option>{data.plans.filter(x=>x.is_active).map(x=><option key={x.id} value={x.id}>{x.name} · {x.currency} {x.amount}/{x.interval}</option>)}</select></label><label>Initial status<select value={status} onChange={e=>setStatus(e.target.value)}><option value="active">Active</option><option value="trialing">Trialing</option></select></label><button className="primary" disabled={busy||!selectedOrg||!planId}>Assign subscription</button></form></Panel>
      <Panel title="Subscription lifecycle"><Rows items={data.subscriptions} empty="No subscriptions found." render={sub=><div className="org-row" key={sub.id}><div><strong>{sub.organization}</strong><small>{sub.plan} · #{sub.id} · {sub.ends_at||"No end date"}</small></div><span className="status">{label(sub.status)}</span><select aria-label={"Change subscription "+sub.id} defaultValue={sub.status} onChange={e=>changeSubscription(sub.id,e.target.value)}><option value="active">Active</option><option value="trialing">Trialing</option><option value="suspended">Suspended</option><option value="past_due">Past due</option><option value="cancelled">Cancelled</option></select></div>}/></Panel>
      <label>Lifecycle reason<input value={reason} onChange={e=>setReason(e.target.value)} placeholder="Reason for subscription or security change"/></label>
    </>}
    {tab==="developers"&&<Panel title="Developer credentials"><Rows items={data.credentials} empty="No developer credentials issued." render={key=><div className="org-row" key={key.id}><div><strong>{key.name} · {key.key_prefix}…</strong><small>Org #{key.organization_id} · {key.environment} · {key.usage_count} requests · expires {key.expires_at||"never"}</small></div><span className="status">{key.revoked_at?"Revoked":"Active"}</span>{!key.revoked_at&&<button className="secondary" onClick={()=>revokeCredential(key.id)}>Revoke</button>}</div>}/></Panel>}
    {tab==="security"&&<Panel title="Account and session controls"><Rows items={data.users} empty="No users found." render=u=><div className="org-row" key={u.id}><div><strong>{u.full_name||u.email}</strong><small>{u.email} · {u.platform_role} · {u.organization_count} organizations</small></div><span className="status">{u.is_active?"Active":"Suspended"}</span><button className="secondary" onClick={()=>revokeSessions(u.id)}>Revoke sessions</button></div>}/><p className="tiny">Session revocation increments the account authentication version so existing OneCore access tokens are rejected. MFA factors and recovery codes are not modified.</p><label>Security action reason<input value={reason} onChange={e=>setReason(e.target.value)}/></label></Panel>}
    {tab==="incidents"&&<><Panel title="Create incident"><form className="stack-form" onSubmit={e=>createOperation("incidents",e)}><label>Title<input required minLength="3" value={operation.title} onChange={e=>setOperation(x=>({...x,title:e.target.value}))}/></label><label>Summary<textarea rows="3" value={operation.summary} onChange={e=>setOperation(x=>({...x,summary:e.target.value}))}/></label><label>Severity<select value={operation.severity} onChange={e=>setOperation(x=>({...x,severity:e.target.value}))}>{["low","medium","high","critical"].map(x=><option key={x}>{x}</option>)}</select></label><label>Affected services (comma separated)<input value={operation.affected_services} onChange={e=>setOperation(x=>({...x,affected_services:e.target.value}))}/></label><button className="primary" disabled={busy}>Create incident draft</button></form></Panel><Panel title="Incident register"><Rows items={data.incidents} empty="No incident records." render=row=><div className="org-row" key={row.id}><div><strong>{row.payload.title}</strong><small>{row.payload.severity} · #{row.id} · {row.payload.summary}</small></div><select value={row.status} onChange={e=>transition("incidents",row.id,e.target.value)}>{["draft","investigating","identified","monitoring","resolved","closed"].map(x=><option key={x}>{x}</option>)}</select></div>}/></Panel></>}
    {tab==="maintenance"&&<><Panel title="Schedule maintenance"><form className="stack-form" onSubmit={e=>createOperation("maintenance",e)}><label>Title<input required minLength="3" value={operation.title} onChange={e=>setOperation(x=>({...x,title:e.target.value}))}/></label><label>Summary<textarea rows="3" value={operation.summary} onChange={e=>setOperation(x=>({...x,summary:e.target.value}))}/></label><label>Severity / impact<select value={operation.severity} onChange={e=>setOperation(x=>({...x,severity:e.target.value}))}>{["low","medium","high","critical"].map(x=><option key={x}>{x}</option>)}</select></label><label>Affected services (comma separated)<input value={operation.affected_services} onChange={e=>setOperation(x=>({...x,affected_services:e.target.value}))}/></label><button className="primary" disabled={busy}>Create maintenance draft</button></form></Panel><Panel title="Maintenance register"><Rows items={data.maintenance} empty="No maintenance records." render=row=><div className="org-row" key={row.id}><div><strong>{row.payload.title}</strong><small>{row.payload.summary} · #{row.id}</small></div><select value={row.status} onChange={e=>transition("maintenance",row.id,e.target.value)}>{["draft","scheduled","in_progress","completed","cancelled"].map(x=><option key={x}>{x}</option>)}</select></div>}/></Panel></>}
    {tab==="audit"&&<Panel title="Platform audit trail"><Rows items={data.audit} empty="No audit events found." render=row=><div className="org-row" key={row.id}><div><strong>{row.action}</strong><small>{row.resource_type} #{row.resource_id} · Org {row.organization_id??"platform"} · {new Date(row.created_at).toLocaleString()}</small><small>{row.detail}</small></div></div>}/></Panel>}
  </div>;
}
