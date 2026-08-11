import { useEffect, useState } from "react";
import "./SettingsPanel.css";

type StudentSettings = {
  student: {
    id: string;
    name: string | null;
    email: string | null;
    created_at: string;
    updated_at: string;
  };
  github: {
    connected: boolean;
    username: string | null;
    connected_at: string | null;
  };
};

type Props = {
  apiUrl: string;
  onClose: () => void;
};

export default function SettingsPanel({
  apiUrl,
  onClose,
}: Props) {
  const [settings, setSettings] =
    useState<StudentSettings | null>(null);

  const [name, setName] = useState("");
  const [email, setEmail] = useState("");

  const [editingProfile, setEditingProfile] =
    useState(false);

  const [loading, setLoading] =
    useState(true);

  const [saving, setSaving] =
    useState(false);

  const [disconnectingGithub, setDisconnectingGithub] =
    useState(false);

  const [error, setError] =
    useState<string | null>(null);

  const [saved, setSaved] =
    useState(false);

  async function loadSettings() {
    setLoading(true);
    setError(null);

    try {
      const response = await fetch(
        `${apiUrl}/student/settings`
      );

      const data = await response
        .json()
        .catch(() => null);

      if (!response.ok) {
        throw new Error(
          data?.detail ??
            "Failed to load student settings."
        );
      }

      setSettings(data);
      setName(data.student.name ?? "");
      setEmail(data.student.email ?? "");
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Failed to load student settings."
      );
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const response = await fetch(
          `${apiUrl}/student/settings`
        );

        const data = await response
          .json()
          .catch(() => null);

        if (!response.ok) {
          throw new Error(
            data?.detail ??
              "Failed to load student settings."
          );
        }

        if (cancelled) {
          return;
        }

        setSettings(data);
        setName(data.student.name ?? "");
        setEmail(data.student.email ?? "");
      } catch (err) {
        if (!cancelled) {
          setError(
            err instanceof Error
              ? err.message
              : "Failed to load student settings."
          );
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    void load();

    return () => {
      cancelled = true;
    };
  }, [apiUrl]);

  function startEditingProfile() {
    setSaved(false);
    setError(null);

    setName(settings?.student.name ?? "");
    setEmail(settings?.student.email ?? "");

    setEditingProfile(true);
  }

  function cancelEditingProfile() {
    setName(settings?.student.name ?? "");
    setEmail(settings?.student.email ?? "");

    setSaved(false);
    setError(null);
    setEditingProfile(false);
  }

  async function saveSettings() {
    setSaving(true);
    setSaved(false);
    setError(null);

    try {
      const response = await fetch(
        `${apiUrl}/student/settings`,
        {
          method: "PUT",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            name: name.trim() || null,
            email: email.trim() || null,
          }),
        }
      );

      const data = await response
        .json()
        .catch(() => null);

      if (!response.ok) {
        throw new Error(
          data?.detail ??
            "Failed to save student settings."
        );
      }

      setSettings(data);
      setName(data.student.name ?? "");
      setEmail(data.student.email ?? "");
      setSaved(true);
      setEditingProfile(false);
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Failed to save student settings."
      );
    } finally {
      setSaving(false);
    }
  }

  function connectGithub() {
    if (settings?.github.connected) {
      return;
    }

    window.location.href =
      `${apiUrl}/github/connect`;
  }

  async function disconnectGithub() {
    if (!settings?.github.connected) {
      return;
    }

    const confirmed = window.confirm(
      "Disconnect this GitHub account from Wibyte Labs?\n\n" +
        "Wibyte Labs will remove its locally stored GitHub " +
        "OAuth credentials. Your GitHub repositories and " +
        "existing Labs will not be deleted."
    );

    if (!confirmed) {
      return;
    }

    setDisconnectingGithub(true);
    setError(null);
    setSaved(false);

    try {
      const response = await fetch(
        `${apiUrl}/github/connection`,
        {
          method: "DELETE",
        }
      );

      const data = await response
        .json()
        .catch(() => null);

      if (!response.ok) {
        throw new Error(
          data?.detail ??
            "Failed to disconnect GitHub."
        );
      }

      await loadSettings();
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Failed to disconnect GitHub."
      );
    } finally {
      setDisconnectingGithub(false);
    }
  }

  return (
    <div className="settings-overlay">
      <section
        className="settings-panel"
        role="dialog"
        aria-modal="true"
        aria-labelledby="settings-title"
      >
        <header className="settings-header">
          <div>
            <h2 id="settings-title">
              Settings
            </h2>

            <p>
              Manage your student profile and
              connected services.
            </p>
          </div>

          <button
            className="settings-close-button"
            onClick={onClose}
            type="button"
            aria-label="Close settings"
          >
            ×
          </button>
        </header>

        {loading ? (
          <div className="settings-message">
            Loading settings...
          </div>
        ) : (
          <div className="settings-content">
            {error && (
              <div className="settings-error">
                {error}
              </div>
            )}

            <section className="settings-section">
              <div className="settings-section-title">
                Profile
              </div>

              <label className="settings-field">
                <span>Username</span>

                <input
                  value={name}
                  maxLength={100}
                  placeholder="Your username"
                  readOnly={!editingProfile}
                  onChange={(event) =>
                    setName(event.target.value)
                  }
                />
              </label>

              <label className="settings-field">
                <span>Email</span>

                <input
                  type="email"
                  value={email}
                  maxLength={255}
                  placeholder="you@example.com"
                  readOnly={!editingProfile}
                  onChange={(event) =>
                    setEmail(event.target.value)
                  }
                />
              </label>

              <label className="settings-field">
                <span>Student ID</span>

                <input
                  value={
                    settings?.student.id ?? ""
                  }
                  readOnly
                />
              </label>

              {editingProfile ? (
                <div className="settings-save-row">
                  <button
                    className="settings-primary-button"
                    onClick={saveSettings}
                    disabled={saving}
                    type="button"
                  >
                    {saving
                      ? "Saving..."
                      : "Save changes"}
                  </button>

                  <button
                    className="settings-secondary-button"
                    onClick={cancelEditingProfile}
                    disabled={saving}
                    type="button"
                  >
                    Cancel
                  </button>
                </div>
              ) : (
                <div className="settings-save-row">
                  <button
                    className="settings-primary-button"
                    onClick={startEditingProfile}
                    type="button"
                  >
                    Edit
                  </button>

                  {saved && (
                    <span className="settings-saved">
                      Saved
                    </span>
                  )}
                </div>
              )}
            </section>

            <section className="settings-section">
              <div className="settings-section-title">
                GitHub
              </div>

              {settings?.github.connected ? (
                <div className="github-connected-card">
                  <div className="github-status-card">
                    <div>
                      <div className="github-status-title">
                        <span className="status-dot" />
                        Connected
                      </div>

                      <div className="github-username">
                        @{settings.github.username}
                      </div>

                      <div className="github-note">
                        This GitHub account can be used
                        to access repositories from Wibyte
                        Labs.
                      </div>
                    </div>

                    <button
                      className="settings-danger-button"
                      onClick={disconnectGithub}
                      disabled={disconnectingGithub}
                      type="button"
                    >
                      {disconnectingGithub
                        ? "Disconnecting..."
                        : "Delete GitHub connection"}
                    </button>
                  </div>

                  <div className="github-add-section">
                    <div>
                      <div className="github-add-title">
                        Add GitHub connection
                      </div>

                      <div className="github-note">
                        Only one GitHub connection can be
                        active at a time. Delete the current
                        connection before connecting a
                        different GitHub account.
                      </div>
                    </div>

                    <button
                      className="settings-secondary-button"
                      onClick={connectGithub}
                      disabled
                      type="button"
                      title="Delete the current GitHub connection first"
                    >
                      Connect GitHub
                    </button>
                  </div>
                </div>
              ) : (
                <div className="github-status-card github-disconnected-card">
                  <div>
                    <div className="github-status-title">
                      Not connected
                    </div>

                    <div className="github-note">
                      Connect GitHub to access your
                      repositories from Wibyte Labs.
                    </div>
                  </div>

                  <button
                    className="settings-primary-button"
                    onClick={connectGithub}
                    type="button"
                  >
                    Connect GitHub
                  </button>
                </div>
              )}
            </section>
          </div>
        )}
      </section>
    </div>
  );
}