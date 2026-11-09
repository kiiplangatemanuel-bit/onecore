import React, { useEffect, useState } from "react";
import { api, clearToken, getToken } from "./api";

export default function AccountSecurity() {
  const [status, setStatus] = useState(null);
  const [pending, setPending] = useState(null);
  const [recoveryCodes, setRecoveryCodes] = useState([]);
  const [enrollPassword, setEnrollPassword] = useState("");
  const [confirmCode, setConfirmCode] = useState("");
  const [actionPassword, setActionPassword] = useState("");
  const [actionCode, setActionCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [sessionState, setSessionState] = useState(null);
  const [sessionBusy, setSessionBusy] = useState(false);
  const [sessionError, setSessionError] = useState("");

  async function load() {
    setBusy(true); setError(""); setSessionError("");
    try {
      const nextStatus = await api("/api/v1/auth/mfa/status");
      setStatus(nextStatus);
      if (nextStatus.session_management_available === false) {
        setSessionState({ sessions: [], setup_only: true });
      } else {
        setSessionState(await api("/api/v1/auth/sessions"));
      }
    } catch (e) { setError(e.message); }
    finally { setBusy(false); }
  }

  async function refreshSessions() {
    setSessionBusy(true); setSessionError("");
    try { setSessionState(await api("/api/v1/auth/sessions")); }
    catch (e) { setSessionError(e.message); }
    finally { setSessionBusy(false); }
  }

  async function revokeSession(session) {
    if (!window.confirm(session.current
      ? "Revoke this device session? You will be signed out immediately."
      : "Revoke this device session?")) return;
    setSessionBusy(true); setSessionError(""); setNotice("");
    try {
      const result = await api(`/api/v1/auth/sessions/${encodeURIComponent(session.id)}`, { method: "DELETE" });
      if (result.current_session) {
        clearToken();
        setNotice("This device session has been revoked. Sign in again to continue.");
      } else {
        setNotice("The selected device session has been revoked.");
        await refreshSessions();
      }
    } catch (e) { setSessionError(e.message); }
    finally { setSessionBusy(false); }
  }

  async function revokeOtherSessions() {
    if (!window.confirm("Sign out all other active OneCore sessions? This device will remain signed in.")) return;
    setSessionBusy(true); setSessionError(""); setNotice("");
    try {
      const result = await api("/api/v1/auth/sessions/revoke-others", { method: "POST" });
      setNotice(`${result.revoked_count} other session(s) revoked. This device remains signed in.`);
      await refreshSessions();
    } catch (e) { setSessionError(e.message); }
    finally { setSessionBusy(false); }
  }

  const formatSessionDate = value => {
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
  };
  const activeOtherSessions = (sessionState?.sessions || []).filter(session =>
    !session.current && !session.revoked_at && new Date(session.expires_at).getTime() > Date.now()
  );
  useEffect(() => { load(); }, []);

  async function beginEnrollment(e) {
    e.preventDefault(); setBusy(true); setError(""); setNotice("");
    try {
      setPending(await api("/api/v1/auth/mfa/enroll", {
        method: "POST", body: JSON.stringify({ password: enrollPassword })
      }));
      setEnrollPassword(""); setConfirmCode("");
      setNotice("Add the secret to an authenticator app, then confirm with its current six-digit code.");
    } catch (e) { setError(e.message); }
    finally { setBusy(false); }
  }

  async function confirmEnrollment(e) {
    e.preventDefault(); setBusy(true); setError(""); setNotice("");
    try {
      const result = await api("/api/v1/auth/mfa/confirm", {
        method: "POST", body: JSON.stringify({ code: confirmCode })
      });
      setRecoveryCodes(result.recovery_codes || []);
      setPending(null);
      setStatus({ enabled: true, setup_pending: false, recovery_codes_remaining: (result.recovery_codes || []).length });
      clearToken();
      setNotice("MFA is enabled. Existing sessions were revoked. Save the recovery codes below, then sign in again using a new authenticator code.");
    } catch (e) { setError(e.message); }
    finally { setBusy(false); }
  }

  async function rotateCodes(e) {
    e.preventDefault(); setBusy(true); setError(""); setNotice("");
    try {
      const result = await api("/api/v1/auth/mfa/recovery-codes/rotate", {
        method: "POST", body: JSON.stringify({ password: actionPassword, code: actionCode })
      });
      setRecoveryCodes(result.recovery_codes || []);
      setActionPassword(""); setActionCode("");
      setStatus(old => ({ ...old, recovery_codes_remaining: (result.recovery_codes || []).length }));
      setNotice("New recovery codes generated. All previous unused codes are revoked.");
    } catch (e) { setError(e.message); }
    finally { setBusy(false); }
  }

  async function disable(e) {
    e.preventDefault();
    if (!window.confirm("Disable multi-factor authentication for this account?")) return;
    setBusy(true); setError(""); setNotice("");
    try {
      await api("/api/v1/auth/mfa/disable", {
        method: "POST", body: JSON.stringify({ password: actionPassword, code: actionCode })
      });
      setRecoveryCodes([]); setPending(null);
      setStatus({ enabled: false, setup_pending: false, recovery_codes_remaining: 0 });
      setActionPassword(""); setActionCode("");
      clearToken();
      setNotice("MFA has been disabled and existing sessions were revoked. Sign in again.");
    } catch (e) { setError(e.message); }
    finally { setBusy(false); }
  }

  const signedIn = Boolean(getToken());
  const codeBlock = recoveryCodes.length > 0 ? (
    <section className="panel">
      <h3>Save your recovery codes</h3>
      <p className="muted">Each code works once. These codes are shown only after generation; store them somewhere secure and do not share them.</p>
      <pre className="recovery-codes">{recoveryCodes.join("\n")}</pre>
      <button className="secondary" type="button" onClick={() => navigator.clipboard?.writeText(recoveryCodes.join("\n"))}>Copy recovery codes</button>
    </section>
  ) : null;

  if (!status && busy) return <section className="panel"><p>Loading account security…</p></section>;

  return <div className="workspace-stack">
    <div className="page-heading"><div><p className="eyebrow">ACCOUNT SECURITY</p><h1>Multi-factor authentication</h1><p className="muted">Protect this OneCore account with an authenticator app and one-time recovery codes.</p></div><button className="secondary" type="button" onClick={load} disabled={busy}>Refresh status</button></div>
    {error && <div className="alert error" role="alert">{error}</div>}
    {notice && <div className="notice info" role="status">{notice}</div>}
    {!signedIn ? <section className="panel"><h3>Sign in again</h3><p className="muted">The security change revoked the current session. Save any recovery codes above, then sign in again to continue.</p><a className="primary link-button" href="/login">Return to sign in</a></section> : status?.enabled ? <>
      <section className="panel">
        <div className="panel-head"><div><h3>Authenticator protection is enabled</h3><p className="muted">Password sign-in now requires a second factor.</p></div><span className="status online"><i/>Enabled</span></div>
        <p><strong>{status.recovery_codes_remaining}</strong> unused recovery codes remain.</p>
      </section>
      <section className="panel">
        <h3>Rotate recovery codes</h3>
        <p className="muted">Confirm your password and a current authenticator code or unused recovery code. Previous unused recovery codes will be revoked.</p>
        <form className="stack-form" onSubmit={rotateCodes}>
          <label>Current password<input type="password" autoComplete="current-password" required value={actionPassword} onChange={e=>setActionPassword(e.target.value)}/></label>
          <label>Authenticator or recovery code<input required minLength={6} maxLength={64} autoComplete="one-time-code" value={actionCode} onChange={e=>setActionCode(e.target.value)}/></label>
          <button className="primary" disabled={busy}>{busy?"Working…":"Generate new recovery codes"}</button>
        </form>
      </section>
      <section className="panel">
        <h3>Disable MFA</h3>
        <p className="muted">Disabling MFA requires password re-authentication and a current second factor. All existing sessions will be revoked.</p>
        <form className="stack-form" onSubmit={disable}>
          <label>Current password<input type="password" autoComplete="current-password" required value={actionPassword} onChange={e=>setActionPassword(e.target.value)}/></label>
          <label>Authenticator or recovery code<input required minLength={6} maxLength={64} autoComplete="one-time-code" value={actionCode} onChange={e=>setActionCode(e.target.value)}/></label>
          <button className="secondary" disabled={busy}>Disable multi-factor authentication</button>
        </form>
      </section>
    </> : <>
      <section className="panel">
        <div className="panel-head"><div><h3>Authenticator app</h3><p className="muted">Use any RFC 6238 compatible authenticator that supports six-digit TOTP codes.</p></div><span className="status checking"><i/>Not enabled</span></div>
        {!pending ? <form className="stack-form" onSubmit={beginEnrollment}>
          <label>Confirm your current password<input type="password" autoComplete="current-password" required value={enrollPassword} onChange={e=>setEnrollPassword(e.target.value)}/></label>
          <button className="primary" disabled={busy}>{busy?"Preparing…":"Set up authenticator"}</button>
        </form> : <>
          <p>Enter this secret manually in your authenticator app. The enrollment expires in ten minutes.</p>
          <label>Secret key</label><pre className="recovery-codes">{pending.secret}</pre>
          <label>Authenticator provisioning URI</label><pre className="recovery-codes">{pending.otpauth_uri}</pre>
          <form className="stack-form" onSubmit={confirmEnrollment}>
            <label>Current six-digit authenticator code<input required inputMode="numeric" autoComplete="one-time-code" pattern="[0-9]{6}" minLength={6} maxLength={6} value={confirmCode} onChange={e=>setConfirmCode(e.target.value)}/></label>
            <button className="primary" disabled={busy}>{busy?"Verifying…":"Confirm and enable MFA"}</button>
          </form>
        </>}
      </section>
    </>}
    {sessionState?.setup_only ? <section className="panel">
      <h3>Device sessions</h3>
      <p className="muted">Session inventory becomes available after you complete privileged MFA enrollment and sign in again.</p>
    </section> : sessionState ? <section className="panel">
      <div className="panel-head">
        <div><h3>Signed-in devices and sessions</h3><p className="muted">Review recent account access and revoke devices you no longer use.</p></div>
        <button className="secondary" type="button" onClick={refreshSessions} disabled={sessionBusy}>{sessionBusy ? "Refreshing…" : "Refresh"}</button>
      </div>
      {sessionError && <div className="alert error" role="alert">{sessionError}</div>}
      {sessionState.legacy_session && <p className="notice info" role="status">This sign-in predates device tracking. Sign in again to identify and revoke the current device or use the sign-out-other-sessions action.</p>}
      <div className="session-toolbar">
        <span className="muted">{activeOtherSessions.length} other active session(s)</span>
        <button className="secondary" type="button" onClick={revokeOtherSessions} disabled={sessionBusy || sessionState.legacy_session || activeOtherSessions.length === 0}>Sign out other devices</button>
      </div>
      {(sessionState.sessions || []).length === 0 ? <p className="muted">No tracked sessions are available for this account yet.</p> : <div className="session-list">
        {sessionState.sessions.map(session => {
          const expired = new Date(session.expires_at).getTime() <= Date.now();
          const stateLabel = session.revoked_at ? "Revoked" : expired ? "Expired" : session.current ? "This device" : "Active";
          return <article className="session-item" key={session.id}>
            <div className="session-item-head">
              <div><strong>{session.device_name || "Unnamed device"}</strong><p className="muted">{session.user_agent || "Device details not supplied"}</p></div>
              <span className={session.revoked_at || expired ? "status checking" : "status online"}><i/>{stateLabel}</span>
            </div>
            <div className="session-item-meta">
              <span>Method: <strong>{session.auth_method}</strong></span>
              <span>MFA: <strong>{session.mfa_verified ? "Verified" : "Not verified"}</strong></span>
              <span>Last seen: <strong>{formatSessionDate(session.last_seen_at)}</strong></span>
              <span>Expires: <strong>{formatSessionDate(session.expires_at)}</strong></span>
              {session.revoked_at && <span>Revoked: <strong>{formatSessionDate(session.revoked_at)}</strong></span>}
            </div>
            {!session.revoked_at && !expired && <button className="secondary" type="button" onClick={() => revokeSession(session)} disabled={sessionBusy}>Revoke session</button>}
          </article>;
        })}
      </div>}
    </section> : null}
    {codeBlock}
    <p className="tiny">If MFA enrollment is unavailable, the deployment operator must configure the dedicated MFA_ENCRYPTION_KEY secret. Do not send the TOTP seed or recovery codes to support.</p>
  </div>;
}
