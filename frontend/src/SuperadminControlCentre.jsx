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

export default function SuperadminControlCentre({user}) {
  const [tab,setTab] = useState("overview");
  const [data,setData] = useState({overview:null,organizations:[],subscriptions:[],plans:[],users:[],credentials:[],audit:[],incidents:[],maintenance:[],readiness:null});
  const [selectedOrg,setSelectedOrg] = useState("");
  const [memberships,setMemberships] = useState([]);
  const [organizationDraft,setOrganizationDraft] = useState({name:"",slug:"",owner_user_id:"",industry:"general",country:"KE",currency:"KES",timezone:"Africa/Nairobi"});
  const [entitlements,setEntitlements] = useState([]);
  const [planId,setPlanId] = useState("");
  const [planDraft,setPlanDraft] = useState({code:"",name:"",description:"",amount:"0",currency:"KES",interval:"monthly",is_active:true});
  const [planModules,setPlanModules] = useState(["dashboard","reports","documents"]);
  const [startsAt,setStartsAt] = useState("");
  const [endsAt,setEndsAt] = useState("");
  const [status,setStatus] = useState("active");
  const [reason,setReason] = useState("");
  const [credentialDraft,setCredentialDraft] = useState({organization_id:"",name:"",environment:"sandbox",expires_in_days:90});
  const [issuedSecret,setIssuedSecret] = useState("");
  const [operation,setOperation] = useState({title:"",summary:"",severity:"medium",owner:"",affected_services:"",starts_at:"",ends_at:""});
  const [busy,setBusy] = useState(false);
  const [error,setError] = useState("");
  const [notice,setNotice] = useState("");

  const refresh = useCallback(async () => {
    setError("");
    const [overview,organizations,subscriptions,plans,users,credentials,audit,incidents,maintenance,readiness] = await Promise.all([
      api("/api/v1/admin/platform/overview"),
      api("/api/v1/admin/platform/organizations"),
      api("/api/v1/admin/platform/subscriptions"),
      api("/api/v1/admin/platform/subscription-plans"),
      api("/api/v1/admin/platform/users"),
      api("/api/v1/admin/platform/developer-credentials"),
      api("/api/v1/admin/platform/audit"),
      api("/api/v1/admin/platform/operations/incidents"),
      api("/api/v1/admin/platform/operations/maintenance"),
      api("/api/v1/admin/platform/operations/readiness")
    ]);
    setData({overview,organizations,subscriptions,plans,users,credentials,audit,incidents,maintenance,readiness});
    if (!selectedOrg && organizations.length) setSelectedOrg(String(organizations[0].id));
  },[selectedOrg]);

  useEffect(()=>{refresh().catch(e=>setError(e.message));},[refresh]);
  useEffect(()=>{
    if(!selectedOrg)return;
    api("/api/v1/admin/platform/organizations/"+selectedOrg+"/memberships")
      .then(setMemberships).catch(e=>setError(e.message));
    api("/api/v1/admin/platform/organizations/"+selectedOrg+"/entitlements")
      .then(result=>{const raw=result.effective_entitlements?.modules||[];setEntitlements(Array.isArray(raw)?raw:Object.keys(raw).filter(key=>raw[key]===true));})
      .catch(e=>setError(e.message));
  },[selectedOrg]);

  async function act(fn,success) {
    setBusy(true);setError("");setNotice("");
    try { await fn(); await refresh(); setNotice(success); }
    catch(e){setError(e.message);}
    finally{setBusy(false);}
  }
  async function createOrganization(e) {
    e.preventDefault();
    await act(async()=>{const result=await api("/api/v1/admin/platform/organizations",{method:"POST",body:JSON.stringify({...organizationDraft,owner_user_id:Number(organizationDraft.owner_user_id)})});setSelectedOrg(String(result.id));setOrganizationDraft({name:"",slug:"",owner_user_id:"",industry:"general",country:"KE",currency:"KES",timezone:"Africa/Nairobi"});},"Organization created with its initial owner membership.");
  }
  async function updateMembership(member,changes) {
    await act(async()=>{const result=await api("/api/v1/admin/platform/memberships/"+member.id,{method:"PATCH",body:JSON.stringify({role:member.role,branch_scope:member.branch_scope,is_active:member.is_active,...changes})});setMemberships(rows=>rows.map(row=>row.id===member.id?{...row,...result}:row));},"Organization membership updated.");
  }
  async function createPlan(e) {
    e.preventDefault();
    await act(()=>api("/api/v1/admin/platform/subscription-plans",{method:"POST",body:JSON.stringify({...planDraft,amount:Number(planDraft.amount),entitlements:{modules:planModules}})}),"Subscription plan created.");
    setPlanDraft({code:"",name:"",description:"",amount:"0",currency:"KES",interval:"monthly",is_active:true});
  }
  async function assignPlan(e) {
    e.preventDefault();
    await act(()=>api("/api/v1/admin/platform/organizations/"+selectedOrg+"/subscription",{
      method:"PUT",body:JSON.stringify({plan_id:Number(planId),status,starts_at:startsAt?new Date(startsAt).toISOString():null,ends_at:endsAt?new Date(endsAt).toISOString():null})
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
  async function createCredential(e) {
    e.preventDefault(); setIssuedSecret("");
    await act(async()=>{const result=await api("/api/v1/admin/platform/developer-credentials",{method:"POST",body:JSON.stringify({...credentialDraft,organization_id:Number(credentialDraft.organization_id),expires_in_days:Number(credentialDraft.expires_in_days)})});setIssuedSecret(result.secret||"");}, "Developer credential issued. Copy its secret now; it will not be shown again.");
  }
  async function revokeSessions(id) {
    await act(()=>api("/api/v1/admin/platform/users/"+id+"/revoke-sessions?reason="+encodeURIComponent(reason || "Superadmin security action"),{method:"POST"}),"User sessions revoked.");
  }
  async function setOrganizationStatus(org) {
    await act(()=>api("/api/v1/admin/platform/organizations/"+org.id+"/status",{method:"PATCH",body:JSON.stringify({is_active:!org.is_active,reason:reason||"Superadmin organization lifecycle action"})}),"Organization status updated.");
  }
  async function setUserStatus(user) {
    await act(()=>api("/api/v1/admin/platform/users/"+user.id+"/status",{method:"PATCH",body:JSON.stringify({is_active:!user.is_active,reason:reason||"Superadmin account security action"})}),"User status updated.");
  }
  async function createOperation(kind,e) {
    e.preventDefault();
    const payload={...operation,starts_at:operation.starts_at?new Date(operation.starts_at).toISOString():null,ends_at:operation.ends_at?new Date(operation.ends_at).toISOString():null,affected_services:operation.affected_services.split(",").map(x=>x.trim()).filter(Boolean)};
    await act(()=>api("/api/v1/admin/platform/operations/"+kind,{method:"POST",body:JSON.stringify(payload)}),
      kind==="incidents"?"Incident record created as draft.":"Maintenance record created as draft.");
    setOperation({title:"",summary:"",severity:"medium",owner:"",affected_services:"",starts_at:"",ends_at:""});
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
      <Panel title="Create organization"><form className="stack-form" onSubmit={createOrganization}><label>Organization name<input required minLength="2" maxLength="200" value={organizationDraft.name} onChange={e=>setOrganizationDraft(x=>({...x,name:e.target.value}))}/></label><label>Unique slug<input required pattern="[a-z0-9][a-z0-9-]*" value={organizationDraft.slug} onChange={e=>setOrganizationDraft(x=>({...x,slug:e.target.value}))}/></label><label>Initial owner<select required value={organizationDraft.owner_user_id} onChange={e=>setOrganizationDraft(x=>({...x,owner_user_id:e.target.value}))}><option value="">Select an active user</option>{data.users.filter(x=>x.is_active).map(x=><option key={x.id} value={x.id}>{x.email}</option>)}</select></label><label>Industry<input value={organizationDraft.industry} onChange={e=>setOrganizationDraft(x=>({...x,industry:e.target.value}))}/></label><div className="portal-form-grid"><label>Country<input maxLength="2" value={organizationDraft.country} onChange={e=>setOrganizationDraft(x=>({...x,country:e.target.value.toUpperCase()}))}/></label><label>Currency<input maxLength="3" value={organizationDraft.currency} onChange={e=>setOrganizationDraft(x=>({...x,currency:e.target.value.toUpperCase()}))}/></label></div><button className="primary" disabled={busy||!organizationDraft.owner_user_id}>Create organization</button></form></Panel><Panel title="Organization lifecycle"><Rows items={data.organizations} empty="No organizations found." render={org=><div className="org-row" key={org.id}><div><strong>{org.name}</strong><small>{org.slug} · {org.industry} · {org.member_count} members</small></div><span className={"status "+(org.is_active?"online":"offline")}>{org.is_active?"Active":"Suspended"}</span><button className="secondary" onClick={()=>setSelectedOrg(String(org.id))}>Manage</button><button className="secondary" onClick={()=>setOrganizationStatus(org)}>{org.is_active?"Suspend":"Reactivate"}</button></div>}/></Panel>
      <Panel title="Organization memberships"><Rows items={memberships} empty="No memberships found." render={m=><div className="org-row" key={m.id}><div><strong>{m.full_name||m.email||("User #"+m.user_id)}</strong><small>{m.email} · Membership #{m.id}</small></div><select defaultValue={m.role} aria-label={"Role for "+m.email} onChange={e=>updateMembership(m,{role:e.target.value})}>{["org_admin","branch_admin","manager","accountant","staff","viewer","teacher","guardian","school_admin","hr_admin","hr_manager","payroll_manager","payroll_approver","payroll_payment","payroll_accounting","sacco_officer","sacco_manager","sacco_kyc_approver","sacco_treasurer","sacco_auditor"].map(role=><option key={role}>{role}</option>)}</select><input aria-label={"Branch scope for "+m.email} defaultValue={m.branch_scope} onBlur={e=>{if(e.target.value!==m.branch_scope)updateMembership(m,{branch_scope:e.target.value});}}/><button className="secondary" onClick={()=>updateMembership(m,{is_active:!m.is_active})}>{m.is_active?"Deactivate":"Reactivate"}</button></div>}/> </Panel>\n      <Panel title="Organization module entitlements"><label>Organization<select value={selectedOrg} onChange={e=>setSelectedOrg(e.target.value)}>{data.organizations.map(x=><option key={x.id} value={x.id}>{x.name}</option>)}</select></label><form onSubmit={saveEntitlements}><div className="capability-list">{MODULES.map(key=><label key={key}><input type="checkbox" checked={entitlements.includes(key)} onChange={e=>setEntitlements(old=>e.target.checked?[...old,key]:old.filter(x=>x!==key))}/>{label(key)}</label>)}</div><button className="primary" disabled={busy||!selectedOrg}>Save organization override</button></form><p className="tiny">An explicit override replaces the plan's module list for this organization. The backend enforces it on protected business API routes.</p></Panel>
    </>}
    {tab==="subscriptions"&&<>
      <Panel title="Create subscription plan"><form className="stack-form" onSubmit={createPlan}><label>Plan code<input required pattern="[a-z0-9][a-z0-9_-]*" value={planDraft.code} onChange={e=>setPlanDraft(x=>({...x,code:e.target.value}))}/></label><label>Plan name<input required minLength="2" value={planDraft.name} onChange={e=>setPlanDraft(x=>({...x,name:e.target.value}))}/></label><label>Description<textarea rows="2" value={planDraft.description} onChange={e=>setPlanDraft(x=>({...x,description:e.target.value}))}/></label><div className="portal-form-grid"><label>Price<input type="number" min="0" step="0.01" value={planDraft.amount} onChange={e=>setPlanDraft(x=>({...x,amount:e.target.value}))}/></label><label>Currency<input maxLength="3" value={planDraft.currency} onChange={e=>setPlanDraft(x=>({...x,currency:e.target.value.toUpperCase()}))}/></label><label>Billing interval<select value={planDraft.interval} onChange={e=>setPlanDraft(x=>({...x,interval:e.target.value}))}><option value="monthly">Monthly</option><option value="yearly">Yearly</option></select></label></div><label>Included modules</label><div className="capability-list">{MODULES.map(key=><label key={key}><input type="checkbox" checked={planModules.includes(key)} onChange={e=>setPlanModules(old=>e.target.checked?[...old,key]:old.filter(x=>x!==key))}/>{label(key)}</label>)}</div><button className="primary" disabled={busy}>Create plan</button></form><Rows items={data.plans} empty="No subscription plans configured." render= {plan=><div className="org-row" key={plan.id}><div><strong>{plan.name} · {plan.code}</strong><small>{plan.currency} {plan.amount}/{plan.interval} · {Array.isArray(plan.entitlements?.modules)?plan.entitlements.modules.length:Object.keys(plan.entitlements?.modules||{}).filter(key=>plan.entitlements.modules[key]===true).length} modules</small></div><span className="status">{plan.is_active?"Active":"Inactive"}</span></div>}/></Panel><Panel title="Assign or renew subscription"><form className="stack-form" onSubmit={assignPlan}><label>Organization<select required value={selectedOrg} onChange={e=>setSelectedOrg(e.target.value)}>{data.organizations.map(x=><option key={x.id} value={x.id}>{x.name}</option>)}</select></label><label>Plan<select required value={planId} onChange={e=>setPlanId(e.target.value)}><option value="">Choose plan</option>{data.plans.filter(x=>x.is_active).map(x=><option key={x.id} value={x.id}>{x.name} · {x.currency} {x.amount}/{x.interval}</option>)}</select></label><label>Initial status<select value={status} onChange={e=>setStatus(e.target.value)}><option value="active">Active</option><option value="trialing">Trialing</option></select></label><label>Starts at (optional)<input type="datetime-local" value={startsAt} onChange={e=>setStartsAt(e.target.value)}/></label><label>Ends at (optional)<input type="datetime-local" value={endsAt} onChange={e=>setEndsAt(e.target.value)}/></label><button className="primary" disabled={busy||!selectedOrg||!planId}>Assign subscription</button></form></Panel>
      <Panel title="Subscription lifecycle"><Rows items={data.subscriptions} empty="No subscriptions found." render={sub=><div className="org-row" key={sub.id}><div><strong>{sub.organization}</strong><small>{sub.plan} · #{sub.id} · {sub.ends_at||"No end date"}</small></div><span className="status">{label(sub.status)}</span><select aria-label={"Change subscription "+sub.id} defaultValue={sub.status} onChange={e=>changeSubscription(sub.id,e.target.value)}><option value="active">Active</option><option value="trialing">Trialing</option><option value="suspended">Suspended</option><option value="past_due">Past due</option><option value="cancelled">Cancelled</option></select></div>}/></Panel>
      <label>Lifecycle reason<input value={reason} onChange={e=>setReason(e.target.value)} placeholder="Reason for subscription or security change"/></label>
    </>}
    {tab==="developers"&&<><Panel title="Issue developer credential"><form className="stack-form" onSubmit={createCredential}><label>Organization<select required value={credentialDraft.organization_id} onChange={e=>setCredentialDraft(x=>({...x,organization_id:e.target.value}))}><option value="">Choose organization</option>{data.organizations.map(x=><option key={x.id} value={x.id}>{x.name}</option>)}</select></label><label>Credential name<input required minLength="2" maxLength="120" value={credentialDraft.name} onChange={e=>setCredentialDraft(x=>({...x,name:e.target.value}))}/></label><label>Environment<select value={credentialDraft.environment} onChange={e=>setCredentialDraft(x=>({...x,environment:e.target.value}))}><option value="sandbox">Sandbox</option><option value="production">Production</option></select></label><label>Expires in days<input type="number" min="1" max="365" value={credentialDraft.expires_in_days} onChange={e=>setCredentialDraft(x=>({...x,expires_in_days:e.target.value}))}/></label><button className="primary" disabled={busy||!credentialDraft.organization_id}>Issue credential</button></form>{issuedSecret&&<div className="notice info"><strong>Copy this secret now — it is shown once.</strong><code className="secret-value">{issuedSecret}</code><button className="secondary" onClick={()=>{if(navigator.clipboard?.writeText)navigator.clipboard.writeText(issuedSecret);}}>Copy secret</button></div>}</Panel><Panel title="Developer credentials"><Rows items={data.credentials} empty="No developer credentials issued." render={key=><div className="org-row" key={key.id}><div><strong>{key.name} · {key.key_prefix}…</strong><small>Org #{key.organization_id} · {key.environment} · {key.usage_count} requests · expires {key.expires_at||"never"}</small></div><span className="status">{key.revoked_at?"Revoked":"Active"}</span>{!key.revoked_at&&<button className="secondary" onClick={()=>revokeCredential(key.id)}>Revoke</button>}</div>}/></Panel></>}
    {tab==="security"&&<Panel title="Account and session controls"><Rows items={data.users} empty="No users found." render={u=><div className="org-row" key={u.id}><div><strong>{u.full_name||u.email}</strong><small>{u.email} · {u.platform_role} · {u.organization_count} organizations</small></div><span className="status">{u.is_active?"Active":"Suspended"}</span><button className="secondary" onClick={()=>revokeSessions(u.id)}>Revoke sessions</button>{u.platform_role!=="root_superadmin"&&(u.platform_role!=="platform_admin"||user?.platform_role==="root_superadmin")&&u.id!==user?.id&&<button className="secondary" onClick={()=>setUserStatus(u)}>{u.is_active?"Suspend":"Reactivate"}</button>}</div>}/><p className="tiny">Session revocation increments the account authentication version so existing OneCore access tokens are rejected. MFA factors and recovery codes are not modified.</p><label>Security action reason<input value={reason} onChange={e=>setReason(e.target.value)}/></label></Panel>}
    {tab==="incidents"&&<><Panel title="Create incident"><form className="stack-form" onSubmit={e=>createOperation("incidents",e)}><label>Title<input required minLength="3" value={operation.title} onChange={e=>setOperation(x=>({...x,title:e.target.value}))}/></label><label>Summary<textarea rows="3" value={operation.summary} onChange={e=>setOperation(x=>({...x,summary:e.target.value}))}/></label><label>Severity<select value={operation.severity} onChange={e=>setOperation(x=>({...x,severity:e.target.value}))}>{["low","medium","high","critical"].map(x=><option key={x}>{x}</option>)}</select></label><label>Affected services (comma separated)<input value={operation.affected_services} onChange={e=>setOperation(x=>({...x,affected_services:e.target.value}))}/></label><label>Owner<input value={operation.owner} onChange={e=>setOperation(x=>({...x,owner:e.target.value}))}/></label><div className="portal-form-grid"><label>Starts at<input type="datetime-local" value={operation.starts_at} onChange={e=>setOperation(x=>({...x,starts_at:e.target.value}))}/></label><label>Ends at<input type="datetime-local" value={operation.ends_at} onChange={e=>setOperation(x=>({...x,ends_at:e.target.value}))}/></label></div><button className="primary" disabled={busy}>Create incident draft</button></form></Panel><Panel title="Incident register"><Rows items={data.incidents} empty="No incident records." render={row=><div className="org-row" key={row.id}><div><strong>{row.payload.title}</strong><small>{row.payload.severity} · #{row.id} · {row.payload.summary}</small></div><select value={row.status} onChange={e=>transition("incidents",row.id,e.target.value)}>{["draft","investigating","identified","monitoring","resolved","closed"].map(x=><option key={x}>{x}</option>)}</select></div>}/></Panel></>}
    {tab==="maintenance"&&<><Panel title="Operational readiness"><p className="tiny">These are safe runtime configuration checks only. They do not prove a successful backup, restore, scheduled monitor run or production recovery drill.</p><div className="capability-list"><div><span className={data.readiness?.database?.reachable?"check":"status offline"}>{data.readiness?.database?.reachable?"✓":"!"}</span>Database reachable</div><div><span className={data.readiness?.backup?.database_url_configured?"check":"status offline"}>{data.readiness?.backup?.database_url_configured?"✓":"!"}</span>Backup database URL configured in API runtime</div><div><span className="status offline">!</span>Remote backup archive storage is not configured; current script writes local files only</div><div><span className={data.readiness?.backup?.restore_target_configured?"check":"status offline"}>{data.readiness?.backup?.restore_target_configured?"✓":"!"}</span>Restore target configured</div><div><span className={data.readiness?.security?.mfa_encryption_key_configured?"check":"status offline"}>{data.readiness?.security?.mfa_encryption_key_configured?"✓":"!"}</span>MFA encryption key configured</div><div><span className={data.readiness?.monitoring?.healthcheck_url_configured?"check":"status offline"}>{data.readiness?.monitoring?.healthcheck_url_configured?"✓":"!"}</span>Health monitor URL configured in API runtime</div></div><p className="tiny">{data.readiness?.backup?.evidence}</p><p className="tiny">{data.readiness?.monitoring?.evidence}</p></Panel><Panel title="Schedule maintenance"><form className="stack-form" onSubmit={e=>createOperation("maintenance",e)}><label>Title<input required minLength="3" value={operation.title} onChange={e=>setOperation(x=>({...x,title:e.target.value}))}/></label><label>Summary<textarea rows="3" value={operation.summary} onChange={e=>setOperation(x=>({...x,summary:e.target.value}))}/></label><label>Severity / impact<select value={operation.severity} onChange={e=>setOperation(x=>({...x,severity:e.target.value}))}>{["low","medium","high","critical"].map(x=><option key={x}>{x}</option>)}</select></label><label>Affected services (comma separated)<input value={operation.affected_services} onChange={e=>setOperation(x=>({...x,affected_services:e.target.value}))}/></label><label>Owner<input value={operation.owner} onChange={e=>setOperation(x=>({...x,owner:e.target.value}))}/></label><div className="portal-form-grid"><label>Starts at<input type="datetime-local" value={operation.starts_at} onChange={e=>setOperation(x=>({...x,starts_at:e.target.value}))}/></label><label>Ends at<input type="datetime-local" value={operation.ends_at} onChange={e=>setOperation(x=>({...x,ends_at:e.target.value}))}/></label></div><button className="primary" disabled={busy}>Create maintenance draft</button></form></Panel><Panel title="Maintenance register"><Rows items={data.maintenance} empty="No maintenance records." render={row=><div className="org-row" key={row.id}><div><strong>{row.payload.title}</strong><small>{row.payload.summary} · #{row.id}</small></div><select value={row.status} onChange={e=>transition("maintenance",row.id,e.target.value)}>{["draft","scheduled","in_progress","completed","cancelled"].map(x=><option key={x}>{x}</option>)}</select></div>}/></Panel></>}
    {tab==="audit"&&<Panel title="Platform audit trail"><Rows items={data.audit} empty="No audit events found." render={row=><div className="org-row" key={row.id}><div><strong>{row.action}</strong><small>{row.resource_type} #{row.resource_id} · Org {row.organization_id??"platform"} · {new Date(row.created_at).toLocaleString()}</small><small>{row.detail}</small></div></div>}/></Panel>}
  </div>;
}
