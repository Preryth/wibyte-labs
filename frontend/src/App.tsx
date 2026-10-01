import {
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";

import type {
  Session,
  User,
} from "@supabase/supabase-js";

import Terminal, {
  type TerminalHandle,
} from "./Terminal";

import CodeEditor from "./CodeEditor";
import SettingsPanel from "./SettingsPanel";

import "./App.css";
import LoginScreen from "./LoginScreen";
import ResetPasswordScreen from "./ResetPasswordScreen";
import { supabase } from "./lib/supabase";



function defaultPythonFilename(path: string): string {
  const name = path.slice(path.lastIndexOf("/") + 1);
  return name && !name.includes(".") ? `${path}.py` : path;
}

const API_URL =
  import.meta.env.VITE_API_URL;

async function apiFetch(input: RequestInfo | URL, init: RequestInit = {}) {
  const { data } = await supabase.auth.getSession();
  const headers = new Headers(init.headers);
  if (data.session?.access_token) {
    headers.set("Authorization", `Bearer ${data.session.access_token}`);
  }
  return window.fetch(input, { ...init, headers });
}


type LabFile = {
  name: string;
  type: "file" | "directory";
};

type GitHubRepository = {
  id: string;
  github_repo_id: string;
  owner: string;
  name: string;
  full_name: string;
  default_branch: string;
  private?: boolean;
  html_url?: string | null;
  description?: string | null;
};





type WorkspaceDirectoryState = {
  loading: boolean;
  items: LabFile[];
  error: string | null;
};

type GitStatus = {
  branch: string | null;
  ahead: number;
  behind: number;
  clean: boolean;
  changes: {
    index: string;
    worktree: string;
    path: string;
  }[];
};


function WelcomeGuide() {
  return (
    <article className="welcome-guide">
      <h2>Welcome to WiByte Python Lab</h2>
      <p>Your place to write, run, and practise Python.</p>

      <h3>Start coding</h3>
      <ol>
        <li>In Workspace, click <strong>Create File</strong> to create a file,
          or <strong>Upload</strong> to bring one from your device.</li>
        <li>Names without an extension get <strong>.py</strong>.
          Explicit extensions such as .txt stay unchanged.</li>
        <li>Select a file, write your code, and click <strong>Run</strong>.
          Run saves the current file first.</li>
        <li>Read output and enter answers in the terminal.
          Use <strong>Stop</strong> to end a running program.</li>
        <li>For Turtle or Tkinter, click <strong>GUI</strong> to see the window.
          Open GUI before running graphical programs manually in the terminal.</li>
      </ol>

      <h3>Before you finish</h3>
      <ol>
        <li>Click <strong>Save</strong> for your latest edits.</li>
        <li>In the GitHub panel, click <strong>Commit</strong> and enter a short
          description of your changes.</li>
        <li>Then click <strong>Push</strong> and wait for confirmation.
          Commit alone does not upload your work to GitHub.</li>
        <li>After a successful push, you can close the lab.</li>
      </ol>

      <p>If GitHub is not connected, open <strong>Settings</strong> to connect it.
        You can also save a local copy: hover over a Workspace file and click
        its <strong>down arrow</strong> to download the saved version.</p>

      <p className="welcome-notice">
        Lab files are temporary. Save and push regularly: labs close after
        30 minutes of inactivity. Save alone does not preserve work after
        the lab is removed.
      </p>

      <p>Uploads and downloads support files up to 10 MB.
        Use <strong>Help</strong> above the editor to reopen this guide.</p>
    </article>
  );
}

function LabApp({
  currentUser,
  handleSignOut,
}: {
  currentUser: User | null;
  handleSignOut: () => Promise<void>;
}) {
  const [
    backendStatus,
    setBackendStatus,
  ] = useState(
    "Checking backend..."
  );

  const [editorWidth, setEditorWidth] = useState(60);
  const [sidebarWidth, setSidebarWidth] = useState(310);


  const uploadInputRef = useRef<HTMLInputElement | null>(null);
  const [uploadingFile, setUploadingFile] = useState(false);

  async function uploadWorkspaceFile(file: File) {
    if (!labId || uploadingFile) return;
    if (file.size > 10 * 1024 * 1024) {
      alert("Maximum file size is 10 MB.");
      return;
    }

    setUploadingFile(true);
    try {
      const response = await apiFetch(
        `${API_URL}/labs/${labId}/upload?path=${encodeURIComponent(defaultPythonFilename(file.name))}`,
        {
          method: "POST",
          headers: { "Content-Type": "application/octet-stream" },
          body: file,
        },
      );
      if (!response.ok) {
        const error = await response.json().catch(() => null);
        throw new Error(error?.detail ?? "Upload failed.");
      }
      await refreshWorkspaceTree();
      if (activeGitHubRepositoryId) void loadGitStatus();
    } catch (error) {
      alert(error instanceof Error ? error.message : "Upload failed.");
    } finally {
      setUploadingFile(false);
    }
  }

  async function downloadWorkspaceFile(path: string) {
    if (!labId) return;
    try {
      const response = await apiFetch(
        `${API_URL}/labs/${labId}/download?path=${encodeURIComponent(path)}`,
      );
      if (!response.ok) {
        const error = await response.json().catch(() => null);
        throw new Error(error?.detail ?? "Download failed.");
      }

      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement("a");
      link.href = url;
      link.download = path.split("/").pop() || "download";
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 60000);
    } catch (error) {
      alert(error instanceof Error ? error.message : "Download failed.");
    }
  }

  const welcomeDialogRef = useRef<HTMLDialogElement | null>(null);

  const gitActionBusyRef = useRef(false);
  const gitActionVersionRef = useRef(0);
  const gitStatusPollingRef = useRef(false);

  const [labConflictIds, setLabConflictIds] = useState<string[] | null>(null);
  const [labNotice, setLabNotice] = useState<string | null>(null);
  const labConflictDialogRef = useRef<HTMLDialogElement | null>(null);
  const labCreationBusyRef = useRef(false);

  useEffect(() => {
    const dialog = labConflictDialogRef.current;
    if (!dialog) return;
    if (labConflictIds && !dialog.open) dialog.showModal();
    if (!labConflictIds && dialog.open) dialog.close();
  }, [labConflictIds]);

  const [accessToken, setAccessToken] = useState("");

  useEffect(() => {
    let active = true;
    void supabase.auth.getSession().then(({ data }) => {
      if (active) setAccessToken(data.session?.access_token ?? "");
    });
    const { data: listener } = supabase.auth.onAuthStateChange((_event, session) => {
      if (active) setAccessToken(session?.access_token ?? "");
    });
    return () => { active = false; listener.subscription.unsubscribe(); };
  }, []);


  const [
    labId,
    setLabId,
  ] = useState<string | null>(
    null
  );


  const [
    creatingLab,
    setCreatingLab,
  ] = useState(false);

  const [
    openingGui,
    setOpeningGui,
  ] = useState(false);

  const [
    settingsOpen,
    setSettingsOpen,
  ] = useState(false);

  const [
    githubConnected,
    setGithubConnected,
  ] = useState(false);

  const [
    githubUsername,
    setGithubUsername,
  ] = useState<string | null>(null);

  const [
    githubRepositories,
    setGithubRepositories,
  ] = useState<GitHubRepository[]>([]);

  const [
    githubLoading,
    setGithubLoading,
  ] = useState(false);

  const [
    githubError,
    setGithubError,
  ] = useState<string | null>(null);






  const [
    activeGitHubRepositoryId,
    setActiveGitHubRepositoryId,
  ] = useState<string | null>(null);



  const [
    expandedWorkspaceDirectories,
    setExpandedWorkspaceDirectories,
  ] = useState<Record<string, boolean>>({});

  const [
    workspaceDirectories,
    setWorkspaceDirectories,
  ] = useState<Record<string, WorkspaceDirectoryState>>({});

  const [
    gitStatus,
    setGitStatus,
  ] = useState<GitStatus | null>(null);

  const [
    gitDiff,
    setGitDiff,
  ] = useState<string | null>(null);

  const [
    gitLoading,
    setGitLoading,
  ] = useState(false);
  const [
    files,
    setFiles,
  ] = useState<LabFile[]>([]);


  const [
    selectedFile,
    setSelectedFile,
  ] = useState<string | null>(
    null
  );


  const [
    fileContent,
    setFileContent,
  ] = useState("");


  const [
    loadingFile,
    setLoadingFile,
  ] = useState(false);


  const [
    savingFile,
    setSavingFile,
  ] = useState(false);


  const [
    running,
    setRunning,
  ] = useState(false);


  const terminalRef =
    useRef<TerminalHandle | null>(
      null
    );

  /* Prevent Git status polling errors while a Lab is intentionally closing. */
  const closingLabRef = useRef(false);
  useEffect(() => {
    if (!labId) return;
    let cancelled = false;
    let checking = false;

    async function checkLabSession() {
      if (checking || closingLabRef.current) return;
      checking = true;
      try {
        const response = await apiFetch(`${API_URL}/labs/${labId}/session`);
        if (response.status === 404 && !cancelled && !closingLabRef.current) {
          closingLabRef.current = true;
          setLabId(null);
          setActiveGitHubRepositoryId(null);
          setFiles([]);
          setSelectedFile(null);
          setFileContent("");
          setRunning(false);
          setGitStatus(null);
          setGitDiff(null);
          setExpandedWorkspaceDirectories({});
          setWorkspaceDirectories({});
          setLabNotice(
            "This lab has closed or was replaced from another tab or device. You can close this tab or create a lab here."
          );
        }
      } catch (error) {
        console.warn("Could not check lab session:", error);
      } finally {
        checking = false;
      }
    }

    void checkLabSession();
    const timer = window.setInterval(() => void checkLabSession(), 4000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [labId]);




  /*
   * -------------------------------------------------------
   * Lab activity tracking
   * -------------------------------------------------------
   *
   * Editor changes can happen many times per second.
   *
   * We therefore:
   *
   * 1. Send activity immediately on the first edit.
   * 2. While the student keeps typing, send at most
   *    one activity request every 10 seconds.
   *
   * This prevents one HTTP request per keystroke while
   * still ensuring that continuous coding keeps the
   * lab's last_activity_at timestamp fresh.
   */

  const lastActivitySentAtRef =
    useRef(0);


  const activityTimerRef =
    useRef<ReturnType<
      typeof setTimeout
    > | null>(null);


  const reportLabActivity =
    useCallback(
      async (id: string) => {
        try {
          const response =
            await apiFetch(
              `${API_URL}/labs/${id}/activity`,
              {
                method: "POST",
              }
            );


          if (!response.ok) {
            console.warn(
              "Failed to record lab activity."
            );
          }

        } catch (error) {
          /*
           * Activity tracking should never
           * interfere with the coding
           * experience if the request fails.
           */

          console.warn(
            "Lab activity request failed:",
            error
          );
        }
      },
      []
    );


  const handleEditorActivity =
    useCallback(() => {
      const id = labId;

      if (!id) {
        return;
      }


      const now =
        Date.now();


      const elapsed =
        now -
        lastActivitySentAtRef.current;


      /*
       * Send immediately if:
       *
       * - this is the first activity
       * - at least 10 seconds have passed
       */

      if (
        lastActivitySentAtRef.current ===
          0 ||
        elapsed >= 10_000
      ) {
        lastActivitySentAtRef.current =
          now;

        if (
          activityTimerRef.current !==
          null
        ) {
          clearTimeout(
            activityTimerRef.current
          );

          activityTimerRef.current =
            null;
        }

        void reportLabActivity(
          id
        );

        return;
      }


      /*
       * Activity happened inside the
       * 10-second cooldown.
       *
       * Schedule one update for when
       * the cooldown expires.
       */

      if (
        activityTimerRef.current ===
        null
      ) {
        const remaining =
          10_000 - elapsed;


        activityTimerRef.current =
          setTimeout(() => {
            activityTimerRef.current =
              null;

            /*
             * Re-check that this lab is
             * still the active lab.
             */

            if (labId) {
              lastActivitySentAtRef.current =
                Date.now();

              void reportLabActivity(
                labId
              );
            }
          }, remaining);
      }
    }, [
      labId,
      reportLabActivity,
    ]);


  /*
   * Reset activity tracking whenever
   * the active lab changes.
   */

  useEffect(() => {
    lastActivitySentAtRef.current =
      0;


    if (
      activityTimerRef.current !==
      null
    ) {
      clearTimeout(
        activityTimerRef.current
      );

      activityTimerRef.current =
        null;
    }


    return () => {
      if (
        activityTimerRef.current !==
        null
      ) {
        clearTimeout(
          activityTimerRef.current
        );

        activityTimerRef.current =
          null;
      }
    };
  }, [labId]);


  // User interaction counts as activity; an open idle tab does not.
  useEffect(() => {
    if (!labId) return;

    const events = ["keydown", "pointerdown", "pointermove", "wheel"];
    const record = (event: Event) => {
      if (event.isTrusted) handleEditorActivity();
    };

    for (const event of events) {
      document.addEventListener(event, record, {
        capture: true,
        passive: true,
      });
    }

    return () => {
      for (const event of events) {
        document.removeEventListener(event, record, true);
      }
    };
  }, [labId, handleEditorActivity]);

  /*
   * Backend health check
   */

  /*
   * Open Settings after returning from GitHub OAuth.
   *
   * The backend redirects back to:
   *   /?github=connected
   *
   * The settings panel then reloads the current connection
   * state from /student/settings.
   */


  useEffect(() => {
    apiFetch(`${API_URL}/health`)
      .then((response) => {
        if (!response.ok) {
          throw new Error(
            "Backend returned an error"
          );
        }

        return response.json();
      })
      .then((data) => {
        setBackendStatus(
          data.status
        );
      })
      .catch(() => {
        setBackendStatus(
          "Backend unavailable"
        );
      });
  }, []);

/*
 * -------------------------------------------------------
 * GitHub status and repository loading
 * -------------------------------------------------------
 */

const loadGitHubRepositories = useCallback(
  async () => {
    setGithubLoading(true);
    setGithubError(null);

    try {
      const statusResponse =
        await apiFetch(
          `${API_URL}/github/status`
        );

      if (!statusResponse.ok) {
        throw new Error(
          "Failed to load GitHub connection status."
        );
      }

      const status =
        await statusResponse.json();

      setGithubConnected(
        Boolean(status.connected)
      );

      setGithubUsername(
        status.github_username ?? null
      );

      if (!status.connected) {
        setGithubRepositories([]);
        return;
      }

      const repositoriesResponse =
        await apiFetch(
          `${API_URL}/github/repositories`
        );

      if (!repositoriesResponse.ok) {
        const error =
          await repositoriesResponse
            .json()
            .catch(() => null);

        throw new Error(
          error?.detail ??
            "Failed to load GitHub repositories."
        );
      }

      const data =
        await repositoriesResponse.json();

      setGithubRepositories(
        data.repositories ?? []
      );
    } catch (error) {
      console.error(
        "Failed to load GitHub data:",
        error
      );

      setGithubError(
        error instanceof Error
          ? error.message
          : "Failed to load GitHub data."
      );
    } finally {
      setGithubLoading(false);
    }
  },
  []
);

useEffect(() => {
  void loadGitHubRepositories();
}, [
  loadGitHubRepositories,
]);
  useEffect(() => {
    const params = new URLSearchParams(
      window.location.search
    );

    const githubResult =
      params.get("github");

    if (
  githubResult === "connected"
) {
  setSettingsOpen(true);

  void loadGitHubRepositories();

  window.history.replaceState(
    {},
    document.title,
    window.location.pathname
  );
}
}, [
  loadGitHubRepositories,
]);

  /*
   * Create lab
   */

  async function createLab(replaceLabIds?: string[]) {
    if (labCreationBusyRef.current || labId) return;
    labCreationBusyRef.current = true;
    setLabNotice(null);
    setLabConflictIds(null);
    setCreatingLab(true);
    try {
      const response = await apiFetch(`${API_URL}/labs`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(
          replaceLabIds ? { replace_lab_ids: replaceLabIds } : {}
        ),
      });
      const data = await response.json().catch(() => null);
      if (!response.ok) {
        const detail = data?.detail;
        if (
          response.status === 409 &&
          detail?.code === "LAB_ALREADY_OPEN" &&
          Array.isArray(detail.lab_ids) &&
          detail.lab_ids.length > 0 &&
          detail.lab_ids.every((id: unknown) => typeof id === "string")
        ) {
          setLabConflictIds(detail.lab_ids);
          return;
        }
        throw new Error(
          typeof detail === "string"
            ? detail
            : detail?.message ?? "Failed to create lab."
        );
      }
      if (!data?.lab_id) throw new Error("Invalid response when opening the lab.");
      closingLabRef.current = false;
      setLabId(data.lab_id);
      setExpandedWorkspaceDirectories({}); setWorkspaceDirectories({}); setGitStatus(null); setGitDiff(null);
      setFiles([]); setSelectedFile(null); setFileContent(""); setRunning(false);
      if (!data.github_connected) {
        setActiveGitHubRepositoryId(null);
        alert("Connect GitHub in Settings to use your permanent wibyte-workspace repository.");
        return;
      }
      let repository = data.repository;
      if (data.repository_missing) {
        alert("Create repository 'wibyte-workspace' GitHub repository");
        const provisionResponse = await apiFetch(`${API_URL}/github/labs/${data.lab_id}/workspace-repository`, { method: "POST" });
        if (!provisionResponse.ok) { const error = await provisionResponse.json().catch(() => null); throw new Error(error?.detail ?? "Failed to create the workspace repository"); }
        repository = (await provisionResponse.json()).repository;
      }
      setActiveGitHubRepositoryId(repository?.id ?? null);
      await loadFiles(data.lab_id);
      if (repository?.id) {
        const statusResponse = await apiFetch(`${API_URL}/github/labs/${data.lab_id}/git/status`);
        if (statusResponse.ok) setGitStatus(await statusResponse.json());
      }
      void loadGitHubRepositories();
    } catch (error) {
      console.error(error); alert(error instanceof Error ? error.message : "Failed to create lab");
    } finally { labCreationBusyRef.current = false; setCreatingLab(false); }
  }


  /*
   * Close lab
   */

  async function deleteLab() {
    if (!labId) {
      return;
    }


    if (gitStatus && (!gitStatus.clean || gitStatus.ahead > 0)) {
      const discard = window.confirm(
        "Changes made to the repository are yet to be committed and pushed, please commit and push to save changes before closing the lab.\n\nOK: close lab without saving changes\nCancel: take me back"
      );
      if (!discard) return;
    }


    closingLabRef.current = true;

    try {
      /*
       * If a process is running,
       * request that it stops first.
       */

      if (running) {
        terminalRef.current?.stopProcess();
      }


      const response =
        await apiFetch(
          `${API_URL}/labs/${labId}`,
          {
            method: "DELETE",
          }
        );


      if (!response.ok) {
        throw new Error(
          "Failed to delete lab"
        );
      }


      setLabId(null);
      setActiveGitHubRepositoryId(null);
      setExpandedWorkspaceDirectories({});
      setWorkspaceDirectories({});
      setGitStatus(null);
      setGitDiff(null);

      setFiles([]);

      setSelectedFile(
        null
      );

      setFileContent("");

      setRunning(false);

    } catch (error) {
      closingLabRef.current = false;
      console.error(error);

      alert(
        "Failed to delete lab"
      );
    }
  }


  /*
   * Load files
   */

  async function loadFiles(
    id: string
  ) {
    try {
      const response =
        await apiFetch(
          `${API_URL}/labs/${id}/files`
        );


      if (!response.ok) {
        throw new Error(
          "Failed to load files"
        );
      }


      const data =
        await response.json();


      setFiles(
        data.files
      );

    } catch (error) {
      console.error(error);

      alert(
        "Failed to load files"
      );
    }
  }


  /* Browsers only permit a native leave prompt for tab close/reload. */
  useEffect(() => {
    if (!labId || !gitStatus || (gitStatus.clean && gitStatus.ahead === 0)) return;
    const handleBeforeUnload = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ""; };
    window.addEventListener("beforeunload", handleBeforeUnload);
    return () => window.removeEventListener("beforeunload", handleBeforeUnload);
  }, [labId, gitStatus]);

  /*
   * Load files when lab changes
   */
  useEffect(() => {
    if (!labId) {
      return;
    }

    void loadFiles(labId);
  }, [labId]);

  useEffect(() => {
    if (!labId || !activeGitHubRepositoryId) {
      return;
    }

    void loadGitStatus();
  }, [labId, activeGitHubRepositoryId]);

  useEffect(() => {
    if (!labId || !activeGitHubRepositoryId) return;
    const timer = window.setInterval(() => void loadGitStatus(), 2000);
    return () => window.clearInterval(timer);
  }, [labId, activeGitHubRepositoryId]);

  async function loadWorkspaceDirectory(
    id: string,
    path: string
  ) {
    const key = path || ".";

    setWorkspaceDirectories((current) => ({
      ...current,
      [key]: {
        loading: true,
        items: current[key]?.items ?? [],
        error: null,
      },
    }));

    try {
      const suffix = path
        ? `?path=${encodeURIComponent(path)}`
        : "";

      const response = await apiFetch(
        `${API_URL}/labs/${id}/files${suffix}`
      );

      if (!response.ok) {
        const error = await response.json().catch(() => null);
        throw new Error(
          error?.detail ?? "Failed to load directory"
        );
      }

      const data = await response.json();

      setWorkspaceDirectories((current) => ({
        ...current,
        [key]: {
          loading: false,
          items: data.files ?? [],
          error: null,
        },
      }));
    } catch (error) {
      setWorkspaceDirectories((current) => ({
        ...current,
        [key]: {
          loading: false,
          items: [],
          error: error instanceof Error
            ? error.message
            : "Failed to load directory.",
        },
      }));
    }
  }

  async function refreshWorkspaceTree() {
    if (!labId) {
      return;
    }

    await loadFiles(labId);

    const expandedPaths = Object.entries(
      expandedWorkspaceDirectories
    )
      .filter(([, expanded]) => expanded)
      .map(([path]) => path);

    await Promise.all(
      expandedPaths.map((path) =>
        loadWorkspaceDirectory(labId, path)
      )
    );
  }

  async function toggleWorkspaceDirectory(
    path: string
  ) {
    if (!labId) {
      return;
    }

    const isExpanded =
      expandedWorkspaceDirectories[path] ?? false;

    setExpandedWorkspaceDirectories((current) => ({
      ...current,
      [path]: !isExpanded,
    }));

    if (!isExpanded) {
      await loadWorkspaceDirectory(labId, path);
    }
  }

  async function movePath(oldPath: string) {
    if (!labId) {
      return;
    }

    const newPath = window.prompt(
      "Enter the new path:",
      oldPath
    )?.trim();

    if (!newPath || newPath === oldPath) {
      return;
    }

    try {
      const response = await apiFetch(
        `${API_URL}/labs/${labId}/files/rename`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            old_path: oldPath,
            new_path: newPath,
          }),
        }
      );

      if (!response.ok) {
        const error = await response.json().catch(() => null);
        throw new Error(
          error?.detail ?? "Failed to move path"
        );
      }

      if (selectedFile === oldPath) {
        setSelectedFile(newPath);
      }

      await refreshWorkspaceTree();
    } catch (error) {
      alert(
        error instanceof Error
          ? error.message
          : "Failed to move path"
      );
    }
  }


  async function loadGitStatus() {
    if (
      !labId || !activeGitHubRepositoryId || closingLabRef.current ||
      gitActionBusyRef.current || gitStatusPollingRef.current
    ) return;

    gitStatusPollingRef.current = true;
    const version = gitActionVersionRef.current;

    try {
      const response = await apiFetch(
        `${API_URL}/github/labs/${labId}/git/status`
      );

      if (!response.ok) {
        const error = await response.json().catch(() => null);
        throw new Error(error?.detail ?? "Failed to load Git status");
      }

      const status = await response.json();
      if (
        !closingLabRef.current &&
        !gitActionBusyRef.current &&
        version === gitActionVersionRef.current
      ) {
        setGitStatus(status);
      }
    } catch (error) {
      console.error("Background Git status check failed:", error);
    } finally {
      gitStatusPollingRef.current = false;
    }
  }

  async function loadGitDiff() {
    if (!labId || !activeGitHubRepositoryId) {
      return;
    }

    setGitLoading(true);

    try {
      const response = await apiFetch(
        `${API_URL}/github/labs/${labId}/git/diff`
      );

      if (!response.ok) {
        const error = await response.json().catch(() => null);
        throw new Error(error?.detail ?? "Failed to load Git diff");
      }

      const data = await response.json();
      setGitDiff(
        [
          data.unstaged ? "UNSTAGED\n" + data.unstaged : "",
          data.staged ? "STAGED\n" + data.staged : "",
        ].filter(Boolean).join("\n\n") || "No differences."
      );
    } catch (error) {
      alert(
        error instanceof Error
          ? error.message
          : "Failed to load Git diff"
      );
    } finally {
      setGitLoading(false);
    }
  }

  async function commitGitChanges() {
    if (!labId || !activeGitHubRepositoryId || gitActionBusyRef.current) {
      return;
    }

    const message = window.prompt("Commit message:")?.trim();
    if (!message) {
      return;
    }

    gitActionBusyRef.current = true;
    gitActionVersionRef.current += 1;
    setGitLoading(true);

    try {
      const response = await apiFetch(
        `${API_URL}/github/labs/${labId}/git/commit`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({ message }),
        }
      );

      if (!response.ok) {
        const error = await response.json().catch(() => null);
        throw new Error(error?.detail ?? "Failed to commit changes");
      }

      const data = await response.json();
      setGitStatus(data.status ?? null);
      setGitDiff(null);
      await refreshWorkspaceTree();
    } catch (error) {
      alert(
        error instanceof Error
          ? error.message
          : "Failed to commit changes"
      );
    } finally {
      gitActionBusyRef.current = false;
      setGitLoading(false);
    }
  }

  async function pushGitChanges() {
    if (!labId || !activeGitHubRepositoryId || gitActionBusyRef.current) {
      return;
    }

    gitActionBusyRef.current = true;
    gitActionVersionRef.current += 1;
    setGitLoading(true);

    try {
      const response = await apiFetch(
        `${API_URL}/github/labs/${labId}/git/push`,
        { method: "POST" }
      );

      if (!response.ok) {
        const error = await response.json().catch(() => null);
        throw new Error(error?.detail ?? "Failed to push changes");
      }

      const data = await response.json();
      setGitStatus(data.status ?? null);
      const repositoryName = githubRepositories.find(
        (repository) => repository.id === activeGitHubRepositoryId
      )?.name ?? "repository";
      const branch = data.status?.branch ?? gitStatus?.branch;
      alert(`Pushed to GitHub → ${repositoryName}${branch ? ` (${branch})` : ""}`);
    } catch (error) {
      alert(
        error instanceof Error
          ? error.message
          : "Failed to push changes"
      );
    } finally {
      gitActionBusyRef.current = false;
      setGitLoading(false);
    }
  }

  async function pullGitChanges() {
    if (!labId || !activeGitHubRepositoryId) {
      return;
    }

    if (gitStatus && !gitStatus.clean) {
      const proceed = window.confirm(
        "The workspace has uncommitted changes. Pull may fail. Continue?"
      );
      if (!proceed) {
        return;
      }
    }

    setGitLoading(true);

    try {
      const response = await apiFetch(
        `${API_URL}/github/labs/${labId}/git/pull`,
        { method: "POST" }
      );

      if (!response.ok) {
        const error = await response.json().catch(() => null);
        throw new Error(error?.detail ?? "Failed to pull changes");
      }

      const data = await response.json();
      setGitStatus(data.status ?? null);
      setGitDiff(null);
      await refreshWorkspaceTree();

      if (selectedFile) {
        await openFile(selectedFile);
      }

      alert(data.output || "Pull completed.");
    } catch (error) {
      alert(
        error instanceof Error
          ? error.message
          : "Failed to pull changes"
      );
    } finally {
      setGitLoading(false);
    }
  }

  // Retained for the existing repository controls; these operations remain available internally.
  void loadGitDiff;
  void pullGitChanges;

  /*
   * Create new file
   */

  async function createFile() {
    if (!labId) {
      return;
    }


    const fileName =
      window.prompt(
        "Enter file name:"
      );


    if (!fileName) {
      return;
    }


    const path =
      defaultPythonFilename(fileName.trim());


    if (!path) {
      return;
    }


    try {
      const response =
        await apiFetch(
          `${API_URL}/labs/${labId}/files`,
          {
            method: "POST",

            headers: {
              "Content-Type":
                "application/json",
            },

            body: JSON.stringify({
              path,
              type: "file",
            }),
          }
        );


      if (!response.ok) {
        const error =
          await response
            .json()
            .catch(
              () => null
            );


        throw new Error(
          error?.detail ??
            "Failed to create file"
        );
      }


      await loadFiles(
        labId
      );


      await openFile(path);
      if (activeGitHubRepositoryId) void loadGitStatus();

    } catch (error) {
      console.error(error);

      alert(
        error instanceof Error
          ? error.message
          : "Failed to create file"
      );
    }
  }


  /*
   * Open file
   */

  async function openFile(
    path: string
  ) {
    if (!labId) {
      return;
    }


    setLoadingFile(
      true
    );


    try {
      const response =
        await apiFetch(
          `${API_URL}/labs/${labId}/files/${encodeURIComponent(
            path
          )}`
        );


      if (!response.ok) {
        throw new Error(
          "Failed to load file"
        );
      }


      const data =
        await response.json();


      setSelectedFile(
        path
      );

      setFileContent(
        data.content
      );

    } catch (error) {
      console.error(error);

      alert(
        "Failed to load file"
      );

    } finally {
      setLoadingFile(
        false
      );
    }
  }


  /*
   * Save current file
   *
   * Returns true only if the
   * save succeeds.
   */

  /*
   * Open a GitHub file inside the already-active Lab.
   *
   * The repository must already have been opened as
   * the active Lab. The repository is then available
   * inside that Lab's workspace, so clicking a file
   * uses the normal workspace file loader instead of
   * attempting to create another Lab.
   */
  async function saveFile(): Promise<boolean> {
    if (
      !labId ||
      !selectedFile
    ) {
      return false;
    }


    setSavingFile(
      true
    );


    try {
      const response =
        await apiFetch(
          `${API_URL}/labs/${labId}/files/${encodeURIComponent(
            selectedFile
          )}`,
          {
            method: "PUT",

            headers: {
              "Content-Type":
                "application/json",
            },

            body: JSON.stringify({
              content:
                fileContent,
            }),
          }
        );


      if (!response.ok) {
        throw new Error(
          "Failed to save file"
        );
      }


      /*
       * Saving is also meaningful
       * lab activity.
       */

      void reportLabActivity(labId);
      if (activeGitHubRepositoryId) void loadGitStatus();
      return true;

    } catch (error) {
      console.error(error);

      alert(
        "Failed to save file"
      );


      return false;

    } finally {
      setSavingFile(
        false
      );
    }
  }


  /*
   * Rename file
   */

  async function renameFile(
    oldPath: string,
    isFile = false
  ) {
    if (!labId) {
      return;
    }


    const currentName =
      oldPath.split("/").pop() ??
      oldPath;


    const newName =
      window.prompt(
        "Enter new file name:",
        currentName
      );


    if (newName === null) {
      return;
    }


    const trimmedName =
      isFile ? defaultPythonFilename(newName.trim()) : newName.trim();


    if (!trimmedName) {
      alert(
        "File name cannot be empty."
      );

      return;
    }


    if (
      trimmedName ===
      currentName
    ) {
      return;
    }


    /*
     * Preserve the directory if
     * the file is inside one.
     */

    const lastSlash =
      oldPath.lastIndexOf("/");


    const newPath =
      lastSlash === -1
        ? trimmedName
        : `${oldPath.slice(
            0,
            lastSlash + 1
          )}${trimmedName}`;


    try {
      const response =
        await apiFetch(
          `${API_URL}/labs/${labId}/files/rename`,
          {
            method: "POST",

            headers: {
              "Content-Type":
                "application/json",
            },

            body: JSON.stringify({
              old_path:
                oldPath,

              new_path:
                newPath,
            }),
          }
        );


      if (!response.ok) {
        const error =
          await response
            .json()
            .catch(
              () => null
            );


        throw new Error(
          error?.detail ??
            "Failed to rename file"
        );
      }


      await refreshWorkspaceTree();


      /*
       * If the renamed file is open,
       * update its selected path.
       */

      if (
        selectedFile ===
        oldPath
      ) {
        setSelectedFile(
          newPath
        );
      }

    } catch (error) {
      console.error(error);

      alert(
        error instanceof Error
          ? error.message
          : "Failed to rename file"
      );
    }
  }


  /*
   * Delete file
   */

  async function deleteFile(
    path: string
  ) {
    if (!labId) {
      return;
    }


    const confirmed =
      window.confirm(
        `Delete "${path}"?\n\nThis cannot be undone.`
      );


    if (!confirmed) {
      return;
    }


    try {
      const response =
        await apiFetch(
          `${API_URL}/labs/${labId}/files/${encodeURIComponent(
            path
          )}`,
          {
            method: "DELETE",
          }
        );


      if (!response.ok) {
        const error =
          await response
            .json()
            .catch(
              () => null
            );


        throw new Error(
          error?.detail ??
            "Failed to delete file"
        );
      }


      /*
       * If the deleted file is open,
       * clear the editor.
       */

      if (
        selectedFile ===
        path
      ) {
        setSelectedFile(
          null
        );

        setFileContent(
          ""
        );
      }


      await loadFiles(
        labId
      );

    } catch (error) {
      console.error(error);

      alert(
        error instanceof Error
          ? error.message
          : "Failed to delete file"
      );
    }
  }


  /*
   * Open GUI desktop
   */

  async function openGui() {
    if (!labId) {
      alert(
        "Create or open a Lab before opening the GUI."
      );
      return;
    }

    if (openingGui) {
      return;
    }

    setOpeningGui(true);

    const guiWindow = window.open(
      "about:blank",
      "_blank"
    );

    try {
      const startResponse = await apiFetch(
        `${API_URL}/labs/${labId}/gui/start`,
        { method: "POST" }
      );

      if (!startResponse.ok) {
        const detail = await startResponse.text();
        throw new Error(
          detail || "Failed to start GUI environment."
        );
      }

      const connectionResponse = await apiFetch(
        `${API_URL}/labs/${labId}/gui/connection`
      );

      if (!connectionResponse.ok) {
        const detail = await connectionResponse.text();
        throw new Error(
          detail || "Failed to get GUI connection."
        );
      }

      const connection = await connectionResponse.json();
      const url = connection?.url;

      if (typeof url !== "string" || !url) {
        throw new Error(
          "GUI connection URL was not returned by the backend."
        );
      }

      if (guiWindow) {
        guiWindow.location.href = url;
      } else {
        window.open(
          url,
          "_blank",
          "noopener,noreferrer"
        );
      }
    } catch (error) {
      if (guiWindow) {
        guiWindow.close();
      }

      console.error(error);

      alert(
        error instanceof Error
          ? error.message
          : "Failed to open GUI environment."
      );
    } finally {
      setOpeningGui(false);
    }
  }


  /*
   * Run selected file
   */

  async function runFile() {
    if (
      !selectedFile ||
      !terminalRef.current
    ) {
      return;
    }


    /*
     * Always save the latest editor
     * contents before running.
     */

    const saved =
      await saveFile();


    if (!saved) {
      return;
    }


    const started =
      terminalRef.current.runFile(
        selectedFile
      );


    if (!started) {
      alert(
        "Terminal is not connected. Please wait a moment and try again."
      );

      return;
    }


    /*
     * The backend will send
     * process_exit when the process
     * actually finishes.
     */

    setRunning(
      true
    );
  }


  /*
   * Stop selected process
   */

  function stopFile() {
    if (!terminalRef.current) {
      return;
    }


    const stopped =
      terminalRef.current.stopProcess();


    if (!stopped) {
      alert(
        "Terminal is not connected."
      );

      return;
    }


    /*
     * The stop command was successfully
     * sent to the terminal.
     *
     * Return the UI to the Run state.
     */

    setRunning(
      false
    );
  }


  /*
   * Process-exit callback
   *
   * useCallback keeps the function
   * reference stable between renders.
   *
   * This is important because Terminal
   * uses the callback without recreating
   * its WebSocket/xterm instance.
   */

  const handleProcessExit =
    useCallback(
      (_exitCode: number) => {
        setRunning(
          false
        );
      },
      []
    );


  return (
    <main className="app">
      <dialog
        ref={labConflictDialogRef}
        className="welcome-dialog"
        aria-labelledby="lab-conflict-title"
        onCancel={() => setLabConflictIds(null)}
      >
        <div className="welcome-guide">
          <h2 id="lab-conflict-title">Another lab is already open</h2>
          <p>Your account has an existing lab, possibly in another tab or device.</p>
          <p className="welcome-notice">
            Terminating it will stop its programs and delete any work that
            has not been pushed to GitHub or downloaded.
          </p>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 10 }}>
            <button
              type="button"
              style={{ padding: "10px 14px" }}
              disabled={creatingLab || !labConflictIds}
              onClick={() => {
                if (labConflictIds) void createLab(labConflictIds);
              }}
            >
              Terminate old lab and open here
            </button>
            <button
              type="button"
              style={{ padding: "10px 14px" }}
              onClick={() => {
                setLabConflictIds(null);
                setLabNotice(
                  "Your existing lab is still running. Close this tab and continue in the other tab or device."
                );
                window.close();
              }}
            >
              Keep existing lab and close this tab
            </button>
          </div>
        </div>
      </dialog>

      <dialog
        ref={welcomeDialogRef}
        className="welcome-dialog"
        aria-label="WiByte Python Lab help"
      >
        <div className="welcome-dialog-actions">
          <button type="button" onClick={() => welcomeDialogRef.current?.close()}>
            Close help
          </button>
        </div>
        <WelcomeGuide />
      </dialog>

      <header className="header">

        <div>

          <h1>
            WiByte Python Lab
          </h1>

          <p>
            Backend status:{" "}
            {backendStatus}
          </p>

        </div>


        {!labId && (
          <button
            onClick={() => void createLab()}
            disabled={
              creatingLab ||
              backendStatus !==
                "ok"
            }
          >
            {creatingLab
              ? "Creating..."
              : "Create Lab"}
          </button>
        )}


        {labId && (
          <button
            onClick={
              deleteLab
            }
          >
            Close Lab
          </button>
        )}

        <button
          onClick={() => setSettingsOpen(true)}
          type="button"
        >
          Settings
        </button>

      </header>


      {labId ? (
  <section
    className="workspace"
    style={{
      gridTemplateColumns: `min(${sidebarWidth}px, 40%) 8px minmax(0, 1fr)`,
    }}
  >
    <aside className="file-explorer">
<section className="explorer-section workspace-section">
        <div className="file-panel-header">
          <span>WORKSPACE</span>

          <div className="explorer-header-actions">
            <input
              ref={uploadInputRef}
              type="file"
              hidden
              onChange={(event) => {
                const file = event.currentTarget.files?.[0];
                event.currentTarget.value = "";
                if (file) void uploadWorkspaceFile(file);
              }}
            />
            <button
              className="workspace-upload-button"
              type="button"
              disabled={uploadingFile || !labId}
              title="Upload a file to Workspace (maximum 10 MB)"
              onClick={() => uploadInputRef.current?.click()}
            >
              {uploadingFile ? "Uploading..." : "Upload"}
            </button>

            <button
              className="small-action-button"
              onClick={() => void refreshWorkspaceTree()}
              title="Refresh workspace"
              type="button"
            >
              ↻
            </button>

            <button
              className="create-file-button"
              onClick={createFile}
              title="Create a new file"
              type="button"
            >
              Create File
            </button>
          </div>
        </div>

        {files.length === 0 ? (
          <p className="empty-files">No files</p>
        ) : (
          <div className="file-list">
            {files.map((file) => {
              const path = file.name;

              if (file.type === "directory") {
                return (
                  <WorkspaceDirectoryTree
                    key={path}
                    item={file}
                    path={path}
                    directories={workspaceDirectories}
                    expandedDirectories={expandedWorkspaceDirectories}
                    selectedFile={selectedFile}
                    onToggleDirectory={toggleWorkspaceDirectory}
                    onOpenFile={openFile}
                    onRename={renameFile}
                    onMove={movePath}
                    onDelete={deleteFile} onDownload={downloadWorkspaceFile}
                  />
                );
              }

              return (
                <WorkspaceFileRow
                  key={path}
                  path={path}
                  name={file.name}
                  selected={selectedFile === path}
                  onOpen={openFile}
                  onRename={renameFile}
                  onMove={movePath}
                  onDelete={deleteFile} onDownload={downloadWorkspaceFile}
                />
              );
            })}
          </div>
        )}
      </section>

      <section className="explorer-section connected-repository-section">
        <div className="file-panel-header">
          <span>GITHUB</span>
          <button
            className="small-action-button"
            type="button"
            title="Refresh GitHub and Git status"
            aria-label="Refresh GitHub and Git status"
            disabled={githubLoading || gitLoading}
            onClick={() => {
              void loadGitHubRepositories();
              if (activeGitHubRepositoryId) void loadGitStatus();
            }}
          >
            ↻
          </button>
        </div>

        <div className="connected-repository-content">
          {githubError && (
            <p className="explorer-error">{githubError}</p>
          )}

          {githubConnected ? (
            <div className="connected-repository-identity">
              <span className="connected-repository-user">
                {githubUsername ? `@${githubUsername}` : "GitHub connected"}
              </span>
              <strong className="connected-repository-name">
                {activeGitHubRepositoryId
                  ? githubRepositories.find(
                      (repository) => repository.id === activeGitHubRepositoryId
                    )?.name ?? (githubLoading ? "Loading repository..." : "Repository details unavailable")
                  : "No active repository"}
              </strong>
            </div>
          ) : githubLoading ? (
            <p className="explorer-message">Loading GitHub...</p>
          ) : (
            <div className="github-connect-banner">
              <strong>GitHub isn't connected</strong>
              <span>Connect GitHub to commit and push your work.</span>
              <button type="button" onClick={() => setSettingsOpen(true)}>
                Connect GitHub
              </button>
            </div>
          )}

          {activeGitHubRepositoryId && (
            <>
{gitStatus ? (
            <div className="git-status-summary">
              <div>Branch: {gitStatus.branch ?? "unknown"}</div>
              <div>
                {gitStatus.clean
                  ? "Working tree clean"
                  : `${gitStatus.changes.length} change(s)`}
              </div>
              {(gitStatus.ahead > 0 || gitStatus.behind > 0) && (
                <div>
                  {gitStatus.ahead > 0 ? `↑${gitStatus.ahead} ` : ""}
                  {gitStatus.behind > 0 ? `↓${gitStatus.behind}` : ""}
                </div>
              )}
            </div>
          ) : (
            <p className="explorer-message">Loading Git status...</p>
          )}

          {gitStatus && !gitStatus.clean && (
            <div className="git-change-list">
              {gitStatus.changes.map((change) => (
                <div key={`${change.index}${change.worktree}:${change.path}`}>
                  <code>{change.index}{change.worktree}</code> {change.path}
                </div>
              ))}
            </div>
          )}

          <div className="git-actions">
            {gitStatus?.ahead && gitStatus.ahead > 0 ? (
              <button onClick={() => void pushGitChanges()} disabled={gitLoading} type="button">{gitLoading ? "Working..." : "Push"}</button>
            ) : (
              <button onClick={() => void commitGitChanges()} disabled={gitLoading || !gitStatus || gitStatus.clean} type="button">{gitLoading ? "Working..." : "Commit"}</button>
            )}
          </div>

          {gitDiff !== null && (
            <pre className="git-diff-output">{gitDiff}</pre>
          )}

            </>
          )}
        </div>
      </section>

    </aside>

    <div
      className="sidebar-divider"
      role="separator"
      aria-label="Resize workspace sidebar"
      aria-orientation="vertical"
      aria-valuemin={220}
      aria-valuemax={520}
      aria-valuenow={Math.round(sidebarWidth)}
      tabIndex={0}
      title="Drag to resize; double-click to reset"
      onPointerDown={(event) => {
        if (event.button !== 0 || !event.isPrimary) return;
        event.preventDefault();
        event.currentTarget.focus();
        event.currentTarget.setPointerCapture(event.pointerId);
      }}
      onPointerMove={(event) => {
        if (!event.currentTarget.hasPointerCapture(event.pointerId)) return;
        const bounds = event.currentTarget.parentElement?.getBoundingClientRect();
        if (!bounds) return;
        const maximum = Math.min(520, bounds.width * 0.4);
        setSidebarWidth(Math.max(220, Math.min(maximum, event.clientX - bounds.left - 4)));
      }}
      onPointerUp={(event) => {
        if (event.currentTarget.hasPointerCapture(event.pointerId)) {
          event.currentTarget.releasePointerCapture(event.pointerId);
        }
      }}
      onPointerCancel={(event) => {
        if (event.currentTarget.hasPointerCapture(event.pointerId)) {
          event.currentTarget.releasePointerCapture(event.pointerId);
        }
      }}
      onDoubleClick={() => setSidebarWidth(310)}
      onKeyDown={(event) => {
        if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
        event.preventDefault();
        const bounds = event.currentTarget.parentElement?.getBoundingClientRect();
        if (!bounds) return;
        const maximum = Math.min(520, bounds.width * 0.4);
        const key = event.key;
        setSidebarWidth((width) =>
          key === "Home" ? 220 :
          key === "End" ? maximum :
          Math.max(220, Math.min(maximum, width + (key === "ArrowRight" ? 10 : -10)))
        );
      }}
    />


    <section
      className="editor-terminal"
      style={{
        gridTemplateColumns: `minmax(0, ${editorWidth}fr) 8px minmax(0, ${100 - editorWidth}fr)`,
      }}
    >
      <div className="editor-section">
        <div className="editor-header">
          <span>
            {selectedFile ??
              "Welcome"}
          </span>

          <button
            type="button"
            className="welcome-help-button"
            onClick={() => welcomeDialogRef.current?.showModal()}
          >
            Help
          </button>

          {selectedFile && (
            <div className="editor-actions">
              <button
                onClick={
                  saveFile
                }
                disabled={
                  savingFile ||
                  running
                }
              >
                {savingFile
                  ? "Saving..."
                  : "Save"}
              </button>

              <button
                onClick={
                  () => void openGui()
                }
                disabled={
                  openingGui ||
                  !labId
                }
              >
                {openingGui
                  ? "Opening GUI..."
                  : "GUI"}
              </button>

              {!running ? (
                <button
                  onClick={
                    runFile
                  }
                  disabled={
                    savingFile
                  }
                >
                  ▶ Run
                </button>
              ) : (
                <button
                  onClick={
                    stopFile
                  }
                  className="stop-button"
                >
                  ■ Stop
                </button>
              )}
            </div>
          )}
        </div>

        <div className="editor">
          {loadingFile ? (
            <div className="editor-message">
              Loading file...
            </div>
          ) : selectedFile ? (
            <CodeEditor
              value={
                fileContent
              }
              onChange={
                setFileContent
              }
              onActivity={
                handleEditorActivity
              }
            />
          ) : (
            <WelcomeGuide />
          )}
        </div>
      </div>

      <div
        className="panel-divider"
        role="separator"
        aria-label="Resize code and terminal panels"
        aria-orientation="vertical"
        aria-valuemin={30}
        aria-valuemax={70}
        aria-valuenow={Math.round(editorWidth)}
        tabIndex={0}
        title="Drag to resize; double-click to reset"
        onPointerDown={(event) => {
          if (event.button !== 0 || !event.isPrimary) return;
          event.preventDefault();
          event.currentTarget.focus();
          event.currentTarget.setPointerCapture(event.pointerId);
        }}
        onPointerMove={(event) => {
          if (!event.currentTarget.hasPointerCapture(event.pointerId)) return;
          const bounds = event.currentTarget.parentElement?.getBoundingClientRect();
          if (!bounds || bounds.width <= 8) return;
          const width = ((event.clientX - bounds.left - 4) / (bounds.width - 8)) * 100;
          setEditorWidth(Math.max(30, Math.min(70, width)));
        }}
        onPointerUp={(event) => {
          if (event.currentTarget.hasPointerCapture(event.pointerId)) {
            event.currentTarget.releasePointerCapture(event.pointerId);
          }
        }}
        onPointerCancel={(event) => {
          if (event.currentTarget.hasPointerCapture(event.pointerId)) {
            event.currentTarget.releasePointerCapture(event.pointerId);
          }
        }}
        onDoubleClick={() => setEditorWidth(60)}
        onKeyDown={(event) => {
          if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
          event.preventDefault();
          setEditorWidth((width) =>
            event.key === "Home" ? 30 :
            event.key === "End" ? 70 :
            Math.max(30, Math.min(70, width + (event.key === "ArrowRight" ? 2 : -2)))
          );
        }}
      />

      <div className="terminal-section">
        <div className="panel-title">
          TERMINAL
        </div>

        <Terminal
          ref={
            terminalRef
          }
          labId={
            labId
          }
          accessToken={accessToken}
          onProcessExit={
            handleProcessExit
          }
        />
      </div>
    </section>
  </section>
) : (
  <section className="empty-state">
    <h2>
      No active lab
    </h2>

    <p>
      {labNotice ?? "Create a lab to start coding."}
    </p>
  </section>
)}

