import { useEffect, useRef, useState } from "react";
import { supabase } from "./lib/supabase";

export function useLabFullscreen() {
  const fullscreenRef = useRef<HTMLElement | null>(null);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [fullscreenBusy, setFullscreenBusy] = useState(false);
  const [fullscreenError, setFullscreenError] = useState("");
  const pending = useRef(false);

  useEffect(() => {
    const change = () => {
      setIsFullscreen(document.fullscreenElement === fullscreenRef.current);
      window.requestAnimationFrame(() => window.dispatchEvent(new Event("resize")));
    };
    document.addEventListener("fullscreenchange", change);
    return () => document.removeEventListener("fullscreenchange", change);
  }, []);

  async function toggleFullscreen() {
    if (pending.current) return;
    pending.current = true;
    setFullscreenBusy(true);
    setFullscreenError("");
    try {
      const root = fullscreenRef.current;
      if (!root) return;
      if (document.fullscreenElement === root) {
        await document.exitFullscreen();
      } else {
        if (!document.fullscreenEnabled || !root.requestFullscreen) {
          throw new Error("Full screen is unavailable in this browser or window.");
        }
        await root.requestFullscreen();
      }
    } catch (error) {
      setFullscreenError(error instanceof Error ? error.message : "Could not change full-screen mode.");
    } finally {
      pending.current = false;
      setFullscreenBusy(false);
    }
  }

  return {
    fullscreenRef, isFullscreen, fullscreenBusy, fullscreenError, toggleFullscreen,
  };
}

type Entry = { name: string; type: "file" | "directory" };

export function FullscreenFilePicker({ labId, selectedFile, disabled, enabled, onOpen }: {
  labId: string; selectedFile: string | null; disabled: boolean; enabled: boolean;
  onOpen: (path: string) => Promise<void>;
}) {
  const [paths, setPaths] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [refresh, setRefresh] = useState(0);

  useEffect(() => {
    if (!enabled) return;
    const controller = new AbortController();
    let active = true;
    setLoading(true);
    setError("");
    setPaths([]);

    async function load() {
      const found: string[] = [];
      const queue = [""];
      let directories = 0;
      try {
        const { data } = await supabase.auth.getSession();
        if (!data.session) throw new Error("Please sign in again.");
        while (queue.length) {
          if (controller.signal.aborted) return;
          if (++directories > 250 || found.length >= 5000) {
            throw new Error("File list is very large. Exit full screen to browse all files.");
          }
          const directory = queue.shift()!;
          const suffix = directory ? `?path=${encodeURIComponent(directory)}` : "";
          const response = await fetch(
            `${import.meta.env.VITE_API_URL}/labs/${labId}/files${suffix}`,
            {
              headers: { Authorization: `Bearer ${data.session.access_token}` },
              credentials: "include", signal: controller.signal,
            },
          );
          const body = await response.json().catch(() => null);
          if (!response.ok || !Array.isArray(body?.files)) {
            throw new Error("Could not load all files. Use refresh or exit full screen.");
          }
          for (const item of body.files as Entry[]) {
            if (!item.name || item.name === "." || item.name === ".." || item.name.includes("/")) continue;
            const path = directory ? `${directory}/${item.name}` : item.name;
            if (item.type === "directory") {
              if (item.name !== ".git") queue.push(path);
            } else if (item.type === "file") {
              found.push(path);
            }
          }
        }
      } catch (err) {
        if (active && !controller.signal.aborted) {
          setError(err instanceof Error ? err.message : "Could not load files.");
        }
      } finally {
        if (active) {
          setPaths(found.sort((left, right) => left.localeCompare(right)));
          setLoading(false);
        }
      }
    }
    void load();
    return () => { active = false; controller.abort(); };
  }, [labId, enabled, refresh]);

  return <div className="wpl-focus-files">
    <label htmlFor="wpl-focus-file">File</label>
    <select id="wpl-focus-file" value={selectedFile ?? ""}
      disabled={disabled || loading}
      onChange={event => { if (event.target.value) void onOpen(event.target.value); }}>
      <option value="" disabled>{loading ? "Loading files…" : "Select a file"}</option>
      {selectedFile && !paths.includes(selectedFile) &&
        <option value={selectedFile}>{selectedFile}</option>}
      {paths.map(path => <option value={path} key={path}>{path}</option>)}
    </select>
    <button type="button" disabled={loading || disabled}
      onClick={() => setRefresh(value => value + 1)} aria-label="Refresh file list">
      ↻ Refresh files
    </button>
    {error && <small role="status">{error}</small>}
  </div>;
}
