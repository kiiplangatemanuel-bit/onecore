import React, { useEffect, useState } from "react";
import { api } from "./api";

export default function AuthRecovery({ mode }) {
  const confirming = mode === "confirm";
  const [email, setEmail] = useState("");
  const [token, setToken] = useState("");
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    if (!confirming) return;
    const value = new URLSearchParams(window.location.hash.replace(/^#/, "")).get("token") || "";
    setToken(value);
    window.history.replaceState({}, "", window.location.pathname);
  }, [confirming]);

  async function submit(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setMessage("");
    try {
      if (confirming) {
        if (!token) throw new Error("This reset link is invalid or incomplete. Request a new link.");
        if (password !== confirmation) throw new Error("The passwords do not match.");
        const result = await api("/api/v1/auth/password-reset/confirm", {
          method: "POST",
          body: JSON.stringify({ token, new_password: password }),
        });
        setMessage(result.message || "Password updated. Sign in again.");
        setToken("");
        setPassword("");
        setConfirmation("");
      } else {
        const result = await api("/api/v1/auth/password-reset/request", {
          method: "POST",
          body: JSON.stringify({ email }),
        });
        setMessage(result.message || "If an account exists, a reset link will be sent.");
        setEmail("");
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="login-shell">
      <section className="login-brand">
        <div className="brand-mark">O</div>
        <p className="eyebrow">ONECORE TECHNOLOGIES</p>
        <h1>Account<br />recovery.</h1>
        <p className="muted-light">Securely regain access to your OneCore workspace.</p>
        <div className="login-foot">Powered by OneCore Technologies Ltd</div>
      </section>
      <section className="login-panel">
        <form className="login-card" onSubmit={submit}>
          <span className="eyebrow">ACCOUNT RECOVERY</span>
          <h2>{confirming ? "Choose a new password" : "Forgot your password?"}</h2>
          <p className="muted">
            {confirming
              ? "Use a valid reset link to update your password."
              : "Enter your account email. If an active account matches, we will send a reset link."}
          </p>
          {error && <div className="alert error" role="alert">{error}</div>}
          {message && <div className="alert success" role="status">{message}</div>}
          {!confirming ? (
            <label>Email address
              <input type="email" autoComplete="email" required value={email}
                onChange={event => setEmail(event.target.value)} placeholder="you@company.com" />
            </label>
          ) : token ? (
            <>
              <label>New password
                <input type="password" autoComplete="new-password" minLength={12} maxLength={128}
                  required value={password} onChange={event => setPassword(event.target.value)} />
              </label>
              <label>Confirm new password
                <input type="password" autoComplete="new-password" minLength={12} maxLength={128}
                  required value={confirmation} onChange={event => setConfirmation(event.target.value)} />
              </label>
            </>
          ) : (
            <div className="alert error" role="alert">The reset link is missing. Request a new one to continue.</div>
          )}
          {(!confirming || token) && <button className="primary full" disabled={busy}>
            {busy ? "Please wait…" : confirming ? "Update password" : "Send reset link"}
          </button>}
          <p className="tiny"><a href="/login">Back to sign in</a>{confirming && <> · <a href="/forgot-password">Request a new link</a></>}</p>
        </form>
      </section>
    </main>
  );
}
