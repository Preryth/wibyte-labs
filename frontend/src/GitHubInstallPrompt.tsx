import { useEffect, useState } from "react";
import { supabase } from "./lib/supabase";
import "./GitHubInstallPrompt.css";

type Installation = {
  connected: boolean;
  installed: boolean | null;
  suspended: boolean;
  github_username?: string;
};

export default function GitHubInstallPrompt({
  settingsOpen, onOpenSettings,
}: {
  settingsOpen: boolean;
  onOpenSettings: () => void;
}) {
  const [status, setStatus] = useState<Installation | null>(null);
  const [error, setError] = useState("");
  const [checking, setChecking] = useState(false);
  const [retry, setRetry] = useState(0);

  useEffect(() => {
    if (settingsOpen) return;
    let active = true;
    let inFlight = false;

    async function check() {
      if (inFlight || document.hidden) return;
      inFlight = true;
      setChecking(true);
      try {
        const { data } = await supabase.auth.getSession();
        if (!data.session) throw new Error("Sign in again to verify your GitHub setup.");
        const response = await fetch(
          `${import.meta.env.VITE_API_URL}/github/installation-status`,
          {
            headers: { Authorization: `Bearer ${data.session.access_token}` },
            cache: "no-store",
          }
        );
        const result = await response.json().catch(() => null);
        if (!response.ok || typeof result?.connected !== "boolean") {
          throw new Error(typeof result?.detail === "string"
            ? result.detail : "Could not verify your GitHub setup. Please retry.");
        }
        if (active) {
          setStatus(result);
          setError("");
        }
      } catch (err) {
        if (active) setError(err instanceof Error ? err.message : "Could not verify GitHub setup.");
      } finally {
        inFlight = false;
        if (active) setChecking(false);
      }
    }

    const onFocus = () => { void check(); };
    const onVisible = () => { if (!document.hidden) void check(); };
    void check();
    const timer = window.setInterval(() => void check(), 60000);
    window.addEventListener("focus", onFocus);
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      active = false;
      window.clearInterval(timer);
      window.removeEventListener("focus", onFocus);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [settingsOpen, retry]);

  if (status?.installed) return null;
  if (!status && !error) {
    return <p role="status">Checking GitHub App setup...</p>;
  }

  return <aside className="wpl-install-card" aria-labelledby="wpl-install-title">
    <span className="wpl-install-eyebrow">BEFORE YOU START</span>
    <h2 id="wpl-install-title">Install the WiByte GitHub App</h2>
    <p>
      Give WiByte access to your GitHub workspace so your projects can be
      committed and pushed to GitHub.
    </p>

    <ol>
      <li>Open the link below and click <strong>Install</strong>.</li>
      <li>Select your GitHub account and allow WiByte access to your workspace repository.</li>
      <li>
        {status?.connected
          ? <>Use the connected account <strong>@{status.github_username}</strong>, then return here.</>
          : <>After installing, open <strong>Settings</strong> and connect the same GitHub account so we can verify it.</>}
      </li>
    </ol>

    {status?.suspended && <p className="wpl-install-warning">
      Your installation is suspended. Restore its access on GitHub.
    </p>}

    <a className="wpl-install-url"
      href="https://github.com/apps/wibyte-labs-development"
      target="_blank" rel="noopener noreferrer">
      https://github.com/apps/wibyte-labs-development
    </a>

    <div className="wpl-install-actions">
      <a className="wpl-install-primary"
        href="https://github.com/apps/wibyte-labs-development"
        target="_blank" rel="noopener noreferrer">
        Install on GitHub ↗
      </a>
      {!status?.connected && <button type="button" onClick={onOpenSettings}>
        Open Settings
      </button>}
      <button type="button" disabled={checking}
        onClick={() => setRetry(value => value + 1)}>
        {checking ? "Checking..." : "Check installation"}
      </button>
    </div>

    {error && <p className="wpl-install-warning" role="alert">{error}</p>}
    <p className="wpl-install-footnote">
      This message disappears once GitHub confirms installation for your connected account.
    </p>
  </aside>;
}
