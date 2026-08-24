import {
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";

import Terminal, {
  type TerminalHandle,
} from "./Terminal";

import CodeEditor from "./CodeEditor";
import SettingsPanel from "./SettingsPanel";

import "./App.css";


const API_URL =
  import.meta.env.VITE_API_URL;


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

type GitHubRepositoryItem = {
  name: string;
  type: "file" | "directory";
  path: string;
  size?: number;
  html_url?: string | null;
};

type GitHubDirectoryState = {
  loading: boolean;
  items: GitHubRepositoryItem[];
  error: string | null;
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

function App() {
  const [
    backendStatus,
    setBackendStatus,
  ] = useState(
    "Checking backend..."
  );


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
    expandedRepositories,
    setExpandedRepositories,
  ] = useState<Record<string, boolean>>({});

  const [
    githubDirectories,
    setGithubDirectories,
  ] = useState<
    Record<string, GitHubDirectoryState>
  >({});

  const [
    openingRepositoryId,
    setOpeningRepositoryId,
  ] = useState<string | null>(null);
  const [
    activeGitHubRepositoryId,
    setActiveGitHubRepositoryId,
  ] = useState<string | null>(null);

  const [
    ,
    setGithubPreview,
  ] = useState<{ repositoryId: string; path: string } | null>(null);

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
            await fetch(
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


async function loadGitHubDirectory(
  repositoryId: string,
  path: string
) {
  const key =
    `${repositoryId}:${path}`;

  setGithubDirectories(
    (current) => ({
      ...current,
      [key]: {
        loading: true,
        items:
          current[key]?.items ?? [],
        error: null,
      },
    })
  );

  try {
    const response =
      await fetch(
        `${API_URL}/github/repositories/${encodeURIComponent(
          repositoryId
        )}/contents?path=${encodeURIComponent(
          path
        )}`
      );

    if (!response.ok) {
      const error =
        await response
          .json()
          .catch(() => null);

      throw new Error(
        error?.detail ??
          "Failed to load repository contents."
      );
    }

    const data =
      await response.json();

    setGithubDirectories(
      (current) => ({
        ...current,
        [key]: {
          loading: false,
          items: data.contents ?? [],
          error: null,
        },
      })
    );
  } catch (error) {
    console.error(
      "Failed to load GitHub directory:",
      error
    );

    setGithubDirectories(
      (current) => ({
        ...current,
        [key]: {
          loading: false,
          items: [],
          error:
            error instanceof Error
              ? error.message
              : "Failed to load directory.",
        },
      })
    );
  }
}
async function toggleGitHubRepository(
  repositoryId: string
) {
  const isExpanded =
    expandedRepositories[
      repositoryId
    ] ?? false;

  setExpandedRepositories(
    (current) => ({
      ...current,
      [repositoryId]: !isExpanded,
    })
  );

  if (isExpanded) {
    return;
  }

  await loadGitHubDirectory(
    repositoryId,
    ""
  );
}
const [
  expandedGitHubDirectories,
  setExpandedGitHubDirectories,
] = useState<
  Record<string, boolean>
>({});
async function toggleGitHubDirectory(
  repositoryId: string,
  path: string
) {
  const key =
    `${repositoryId}:${path}`;

  const isExpanded =
    expandedGitHubDirectories[key] ??
    false;

  setExpandedGitHubDirectories(
    (current) => ({
      ...current,
      [key]: !isExpanded,
    })
  );

  if (isExpanded) {
    return;
  }

  await loadGitHubDirectory(
    repositoryId,
    path
  );
}
async function openGitHubRepository(
  repositoryId: string
) {
  if (!labId) {
    alert("Create a Lab before selecting a GitHub repository.");
    return;
  }

  if (activeGitHubRepositoryId === repositoryId) {
    return;
  }

  const proceed = window.confirm(
    "Open this repository in the current Lab? Its files will be copied into the empty Lab workspace."
  );
  if (!proceed) return;

  setOpeningRepositoryId(repositoryId);
  try {
    const response = await fetch(
      `${API_URL}/github/labs/${labId}/repository`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ repository_id: repositoryId }),
      }
    );
    if (!response.ok) {
      const error = await response.json().catch(() => null);
      throw new Error(error?.detail ?? "Failed to open GitHub repository.");
    }
    setActiveGitHubRepositoryId(repositoryId);
    setGitStatus(null);
    setGitDiff(null);
    setSelectedFile(null);
    setGithubPreview(null);
    setFileContent("");
    await refreshWorkspaceTree();
  } catch (error) {
    alert(error instanceof Error ? error.message : "Failed to open GitHub repository.");
  } finally {
    setOpeningRepositoryId(null);
  }
}
  useEffect(() => {
    fetch(`${API_URL}/health`)
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
        await fetch(
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
        await fetch(
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

  async function createGitHubRepository() {
    const name = window.prompt("New GitHub repository name:")?.trim();
    if (!name) return;
    const description = window.prompt("Description (optional):") ?? "";
    const isPrivate = window.confirm("Make this repository private? Click Cancel for public.");
    setGithubLoading(true);
    try {
      const response = await fetch(`${API_URL}/github/repositories`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, description, private: isPrivate }),
      });
      if (!response.ok) {
        const error = await response.json().catch(() => null);
        throw new Error(error?.detail ?? "Failed to create repository");
      }
      await loadGitHubRepositories();
    } catch (error) {
      alert(error instanceof Error ? error.message : "Failed to create repository");
    } finally {
      setGithubLoading(false);
    }
  }

  /*
   * Create lab
   */

  async function createLab() {
    setCreatingLab(true);
    try {
      const response = await fetch(`${API_URL}/labs`, { method: "POST" });
      if (!response.ok) { const error = await response.json().catch(() => null); throw new Error(error?.detail ?? "Failed to create lab"); }
      const data = await response.json();
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
        const provisionResponse = await fetch(`${API_URL}/github/labs/${data.lab_id}/workspace-repository`, { method: "POST" });
        if (!provisionResponse.ok) { const error = await provisionResponse.json().catch(() => null); throw new Error(error?.detail ?? "Failed to create the workspace repository"); }
        repository = (await provisionResponse.json()).repository;
      }
      setActiveGitHubRepositoryId(repository?.id ?? null);
      await loadFiles(data.lab_id);
      if (repository?.id) {
        const statusResponse = await fetch(`${API_URL}/github/labs/${data.lab_id}/git/status`);
        if (statusResponse.ok) setGitStatus(await statusResponse.json());
      }
      void loadGitHubRepositories();
    } catch (error) {
      console.error(error); alert(error instanceof Error ? error.message : "Failed to create lab");
    } finally { setCreatingLab(false); }
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


    try {
      /*
       * If a process is running,
       * request that it stops first.
       */

      if (running) {
        terminalRef.current?.stopProcess();
      }


      const response =
        await fetch(
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
        await fetch(
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

      const response = await fetch(
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
      const response = await fetch(
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
    if (!labId || !activeGitHubRepositoryId) {
      return;
    }

    setGitLoading(true);

    try {
      const response = await fetch(
        `${API_URL}/github/labs/${labId}/git/status`
      );

      if (!response.ok) {
        const error = await response.json().catch(() => null);
        throw new Error(error?.detail ?? "Failed to load Git status");
      }

      setGitStatus(await response.json());
    } catch (error) {
      alert(
        error instanceof Error
          ? error.message
          : "Failed to load Git status"
      );
    } finally {
      setGitLoading(false);
    }
  }

  async function loadGitDiff() {
    if (!labId || !activeGitHubRepositoryId) {
      return;
    }

    setGitLoading(true);

    try {
      const response = await fetch(
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
    if (!labId || !activeGitHubRepositoryId) {
      return;
    }

    const message = window.prompt("Commit message:")?.trim();
    if (!message) {
      return;
    }

    setGitLoading(true);

    try {
      const response = await fetch(
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
      setGitLoading(false);
    }
  }

  async function pushGitChanges() {
    if (!labId || !activeGitHubRepositoryId) {
      return;
    }

    setGitLoading(true);

    try {
      const response = await fetch(
        `${API_URL}/github/labs/${labId}/git/push`,
        { method: "POST" }
      );

      if (!response.ok) {
        const error = await response.json().catch(() => null);
        throw new Error(error?.detail ?? "Failed to push changes");
      }

      const data = await response.json();
      setGitStatus(data.status ?? null);
      alert(data.output || "Push completed.");
    } catch (error) {
      alert(
        error instanceof Error
          ? error.message
          : "Failed to push changes"
      );
    } finally {
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
      const response = await fetch(
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
      fileName.trim();


    if (!path) {
      return;
    }


    try {
      const response =
        await fetch(
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
        await fetch(
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
  async function openGitHubFile(
    repositoryId: string,
    filePath: string
  ) {
    setLoadingFile(true);
    try {
      const response = await fetch(
        `${API_URL}/github/repositories/${encodeURIComponent(repositoryId)}/file?path=${encodeURIComponent(filePath)}`
      );
      if (!response.ok) {
        const error = await response.json().catch(() => null);
        throw new Error(error?.detail ?? "Failed to load GitHub file");
      }
      const data = await response.json();
      setSelectedFile(null);
      setGithubPreview({ repositoryId, path: data.path });
      setFileContent(data.content);
    } catch (error) {
      alert(error instanceof Error ? error.message : "Failed to load GitHub file");
    } finally {
      setLoadingFile(false);
    }
  }

  async function editGitHubFile(
    repositoryId: string,
    filePath: string
  ) {
    if (!labId) {
      alert("Create a Lab and select this repository before editing its files.");
      return;
    }
    if (activeGitHubRepositoryId !== repositoryId) {
      alert("Select this repository for the active Lab before editing its files.");
      return;
    }
    if (!window.confirm(`Copy ${filePath} into the Lab workspace and edit it there?`)) return;
    try {
      const source = await fetch(
        `${API_URL}/github/repositories/${encodeURIComponent(repositoryId)}/file?path=${encodeURIComponent(filePath)}`
      );
      if (!source.ok) {
        const error = await source.json().catch(() => null);
        throw new Error(error?.detail ?? "Failed to download GitHub file");
      }
      const data = await source.json();
      const response = await fetch(
        `${API_URL}/labs/${labId}/files/${encodeURIComponent(filePath)}`,
        {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ content: data.content }),
        }
      );
      if (!response.ok) {
        const error = await response.json().catch(() => null);
        throw new Error(error?.detail ?? "Failed to copy file into Lab");
      }
      setGithubPreview(null);
      await refreshWorkspaceTree();
      await openFile(filePath);
    } catch (error) {
      alert(error instanceof Error ? error.message : "Failed to prepare GitHub file for editing");
    }
  }

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
        await fetch(
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
    oldPath: string
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
      newName.trim();


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
        await fetch(
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


      await loadFiles(
        labId
      );


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
        await fetch(
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
      const startResponse = await fetch(
        `${API_URL}/labs/${labId}/gui/start`,
        { method: "POST" }
      );

      if (!startResponse.ok) {
        const detail = await startResponse.text();
        throw new Error(
          detail || "Failed to start GUI environment."
        );
      }

      const connectionResponse = await fetch(
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

      <header className="header">

        <div>

          <h1>
            WiByte Labs
          </h1>

          <p>
            Backend status:{" "}
            {backendStatus}
          </p>

        </div>


        {!labId && (
          <button
            onClick={
              createLab
            }
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
  <section className="workspace">
    <aside className="file-explorer">
      {/* =====================================================
          GITHUB
          ===================================================== */}
      <section className="explorer-section github-section">
        <div className="file-panel-header">
          <span>
            GITHUB
          </span>

          <div className="explorer-header-actions">
            <button
              className="small-action-button"
              onClick={() => void createGitHubRepository()}
              disabled={githubLoading || !githubConnected}
              title="Create GitHub repository"
              type="button"
            >
              +
            </button>

            <button
              className="small-action-button"
              onClick={() =>
                void loadGitHubRepositories()
              }
              disabled={githubLoading}
              title="Refresh GitHub"
              type="button"
            >
              ↻
            </button>
          </div>
        </div>

        {githubLoading ? (
          <p className="explorer-message">
            Loading GitHub...
          </p>
        ) : githubError ? (
          <p className="explorer-error">
            {githubError}
          </p>
        ) : !githubConnected ? (
          <div className="github-connect-banner">
            <strong>
              GitHub isn't connected
            </strong>

            <span>
              Connect GitHub in Settings to
              browse your repositories.
            </span>

            <button
              type="button"
              onClick={() =>
                setSettingsOpen(true)
              }
            >
              Connect GitHub
            </button>
          </div>
        ) : (
          <div className="github-panel-content">
            <div className="github-account-row">
              @{githubUsername}
            </div>

            {githubRepositories.length === 0 ? (
              <p className="explorer-message">
                No repositories found.
              </p>
            ) : (
              githubRepositories.map(
                (repository) => {
                  const isExpanded =
                    expandedRepositories[
                      repository.id
                    ] ?? false;

                  const rootKey =
                    `${repository.id}:`;

                  const rootDirectory =
                    githubDirectories[
                      rootKey
                    ];

                  return (
                    <div
                      key={repository.id}
                      className="github-repository"
                    >
                      <div className="github-repository-header">
                        <button
                          className="github-repository-toggle"
                          type="button"
                          onClick={() =>
                            void toggleGitHubRepository(
                              repository.id
                            )
                          }
                        >
                          {isExpanded
                            ? "▼"
                            : "▶"}{" "}
                          📁{" "}
                          {repository.name}
                        </button>

                        <button
                          className="repo-open-button"
                          type="button"
                          onClick={() =>
                            void openGitHubRepository(
                              repository.id
                            )
                          }
                          disabled={
                            openingRepositoryId ===
                              repository.id ||
                            creatingLab
                          }
                        >
                          {openingRepositoryId ===
                          repository.id
                            ? "Opening..."
                            : activeGitHubRepositoryId === repository.id
                            ? "Active"
                            : "Use"}
                        </button>
                      </div>

                      {repository.description && (
                        <div className="github-repository-description">
                          {repository.description}
                        </div>
                      )}

                      {isExpanded && (
                        <div>
                          {rootDirectory?.loading ? (
                            <p className="explorer-message">
                              Loading...
                            </p>
                          ) : rootDirectory?.error ? (
                            <p className="explorer-error">
                              {rootDirectory.error}
                            </p>
                          ) : (
                            rootDirectory?.items?.map(
                              (item) => (
                                item.type ===
                                "directory" ? (
                                  <GitHubDirectoryTree
                                  key={item.path}
                                  repositoryId={
                                    repository.id
                                  }
                                  item={item}
                                  githubDirectories={
                                    githubDirectories
                                    }
                                    expandedDirectories={
                                        expandedGitHubDirectories
                                    }
                                    onToggleDirectory={
                                        toggleGitHubDirectory
                                    }
                                    onOpenFile={openGitHubFile}
                                    onEditFile={editGitHubFile}
                                  />
                                ) : (
                                  <div
                                    key={item.path}
                                    className="github-file-row"
                                  >
                                    <button
                                      className="github-file-item"
                                      type="button"
                                      title={item.path}
                                      onClick={() =>
                                          void openGitHubFile(
                                            repository.id,
                                            item.path
                                          )
                                        }
                                        >
                                          📄{" "}
                                          {item.name}
                                    </button>
                                    <button
                                      className="repo-open-button"
                                      type="button"
                                      onClick={() => void editGitHubFile(repository.id, item.path)}
                                    >
                                      Edit
                                    </button>
                                  </div>
                                )
                              )
                            )
                          )}
                        </div>
                      )}
                    </div>
                  );
                }
              )
            )}
          </div>
        )}
      </section>

      {/* =====================================================
          WORKSPACE
          ===================================================== */}
      <section className="explorer-section workspace-section">
        <div className="file-panel-header">
          <span>WORKSPACE</span>

          <div className="explorer-header-actions">
            <button
              className="small-action-button"
              onClick={() => void refreshWorkspaceTree()}
              title="Refresh workspace"
              type="button"
            >
              ↻
            </button>

            <button
              className="new-file-button"
              onClick={createFile}
              title="New file"
              type="button"
            >
              +
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
                    onDelete={deleteFile}
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
                  onDelete={deleteFile}
                />
              );
            })}
          </div>
        )}
      </section>

      {/* =====================================================
          GIT
          ===================================================== */}
      {activeGitHubRepositoryId && (
        <section className="explorer-section git-section">
          <div className="file-panel-header">
            <span>GIT</span>
            <button
              className="small-action-button"
              onClick={() => void loadGitStatus()}
              disabled={gitLoading}
              title="Refresh Git status"
              type="button"
            >
              ↻
            </button>
          </div>

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
        </section>
      )}

    </aside>

    <section className="editor-terminal">
      <div className="editor-section">
        <div className="editor-header">
          <span>
            {selectedFile ??
              "No file selected"}
          </span>

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
            <div className="editor-message">
              Select a file to start
              editing.
            </div>
          )}
        </div>
      </div>

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
      Create a lab to start coding.
    </p>
  </section>
)}

{settingsOpen && (
  <SettingsPanel
    apiUrl={API_URL}
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
}: {
  path: string;
  name: string;
  selected: boolean;
  onOpen: (path: string) => void;
  onRename: (path: string) => void;
  onMove: (path: string) => void;
  onDelete: (path: string) => void;
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
          title="Rename file"
          onClick={() => void onRename(path)}
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
}: {
  item: LabFile;
  path: string;
  directories: Record<string, WorkspaceDirectoryState>;
  expandedDirectories: Record<string, boolean>;
  selectedFile: string | null;
  onToggleDirectory: (path: string) => void;
  onOpenFile: (path: string) => void;
  onRename: (path: string) => void;
  onMove: (path: string) => void;
  onDelete: (path: string) => void;
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
                    onDelete={onDelete}
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
                  onDelete={onDelete}
                />
              );
            })
          )}
        </div>
      )}
    </div>
  );
}


function GitHubDirectoryTree({
  repositoryId,
  item,
  githubDirectories,
  expandedDirectories,
  onToggleDirectory,
  onOpenFile,
  onEditFile,
}: {
  repositoryId: string;
  item: GitHubRepositoryItem;
  githubDirectories: Record<
    string,
    GitHubDirectoryState
  >;
  expandedDirectories: Record<
    string,
    boolean
  >;
  onToggleDirectory: (
    repositoryId: string,
    path: string
  ) => void;
  onOpenFile: (
    repositoryId: string,
    filePath: string
  ) => void;
  onEditFile: (
    repositoryId: string,
    filePath: string
  ) => void;
}) {
  const key =
    `${repositoryId}:${item.path}`;

  const isExpanded =
    expandedDirectories[key] ??
    false;

  const directory =
    githubDirectories[key];

  return (
    <div>

      <div className="github-file-row">

        <button
          className="github-file-item"
          type="button"
          onClick={() =>
            onToggleDirectory(
              repositoryId,
              item.path
            )
          }
        >
          {isExpanded
            ? "▼"
            : "▶"}{" "}
          📁{" "}
          {item.name}
        </button>

      </div>


      {isExpanded && (

        <div
          style={{
            paddingLeft: "16px",
          }}
        >

          {directory?.loading ? (

            <p className="explorer-message">
              Loading...
            </p>

          ) : directory?.error ? (

            <p className="explorer-error">
              {directory.error}
            </p>

          ) : (

            directory?.items?.map(
              (child) => (

                child.type ===
                "directory" ? (

                  <GitHubDirectoryTree
                    key={child.path}
                    repositoryId={
                      repositoryId
                    }
                    item={child}
                    githubDirectories={
                      githubDirectories
                    }
                    expandedDirectories={
                      expandedDirectories
                    }
                    onToggleDirectory={
                      onToggleDirectory
                    }
                    onOpenFile={onOpenFile}
                    onEditFile={onEditFile}
                  />

                ) : (

                  <div
                    key={child.path}
                    className="github-file-row"
                  >

                    <button
                    className="github-file-item"
                    type="button"
                    title={
                        child.path
                      }
                      onClick ={() =>
                        void onOpenFile(
                          repositoryId,
                          child.path
                        )
                      }
                    >
                      📄{" "}
                      {child.name}
                    </button>
                    <button
                      className="repo-open-button"
                      type="button"
                      onClick={() => void onEditFile(repositoryId, child.path)}
                    >
                      Edit
                    </button>

                  </div>

                )

              )
            )

          )}

        </div>

      )}

    </div>
  );
}


export default App;