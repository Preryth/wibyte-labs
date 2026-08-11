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
  if (labId) {
    alert(
      "Close the current lab before opening a GitHub repository."
    );

    return;
  }

  setOpeningRepositoryId(
    repositoryId
  );

  setCreatingLab(true);

  try {
    const response =
      await fetch(
        `${API_URL}/labs?github_repository_id=${encodeURIComponent(
          repositoryId
        )}`,
        {
          method: "POST",
        }
      );

    if (!response.ok) {
      const error =
        await response
          .json()
          .catch(() => null);

      throw new Error(
        error?.detail ??
          "Failed to open GitHub repository."
      );
    }

    const data =
      await response.json();

    setLabId(
      data.lab_id
    );

    setFiles([]);

    setSelectedFile(
      null
    );

    setFileContent("");

    setRunning(false);

  } catch (error) {
    console.error(
      "Failed to open GitHub repository:",
      error
    );

    alert(
      error instanceof Error
        ? error.message
        : "Failed to open GitHub repository."
    );
  } finally {
    setOpeningRepositoryId(
      null
    );

    setCreatingLab(false);
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

  /*
   * Create lab
   */

  async function createLab() {
    setCreatingLab(true);

    try {
      const response =
        await fetch(
          `${API_URL}/labs`,
          {
            method: "POST",
          }
        );


      if (!response.ok) {
        throw new Error(
          "Failed to create lab"
        );
      }


      const data =
        await response.json();


      setLabId(
        data.lab_id
      );

      setFiles([]);

      setSelectedFile(
        null
      );

      setFileContent("");

      setRunning(false);

    } catch (error) {
      console.error(error);

      alert(
        "Failed to create lab"
      );

    } finally {
      setCreatingLab(
        false
      );
    }
  }


  /*
   * Close lab
   */

  async function deleteLab() {
    if (!labId) {
      return;
    }


    if (
      !window.confirm(
        "Close this lab? All files in this lab will be lost."
      )
    ) {
      return;
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


  /*
   * Load files when lab changes
   */

  useEffect(() => {
    if (!labId) {
      return;
    }


    loadFiles(
      labId
    );
  }, [labId]);


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


      await openFile(
        path
      );

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

      void reportLabActivity(
        labId
      );


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
                            creatingLab ||
                            Boolean(labId)
                          }
                        >
                          {openingRepositoryId ===
                          repository.id
                            ? "Opening..."
                            : "Open"}
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
                                    >
                                      📄{" "}
                                      {item.name}
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
          <span>
            WORKSPACE
          </span>

          <button
            className="new-file-button"
            onClick={
              createFile
            }
            title="New File"
            type="button"
          >
            +
          </button>
        </div>

        {files.length === 0 ? (
          <p className="empty-files">
            No files
          </p>
        ) : (
          <div className="file-list">
            {files
              .filter(
                (file) =>
                  file.type === "file"
              )
              .map(
                (file) => (
                  <div
                    key={file.name}
                    className={
                      selectedFile ===
                      file.name
                        ? "file-row selected"
                        : "file-row"
                    }
                  >
                    <button
                      className="file-item"
                      onClick={() =>
                        openFile(
                          file.name
                        )
                      }
                      title={
                        file.name
                      }
                      type="button"
                    >
                      <span className="file-name">
                        📄{" "}
                        {file.name}
                      </span>
                    </button>

                    <div className="file-actions">
                      <button
                        className="file-action-button"
                        onClick={() =>
                          renameFile(
                            file.name
                          )
                        }
                        title="Rename"
                        type="button"
                      >
                        ✎
                      </button>

                      <button
                        className="file-action-button delete"
                        onClick={() =>
                          deleteFile(
                            file.name
                          )
                        }
                        title="Delete"
                        type="button"
                      >
                        ×
                      </button>
                    </div>
                  </div>
                )
              )}
          </div>
        )}
      </section>
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

function GitHubDirectoryTree({
  repositoryId,
  item,
  githubDirectories,
  expandedDirectories,
  onToggleDirectory,
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
                    >
                      📄{" "}
                      {child.name}
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