{settingsOpen && (
  <SettingsPanel
    apiUrl={API_URL}
    userEmail={currentUser?.email ?? null}
    onSignOut={() =>
      void handleSignOut()
    }
    onClose={() =>
      setSettingsOpen(false)
    }
  />
)}

</main>
);
}

function WorkspaceFileRow({
  path,
  name,
  selected,
  onOpen,
  onRename,
  onMove,
  onDelete,
  onDownload,
}: {
  path: string;
  name: string;
  selected: boolean;
  onOpen: (path: string) => void;
  onRename: (path: string, isFile?: boolean) => void;
  onMove: (path: string) => void;
  onDelete: (path: string) => void;
  onDownload: (path: string) => void;
}) {
  return (
    <div className={`workspace-file-row${selected ? " selected" : ""}`}>
      <button
        className="workspace-file-item"
        type="button"
        title={path}
        onClick={() => void onOpen(path)}
      >
        <span>📄</span>
        <span className="workspace-file-name">{name}</span>
      </button>

      <div className="workspace-item-actions">
        <button
          className="small-action-button"
          type="button"
          title="Download saved file"
          aria-label={`Download ${name}`}
          onClick={() => void onDownload(path)}
        >
          ↓
        </button>

        <button
          className="small-action-button"
          type="button"
          title="Rename file"
          onClick={() => void onRename(path, true)}
        >
          ✎
        </button>
        <button
          className="small-action-button"
          type="button"
          title="Move file"
          onClick={() => void onMove(path)}
        >
          ↗
        </button>
        <button
          className="small-action-button"
          type="button"
          title="Delete file"
          onClick={() => void onDelete(path)}
        >
          ×
        </button>
      </div>
    </div>
  );
}


