import { useEffect, useState } from "react";
import Terminal from "./Terminal";
import "./App.css";

const API_URL = import.meta.env.VITE_API_URL;

function App() {
  const [backendStatus, setBackendStatus] = useState("Checking backend...");
  const [labId, setLabId] = useState<string | null>(null);
  const [creatingLab, setCreatingLab] = useState(false);

  useEffect(() => {
    fetch(`${API_URL}/health`)
      .then((response) => {
        if (!response.ok) {
          throw new Error("Backend returned an error");
        }

        return response.json();
      })
      .then((data) => {
        setBackendStatus(data.status);
      })
      .catch(() => {
        setBackendStatus("Backend unavailable");
      });
  }, []);

  async function createLab() {
    setCreatingLab(true);

    try {
      const response = await fetch(`${API_URL}/labs`, {
        method: "POST",
      });

      if (!response.ok) {
        throw new Error("Failed to create lab");
      }

      const data = await response.json();

      setLabId(data.lab_id);
    } catch (error) {
      console.error(error);
      alert("Failed to create lab");
    } finally {
      setCreatingLab(false);
    }
  }

  async function deleteLab() {
    if (!labId) {
      return;
    }

    try {
      const response = await fetch(`${API_URL}/labs/${labId}`, {
        method: "DELETE",
      });

      if (!response.ok) {
        throw new Error("Failed to delete lab");
      }

      setLabId(null);
    } catch (error) {
      console.error(error);
      alert("Failed to delete lab");
    }
  }

  return (
    <main className="app">
      <header className="header">
        <div>
          <h1>WiByte Labs</h1>
          <p>Backend status: {backendStatus}</p>
        </div>

        {!labId && (
          <button
            onClick={createLab}
            disabled={creatingLab || backendStatus !== "ok"}
          >
            {creatingLab ? "Creating..." : "Create Lab"}
          </button>
        )}

        {labId && (
          <button onClick={deleteLab}>
            Close Lab
          </button>
        )}
      </header>

      <section className="terminal-container">
        {labId ? (
          <Terminal labId={labId} />
        ) : (
          <div className="empty-state">
            <h2>No active lab</h2>
            <p>Create a lab to open a terminal.</p>
          </div>
        )}
      </section>
    </main>
  );
}

export default App;