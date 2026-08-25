import {
  FormEvent,
  useState,
} from "react";

import {
  supabase,
} from "./lib/supabase";

import "./LoginScreen.css";


type Mode =
  | "sign-in"
  | "sign-up"
  | "forgot-password";


function LoginScreen() {
  const [
    mode,
    setMode,
  ] = useState<Mode>(
    "sign-in"
  );

  const [
    email,
    setEmail,
  ] = useState("");

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
    message,
    setMessage,
  ] = useState<string | null>(
    null
  );

  const [
    errorMessage,
    setErrorMessage,
  ] = useState<string | null>(
    null
  );


  function changeMode(
    nextMode: Mode
  ) {
    setMode(nextMode);
    setPassword("");
    setConfirmPassword("");
    setMessage(null);
    setErrorMessage(null);
  }


  async function handleSubmit(
    event: FormEvent<HTMLFormElement>
  ) {
    event.preventDefault();

    if (submitting) {
      return;
    }

    const normalisedEmail =
      email.trim().toLowerCase();

    if (!normalisedEmail) {
      setErrorMessage(
        "Enter your email address."
      );
      return;
    }

    if (mode !== "forgot-password" && !password) {
      setErrorMessage(
        "Enter your password."
      );
      return;
    }

    if (
      mode === "sign-up" &&
      password.length < 8
    ) {
      setErrorMessage(
        "Your password must be at least 8 characters long."
      );
      return;
    }

    if (
      mode === "sign-up" &&
      password !== confirmPassword
    ) {
      setErrorMessage(
        "The passwords do not match."
      );
      return;
    }

    setSubmitting(true);
    setMessage(null);
    setErrorMessage(null);

    try {
      if (mode === "sign-in") {
        const {
          error,
        } =
          await supabase.auth.signInWithPassword({
            email: normalisedEmail,
            password,
          });

        if (error) {
          throw error;
        }

        return;
      }

      if (mode === "sign-up") {
        const {
          data,
          error,
        } =
          await supabase.auth.signUp({
            email: normalisedEmail,
            password,
            options: {
              emailRedirectTo:
                window.location.origin,
            },
          });

        if (error) {
          throw error;
        }

        if (!data.session) {
          setMessage(
            "Account created. Check your email to confirm your address, then sign in."
          );
          setMode("sign-in");
        } else {
          setMessage(
            "Account created. Your account is awaiting approval."
          );
        }

        return;
      }

      const {
        error,
      } =
        await supabase.auth.resetPasswordForEmail(
          normalisedEmail,
          {
            redirectTo:
              `${window.location.origin}/reset-password`,
          }
        );

      if (error) {
        throw error;
      }

      setMessage(
        "If an account exists for this email address, a password reset link has been sent."
      );

    } catch (error) {
      console.error(
        "Authentication request failed:",
        error
      );

      setErrorMessage(
        error instanceof Error
          ? error.message
          : "Something went wrong. Please try again."
      );
    } finally {
      setSubmitting(false);
    }
  }


  const title =
    mode === "sign-in"
      ? "Sign in"
      : mode === "sign-up"
        ? "Create your account"
        : "Reset your password";


  return (
    <main className="login-screen">
      <section className="login-card">
        <div className="login-brand">
          <span className="login-brand-mark">
            W
          </span>

          <h1>
            WiByte Labs
          </h1>

          <p>
            Your browser-based programming workspace.
          </p>
        </div>

        <div className="login-divider" />

        <h2 className="login-form-title">
          {title}
        </h2>

        <form
          className="login-form"
          onSubmit={(event) =>
            void handleSubmit(event)
          }
        >
          <label className="login-field">
            <span>Email</span>
            <input
              type="email"
              autoComplete="email"
              value={email}
              onChange={(event) =>
                setEmail(event.target.value)
              }
              disabled={submitting}
              required
            />
          </label>

          {mode !== "forgot-password" && (
            <label className="login-field">
              <span>Password</span>
              <input
                type="password"
                autoComplete={
                  mode === "sign-up"
                    ? "new-password"
                    : "current-password"
                }
                value={password}
                onChange={(event) =>
                  setPassword(event.target.value)
                }
                disabled={submitting}
                required
              />
            </label>
          )}

          {mode === "sign-up" && (
            <label className="login-field">
              <span>Confirm password</span>
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
          )}

          {errorMessage && (
            <p
              className="login-error"
              role="alert"
            >
              {errorMessage}
            </p>
          )}

          {message && (
            <p
              className="login-message"
              role="status"
            >
              {message}
            </p>
          )}

          <button
            className="login-submit-button"
            disabled={submitting}
            type="submit"
          >
            {submitting
              ? "Please wait..."
              : mode === "sign-in"
                ? "Sign in"
                : mode === "sign-up"
                  ? "Create account"
                  : "Send reset link"}
          </button>
        </form>

        <div className="login-actions">
          {mode === "sign-in" && (
            <>
              <button
                type="button"
                onClick={() =>
                  changeMode("forgot-password")
                }
              >
                Forgot password?
              </button>

              <p>
                Don't have an account?{" "}
                <button
                  type="button"
                  onClick={() =>
                    changeMode("sign-up")
                  }
                >
                  Create an account
                </button>
              </p>
            </>
          )}

          {mode === "sign-up" && (
            <p>
              Already have an account?{" "}
              <button
                type="button"
                onClick={() =>
                  changeMode("sign-in")
                }
              >
                Sign in
              </button>
            </p>
          )}

          {mode === "forgot-password" && (
            <button
              type="button"
              onClick={() =>
                changeMode("sign-in")
              }
            >
              Back to sign in
            </button>
          )}
        </div>
      </section>
    </main>
  );
}


export default LoginScreen;