function WorkspaceDirectoryTree({
  item,
  path,
  directories,
  expandedDirectories,
  selectedFile,
  onToggleDirectory,
  onOpenFile,
  onRename,
  onMove,
  onDelete,
  onDownload,
}: {
  item: LabFile;
  path: string;
  directories: Record<string, WorkspaceDirectoryState>;
  expandedDirectories: Record<string, boolean>;
  selectedFile: string | null;
  onToggleDirectory: (path: string) => void;
  onOpenFile: (path: string) => void;
  onRename: (path: string, isFile?: boolean) => void;
  onMove: (path: string) => void;
  onDelete: (path: string) => void;
  onDownload: (path: string) => void;
}) {
  const isExpanded =
    expandedDirectories[path] ?? false;

  const directory =
    directories[path];

  return (
    <div className="workspace-directory-tree">
      <div className="workspace-file-row workspace-directory-row">
        <button
          className="workspace-file-item"
          type="button"
          title={path}
          onClick={() => void onToggleDirectory(path)}
        >
          <span>{isExpanded ? "▼" : "▶"}</span>
          <span>📁</span>
          <span className="workspace-file-name">{item.name}</span>
        </button>

        <div className="workspace-item-actions">
          <button
            className="small-action-button"
            type="button"
            title="Rename folder"
            onClick={() => void onRename(path)}
          >
            ✎
          </button>
          <button
            className="small-action-button"
            type="button"
            title="Move folder"
            onClick={() => void onMove(path)}
          >
            ↗
          </button>
          <button
            className="small-action-button"
            type="button"
            title="Delete folder"
            onClick={() => void onDelete(path)}
          >
            ×
          </button>
        </div>
      </div>

      {isExpanded && (
        <div className="workspace-directory-children">
          {directory?.loading ? (
            <p className="explorer-message">
              Loading...
            </p>
          ) : directory?.error ? (
            <p className="explorer-error">
              {directory.error}
            </p>
          ) : (
            directory?.items?.map((child) => {
              const childPath =
                path === "."
                  ? child.name
                  : `${path}/${child.name}`;

              if (child.type === "directory") {
                return (
                  <WorkspaceDirectoryTree
                    key={childPath}
                    item={child}
                    path={childPath}
                    directories={directories}
                    expandedDirectories={expandedDirectories}
                    selectedFile={selectedFile}
                    onToggleDirectory={onToggleDirectory}
                    onOpenFile={onOpenFile}
                    onRename={onRename}
                    onMove={onMove}
                    onDelete={onDelete} onDownload={onDownload}
                  />
                );
              }

              return (
                <WorkspaceFileRow
                  key={childPath}
                  path={childPath}
                  name={child.name}
                  selected={selectedFile === childPath}
                  onOpen={onOpenFile}
                  onRename={onRename}
                  onMove={onMove}
                  onDelete={onDelete} onDownload={onDownload}
                />
              );
            })
          )}
        </div>
      )}
    </div>
  );
}


