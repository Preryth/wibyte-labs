import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { supabase } from "./lib/supabase";
import "./LoginScreen.css";

// Reuse initialization if React runs the effect twice in development.
let recoveryInitialization: Promise<void> | undefined;

function initializeRecovery(): Promise<void> {
  if (!recoveryInitialization) {
    recoveryInitialization = (async () => {
      const params = new URLSearchParams(window.location.hash.slice(1));
      const accessToken = params.get("access_token");
      const refreshToken = params.get("refresh_token");
      const type = params.get("type");

      // Remove credentials from the address bar.
      window.history.replaceState({}, "", "/reset-password");

      if (
        params.has("error") ||
        type !== "recovery" ||
        !accessToken ||
        !refreshToken
      ) {
        throw new Error(
          "This reset link is missing, invalid, or expired. Request a new password reset email."
        );
      }

      const { data, error } = await supabase.auth.setSession({
        access_token: accessToken,
        refresh_token: refreshToken,
      });

      if (error || !data.session) {
        throw new Error(
          "Unable to verify this reset link. Request a new password reset email."
        );
      }
    })();
  }

  return recoveryInitialization;
}

export default function ResetPasswordScreen() {
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [ready, setReady] = useState(false);
  const [checking, setChecking] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [complete, setComplete] = useState(false);

  useEffect(() => {
    let active = true;

    initializeRecovery()
      .then(() => {
        if (active) setReady(true);
      })
      .catch((error: unknown) => {
        if (active) {
          setErrorMessage(
            error instanceof Error ? error.message : "Invalid reset link."
          );
        }
      })
      .finally(() => {
        if (active) setChecking(false);
      });

    return () => {
      active = false;
    };
  }, []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!ready || submitting || complete) return;

    if (password.length < 8) {
      setErrorMessage("Your password must be at least 8 characters long.");
      return;
    }
    if (password !== confirmPassword) {
      setErrorMessage("The passwords do not match.");
      return;
    }

    setSubmitting(true);
    setErrorMessage(null);

    try {
      const { error } = await supabase.auth.updateUser({ password });
      if (error) throw error;

      setPassword("");
      setConfirmPassword("");
      setComplete(true);
    } catch (error) {
      setErrorMessage(
        error instanceof Error ? error.message : "Unable to reset your password."
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="login-screen">
      <section className="login-card">
        <div className="login-brand">
          <span className="login-brand-mark">W</span>
          <h1>Reset password</h1>
          <p>Choose a new password for your WiByte Labs account.</p>
        </div>

        <div className="login-divider" />

        {checking && <p>Verifying your reset link...</p>}
        {errorMessage && <p className="login-error">{errorMessage}</p>}

        {complete ? (
          <p className="login-message">
            Password updated successfully. <a href="/">Continue to WiByte Labs</a>
          </p>
        ) : ready ? (
          <form className="login-form" onSubmit={(event) => void submit(event)}>
            <label className="login-field">
              <span>New password</span>
              <input
                type="password"
                autoComplete="new-password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                disabled={submitting}
                minLength={8}
                required
              />
            </label>

            <label className="login-field">
              <span>Confirm new password</span>
              <input
                type="password"
                autoComplete="new-password"
                value={confirmPassword}
                onChange={(event) => setConfirmPassword(event.target.value)}
                disabled={submitting}
                minLength={8}
                required
              />
            </label>

            <button
              className="login-submit-button"
              type="submit"
              disabled={submitting}
            >
              {submitting ? "Updating password..." : "Reset password"}
            </button>
          </form>
        ) : !checking ? (
          <a href="/">Return to login to request a new reset email</a>
        ) : null}
      </section>
    </main>
  );
}
