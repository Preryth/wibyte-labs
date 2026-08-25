import {
  FormEvent,
  useState,
} from "react";

import {
  supabase,
} from "./lib/supabase";

import "./LoginScreen.css";


export default function ResetPasswordScreen() {
  const [
    password,
    setPassword,
  ] = useState("");

  const [
    confirmPassword,
    setConfirmPassword,
  ] = useState("");

  const [
    submitting,
    setSubmitting,
  ] = useState(false);

  const [
    errorMessage,
    setErrorMessage,
  ] = useState<string | null>(null);

  const [
    message,
    setMessage,
  ] = useState<string | null>(null);


  async function submit(
    event: FormEvent<HTMLFormElement>
  ) {
    event.preventDefault();

    if (password.length < 8) {
      setErrorMessage(
        "Your password must be at least 8 characters long."
      );
      return;
    }

    if (password !== confirmPassword) {
      setErrorMessage(
        "The passwords do not match."
      );
      return;
    }

    setSubmitting(true);
    setErrorMessage(null);

    try {
      const {
        error,
      } =
        await supabase.auth.updateUser({
          password,
        });

      if (error) {
        throw error;
      }

      setMessage(
        "Password reset successfully. You can now continue to WiByte Labs."
      );

      window.history.replaceState(
        {},
        "",
        "/"
      );

    } catch (error) {
      setErrorMessage(
        error instanceof Error
          ? error.message
          : "Unable to reset your password."
      );
    } finally {
      setSubmitting(false);
    }
  }


  return (
    <main className="login-screen">
      <section className="login-card">
        <div className="login-brand">
          <span className="login-brand-mark">
            W
          </span>
          <h1>Reset password</h1>
          <p>
            Choose a new password for your WiByte Labs account.
          </p>
        </div>

        <div className="login-divider" />

        <form
          className="login-form"
          onSubmit={(event) =>
            void submit(event)
          }
        >
          <label className="login-field">
            <span>New password</span>
            <input
              type="password"
              autoComplete="new-password"
              value={password}
              onChange={(event) =>
                setPassword(event.target.value)
              }
              disabled={submitting}
              required
            />
          </label>

          <label className="login-field">
            <span>Confirm new password</span>
            <input
              type="password"
              autoComplete="new-password"
              value={confirmPassword}
              onChange={(event) =>
                setConfirmPassword(event.target.value)
              }
              disabled={submitting}
              required
            />
          </label>

          {errorMessage && (
            <p className="login-error">
              {errorMessage}
            </p>
          )}

          {message && (
            <p className="login-message">
              {message}
            </p>
          )}

          <button
            className="login-submit-button"
            type="submit"
            disabled={submitting}
          >
            {submitting
              ? "Please wait..."
              : "Reset password"}
          </button>
        </form>
      </section>
    </main>
  );
}