type ApprovalStatus =
  | "pending"
  | "approved"
  | "declined";


function AccountStatus({
  status,
  onSignOut,
}: {
  status: ApprovalStatus;
  onSignOut: () => void;
}) {
  const declined =
    status === "declined";

  return (
    <main className="account-status-screen">
      <section className="account-status-card">
        <h1>
          {declined
            ? "Account access unavailable"
            : "Your account is awaiting approval"}
        </h1>

        <p>
          {declined
            ? "This account has not been granted access to WiByte Python Lab. Contact WiByte if you believe this is a mistake."
            : "Your account has been created successfully. A WiByte administrator must approve it before you can use WiByte Python Lab."}
        </p>

        <button
          type="button"
          onClick={onSignOut}
        >
          Sign out
        </button>
      </section>
    </main>
  );
}


function App() {
  if (
    window.location.pathname ===
    "/reset-password"
  ) {
    return <ResetPasswordScreen />;
  }

  const [
    session,
    setSession,
  ] = useState<Session | null>(null);

  const [
    currentUser,
    setCurrentUser,
  ] = useState<User | null>(null);

  const [
    approvalStatus,
    setApprovalStatus,
  ] = useState<ApprovalStatus | null>(null);

  const [
    authLoading,
    setAuthLoading,
  ] = useState(true);

  const loadAccountAccess =
    useCallback(
      async (user: User) => {
        const {
          data,
          error,
        } = await supabase
          .from("profiles")
          .select("approval_status")
          .eq("id", user.id)
          .maybeSingle();

        if (error) {
          throw error;
        }

        return data?.approval_status as
          | ApprovalStatus
          | undefined;
      },
      []
    );

  useEffect(() => {
    let active = true;

    const applySession =
      async (nextSession: Session | null) => {
        if (!active) {
          return;
        }

        setSession(nextSession);
        setCurrentUser(
          nextSession?.user ?? null
        );

        if (!nextSession?.user) {
          setApprovalStatus(null);
          setAuthLoading(false);
          return;
        }

        try {
          const status =
            await loadAccountAccess(
              nextSession.user
            );

          if (!active) {
            return;
          }

          /*
           * A missing profile is treated as pending.
           * The database trigger supplied with this update
           * normally creates the profile automatically.
           */
          setApprovalStatus(
            status ?? "pending"
          );
        } catch (error) {
          console.error(
            "Failed to load account access:",
            error
          );

          if (active) {
            setApprovalStatus("pending");
          }
        } finally {
          if (active) {
            setAuthLoading(false);
          }
        }
      };

    const {
      data: {
        subscription,
      },
    } = supabase.auth.onAuthStateChange(
      (_event, nextSession) => {
        void applySession(nextSession);
      }
    );

    void supabase.auth
      .getSession()
      .then(({ data }) =>
        applySession(data.session)
      )
      .catch((error) => {
        console.error(
          "Failed to load authentication session:",
          error
        );

        if (active) {
          setAuthLoading(false);
        }
      });

    return () => {
      active = false;
      subscription.unsubscribe();
    };
  }, [loadAccountAccess]);

  async function handleSignOut() {
    const {
      error,
    } = await supabase.auth.signOut();

    if (error) {
      console.error(
        "Failed to sign out:",
        error
      );
    }
  }

  if (authLoading) {
    return (
      <main className="auth-loading">
        <div className="auth-loading-card">
          Checking your sign-in...
        </div>
      </main>
    );
  }

  if (!session) {
    return <LoginScreen />;
  }

  if (approvalStatus !== "approved") {
    return (
      <AccountStatus
        status={
          approvalStatus ??
          "pending"
        }
        onSignOut={() =>
          void handleSignOut()
        }
      />
    );
  }

  return (
    <LabApp
      key={currentUser?.id ?? "anonymous"}
      currentUser={currentUser}
      handleSignOut={handleSignOut}
    />
  );
}


export default App;
