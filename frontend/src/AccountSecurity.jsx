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

  async function load() {
    setBusy(true); setError("");
    try { setStatus(await api("/api/v1/auth/mfa/status")); }
    catch (e) { setError(e.message); }
    finally { setBusy(false); }
  }
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
    {codeBlock}
    <p className="tiny">If MFA enrollment is unavailable, the deployment operator must configure the dedicated MFA_ENCRYPTION_KEY secret. Do not send the TOTP seed or recovery codes to support.</p>
  </div>;
}
