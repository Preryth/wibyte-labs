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

import "./App.css";


const API_URL =
  import.meta.env.VITE_API_URL;


type LabFile = {
  name: string;
  type: "file" | "directory";
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

      </header>


      {labId ? (

        <section className="workspace">

          <aside className="file-explorer">

            <div className="file-panel-header">

              <span>
                FILES
              </span>


              <button
                className="new-file-button"
                onClick={
                  createFile
                }
                title="New File"
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
                      file.type ===
                      "file"
                  )
                  .map(
                    (file) => (

                      <div
                        key={
                          file.name
                        }
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
                        >

                          <span className="file-name">
                            📄{" "}
                            {
                              file.name
                            }
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
                          >
                            ×
                          </button>

                        </div>

                      </div>

                    )
                  )}

              </div>

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

    </main>
  );
}


export default App;