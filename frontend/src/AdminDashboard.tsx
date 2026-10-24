import { useEffect, useRef, useState } from "react";
import { supabase } from "./lib/supabase";
import "./AdminDashboard.css";

type Section = "Overview" | "Users" | "Active labs" | "Platform health" | "Activity history";
type Resources = {
  cpu_percent: number; cpu_cores: number; load_average: number[];
  memory_used: number; memory_total: number; disk_used: number; disk_total: number;
};
type Overview = {
  students: number; approved: number; pending: number; active_labs: number;
  recovery_labs: number; suspended: number; resources: Resources; checked_at: string;
};
type Student = {
  id: string; email: string; role: string; approval_status: string;
  github_username: string | null; suspended: number; active_labs: number;
};
type Lab = {
  id: string; email: string; status: string; created_at: string;
  last_activity_at: string; repository: string | null;
  timeout_outcome: string | null; timeout_message: string | null;
};
type Event = {
  id: number; occurred_at: string; actor_email: string | null;
  action: string; target_id: string | null; outcome: string;
};
type Service = {
  name: string; status: string; detail: string; latency_ms: number | null;
};
type Usage = {
  cpu_percent: number; memory_used: number; memory_limit: number; processes: number;
};
const sections: Section[] = ["Overview", "Users", "Active labs", "Platform health", "Activity history"];

async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const { data } = await supabase.auth.getSession();
  if (!data.session) throw new Error("Your session has expired. Please sign in again.");
  const headers = new Headers(init.headers);
  headers.set("Authorization", `Bearer ${data.session.access_token}`);
  const response = await fetch(`${import.meta.env.VITE_API_URL}/admin${path}`, {
    ...init, headers, cache: "no-store",
  });
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    throw new Error(typeof body?.detail === "string" ? body.detail : "Could not load dashboard data.");
  }
  return body as T;
}

function date(value: string) {
  const normalized = /(?:Z|[+-]\d\d:\d\d)$/.test(value) ? value : value.replace(" ", "T") + "Z";
  const result = new Date(normalized);
  return Number.isNaN(result.getTime()) ? "Unavailable" : result.toLocaleString();
}
function bytes(value: number) {
  return `${(value / 1024 ** 3).toFixed(2)} GB`;
}
function label(value: string) {
  return value.replace(/[._]/g, " ");
}
function Badge({ value }: { value: string }) {
  const good = ["approved", "healthy", "running", "success"].includes(value);
  const bad = ["rejected", "suspended", "unavailable", "failed", "save_failed"].includes(value);
  return <span className={`wb-admin-badge ${good ? "wb-admin-good" : bad ? "wb-admin-bad" : "wb-admin-warn"}`}>{label(value)}</span>;
}
function Meter({ title, value, detail }: { title: string; value: number; detail: string }) {
  return <div className="wb-admin-meter">
    <div><strong>{title}</strong><span>{value.toFixed(1)}%</span></div>
    <progress max={100} value={Math.min(100, Math.max(0, value))} />
    <small>{detail}</small>
  </div>;
}

export default function AdminDashboard({ onSignOut }: { onSignOut: () => Promise<void> }) {
  const [section, setSection] = useState<Section>("Overview");
  const [email, setEmail] = useState<string | null>(null);
  const [adminId, setAdminId] = useState<string | null>(null);
  const [accessError, setAccessError] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const busyRef = useRef(false);
  const [reload, setReload] = useState(0);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState<number | null>(0);
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("all");
  const [overview, setOverview] = useState<Overview | null>(null);
  const [students, setStudents] = useState<Student[]>([]);
  const [labs, setLabs] = useState<Lab[]>([]);
  const [events, setEvents] = useState<Event[]>([]);
  const [services, setServices] = useState<Service[]>([]);
  const [updated, setUpdated] = useState("");
  const [usage, setUsage] = useState<Record<string, Usage>>({});

  useEffect(() => {
    let active = true;
    api<{ id: string; email: string }>("/me").then(data => {
      if (active) {
        setEmail(data.email);
        setAdminId(data.id);
      }
    }).catch(err => {
      if (active) setAccessError(err instanceof Error ? err.message : "Access unavailable.");
    });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    if (!email) return;
    let active = true;
    setLoading(true);
    setError("");
    async function load() {
      try {
        if (section === "Overview") {
          const data = await api<Overview>("/overview");
          if (active) setOverview(data);
        } else if (section === "Users") {
          const data = await api<{ students: Student[]; total: number | null }>(
            `/students?page=${page}&q=${encodeURIComponent(query)}&status=${filter}`
          );
          if (active) { setStudents(data.students); setTotal(data.total); }
        } else if (section === "Active labs") {
          const data = await api<{ labs: Lab[]; total: number }>(`/labs?page=${page}`);
          if (active) { setLabs(data.labs); setTotal(data.total); }
        } else if (section === "Activity history") {
          const data = await api<{ events: Event[]; total: number }>(`/activity?page=${page}`);
          if (active) { setEvents(data.events); setTotal(data.total); }
        } else {
          const data = await api<{ services: Service[] }>("/health");
          if (active) setServices(data.services);
        }
        if (active) setUpdated(new Date().toLocaleTimeString());
      } catch (err) {
        if (active) setError(err instanceof Error ? err.message : "Could not load data.");
      } finally {
        if (active) setLoading(false);
      }
    }
    void load();
    return () => { active = false; };
  }, [email, section, page, query, filter, reload]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      if (!busyRef.current && !document.hidden) setReload(value => value + 1);
    }, section === "Platform health" ? 60000 : 30000);
    return () => window.clearInterval(timer);
  }, [section]);

  async function changeStudent(student: Student, action: string) {
    if (busyRef.current) return;
    const confirmation = action === "reject"
      ? `Reject ${student.email}?\n\nTheir Supabase status will become rejected and they will lose access to the lab and dashboard. Their account and existing lab files will be kept. They can request approval again, or you can accept them later. This does not delete their account.`
      : `${label(action)} access for ${student.email}? Existing lab files will be kept.`;
    if (!window.confirm(confirmation)) return;
    busyRef.current = true;
    setBusy(true);
    setError("");
    try {
      await api(`/students/${student.id}/access`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action, confirm_rejection: action === "reject" }),
      });
      setReload(value => value + 1);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not update access.");
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  }

  async function manageAccount(student: Student, operation: "delete" | "removeAdmin") {
    if (busyRef.current) return;
    let confirmationEmail = "";
    if (operation === "delete") {
      const entered = window.prompt(
        `Permanently delete ${student.email}?\n\nThis removes their login, profile, and local GitHub connection. They must sign up again to return. Repositories already on GitHub are not deleted.\n\nAny remaining labs must be closed first.\nType their full email to confirm:`
      );
      if (entered === null) return;
      confirmationEmail = entered.trim();
      if (confirmationEmail.toLowerCase() !== student.email.toLowerCase()) {
        setError("Email did not match. No account was deleted.");
        return;
      }
    } else if (!window.confirm(
      `Remove administrator access from ${student.email}?\n\nThey become a normal student. Their account, approval status, lab files, and GitHub connection are kept.`
    )) return;

    busyRef.current = true;
    setBusy(true);
    setError("");
    try {
      if (operation === "delete") {
        await api(`/students/${student.id}`, {
          method: "DELETE",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ confirmation_email: confirmationEmail }),
        });
        alert("Account deleted. This person must sign up again to return.");
      } else {
        await api(`/administrators/${student.id}/remove`, { method: "POST" });
        alert("Admin access removed. The account is now a student account.");
      }
      setPage(1);
      setReload(value => value + 1);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not update this account.");
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  }

  async function grantAdmin(student?: Student) {
    if (busyRef.current) return;
    const targetEmail = (student?.email ??
      window.prompt("Email of the existing approved account to make admin:") ?? "").trim();
    if (!targetEmail) return;
    if (!window.confirm(
      `Grant full administrator access to ${targetEmail}? This allows managing student access and viewing platform activity.`
    )) return;

    busyRef.current = true;
    setBusy(true);
    setError("");
    try {
      const result = await api<{ email: string; status: string }>("/administrators", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: targetEmail }),
      });
      alert(result.status === "already_admin"
        ? `${result.email} already has admin access.`
        : `Admin access granted to ${result.email}.`);
      setReload(value => value + 1);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not grant admin access.");
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  }

  async function terminateLab(lab: Lab, mode: "save" | "discard") {
    if (busyRef.current) return;
    const confirmed = window.confirm(
      mode === "save"
        ? `Commit and push the saved container files for ${lab.email}, then terminate their lab? Running programs will stop.`
        : `Terminate ${lab.email}'s lab WITHOUT saving? Unpushed changes will be permanently lost.`
    );
    if (!confirmed) return;

    busyRef.current = true;
    setBusy(true);
    setError("");
    try {
      const result = await api<{ message: string }>(`/labs/${lab.id}/terminate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode }),
      });
      alert(result.message);
      setPage(1);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not complete the action.");
    } finally {
      busyRef.current = false;
      setBusy(false);
      setReload(value => value + 1);
    }
  }

  async function inspectUsage(id: string) {
    try {
      const data = await api<Usage>(`/labs/${id}/resources`);
      setUsage(current => ({ ...current, [id]: data }));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Resource usage unavailable.");
    }
  }

  if (!email) return <main className="admin-dashboard wb-admin-access">
    <div className="wb-admin-card">
      <div className="wb-admin-eyebrow">WIBYTE ADMIN</div>
      <h1>{accessError ? "Dashboard unavailable" : "Checking admin access..."}</h1>
      {accessError && <p role="alert">{accessError}</p>}
      <a href="/">Open Python Lab</a>
      {accessError && <button onClick={() => window.location.reload()}>Retry</button>}
    </div>
  </main>;

  const metrics = overview?.resources;
  const paginated = ["Users", "Active labs", "Activity history"].includes(section);

  return <main className="admin-dashboard">
    <header className="wb-admin-header">
      <div><div className="wb-admin-eyebrow">WIBYTE</div><h1>Admin dashboard</h1></div>
      <div className="wb-admin-header-actions">
        <span>{email}</span><a href="/">Open Python Lab ↗</a>
        <button onClick={() => void onSignOut()}>Sign out</button>
      </div>
    </header>
    <div className="wb-admin-layout">
      <nav aria-label="Dashboard sections">
        {sections.map(item => <button key={item} aria-current={section === item ? "page" : undefined}
          className={section === item ? "wb-admin-selected" : ""}
          onClick={() => { setSection(item); setPage(1); setError(""); setUpdated(""); }}>
          {item}
        </button>)}
      </nav>
      <section className="wb-admin-content">
        <div className="wb-admin-title-row">
          <div><h2>{section}</h2><small>
            {loading ? "Refreshing..." : updated ? `Updated ${updated}` : "Loading..."}
          </small></div>
          <button disabled={loading || busy} onClick={() => setReload(value => value + 1)}>Refresh</button>
        </div>
        {error && <div className="wb-admin-error" role="alert">{error}</div>}

        {section === "Overview" && overview && <>
          <div className="wb-admin-stats">
            {[
              ["Active labs", overview.active_labs],
              ["Approved accounts", overview.approved],
              ["Pending approval", overview.pending],
              ["Labs needing review", overview.recovery_labs],
              ["Total accounts", overview.students],
              ["Suspended accounts", overview.suspended],
            ].map(([title, value]) => <div className="wb-admin-stat" key={title}>
              <span>{title}</span><strong>{value}</strong>
            </div>)}
          </div>
          {overview.recovery_labs > 0 && <div className="wb-admin-warning">
            Some labs were preserved after an automatic save failure. Review Active labs.
          </div>}
          {metrics && <div className="wb-admin-card">
            <h3>VPS resources</h3>
            <div className="wb-admin-meters">
              <Meter title="CPU" value={metrics.cpu_percent}
                detail={`${metrics.cpu_cores} cores · Load ${metrics.load_average.map(n => n.toFixed(2)).join(" / ")}`} />
              <Meter title="Memory" value={100 * metrics.memory_used / metrics.memory_total}
                detail={`${bytes(metrics.memory_used)} / ${bytes(metrics.memory_total)}`} />
              <Meter title="Disk" value={100 * metrics.disk_used / metrics.disk_total}
                detail={`${bytes(metrics.disk_used)} / ${bytes(metrics.disk_total)}`} />
            </div>
          </div>}
          <div className="wb-admin-card wb-admin-note">
            Use Platform health to check backend, Docker, Supabase, GitHub and GUI availability.
          </div>
        </>}

        {section === "Users" && <>
          <div className="wb-admin-title-row">
            <p className="wb-admin-note">Manage accounts or promote an approved student to admin.</p>
            <button disabled={busy} onClick={() => void grantAdmin()}>Add admin by email</button>
          </div>
          <form className="wb-admin-search" onSubmit={event => {
            event.preventDefault(); setQuery(search.trim()); setPage(1); setReload(value => value + 1);
          }}>
            <input aria-label="Search student email" placeholder="Search by email"
              value={search} onChange={event => setSearch(event.target.value)} />
            <select aria-label="Approval filter" value={filter}
              onChange={event => { setFilter(event.target.value); setPage(1); }}>
              <option value="all">All approvals</option><option value="approved">Approved</option>
              <option value="pending">Pending</option><option value="rejected">Rejected</option>
            </select>
            <button type="submit">Search</button>
          </form>
          <div className="wb-admin-table-wrap"><table>
            <thead><tr><th>Account</th><th>Access</th><th>GitHub</th><th>Labs</th><th>Actions</th></tr></thead>
            <tbody>{students.map(student => <tr key={student.id}>
              <td><strong>{student.email}</strong><small>{student.role}</small></td>
              <td><Badge value={student.suspended ? "suspended" : student.approval_status} /></td>
              <td>{student.github_username ? `@${student.github_username}` : "Not connected"}</td>
              <td>{student.active_labs}</td>
              <td>{student.id !== adminId && ["student", "admin"].includes(student.role) ? <div className="wb-admin-row-actions">
                {student.approval_status !== "approved" &&
                  <button disabled={busy} onClick={() => void changeStudent(student, "approve")}>
                    {student.approval_status === "rejected" ? "Accept" : "Approve"}
                  </button>}
                {student.approval_status !== "rejected" &&
                  <button disabled={busy} onClick={() => void changeStudent(student, "reject")}>Reject</button>}
                <button disabled={busy} onClick={() => void changeStudent(student, student.suspended ? "restore" : "suspend")}>
                  {student.suspended ? "Restore" : "Suspend"}
                </button>
                {student.role === "student" && student.approval_status === "approved" && !student.suspended && (
                  <button disabled={busy} onClick={() => void grantAdmin(student)}>Make admin</button>
                )}
                {student.role === "admin" && (
                  <button disabled={busy} onClick={() => void manageAccount(student, "removeAdmin")}>
                    Remove admin
                  </button>
                )}
                {student.approval_status === "rejected" && (
                  <button disabled={busy}
                    style={{ color: "#fda4af", borderColor: "#73384a" }}
                    onClick={() => void manageAccount(student, "delete")}>
                    Delete account
                  </button>
                )}
              </div> : <small>{student.id === adminId ? "Your account" : "No actions available"}</small>}</td>
            </tr>)}</tbody>
          </table>{!loading && !students.length && <p className="wb-admin-empty">No matching accounts.</p>}</div>
          <p className="wb-admin-note">Approval and suspension are separate. Restoring a suspension does not approve a pending or rejected account.</p>
        </>}

        {section === "Active labs" && <div className="wb-admin-table-wrap"><table>
          <thead><tr><th>Student / lab</th><th>Status</th><th>Repository</th><th>Activity</th><th>Resources</th><th>Actions</th></tr></thead>
          <tbody>{labs.map(lab => <tr key={lab.id}>
            <td><strong>{lab.email || "Unknown student"}</strong><small title={lab.id}>{lab.id.slice(0, 8)}</small></td>
            <td><Badge value={lab.status} />
              {lab.timeout_outcome === "save_failed" && <p className="wb-admin-inline-warning" title={lab.timeout_message ?? ""}>Automatic save needs review</p>}
            </td>
            <td>{lab.repository || "Not connected"}</td>
            <td><small>Started: {date(lab.created_at)}</small><small>Last input: {date(lab.last_activity_at)}</small></td>
            <td>{usage[lab.id] && <small>
              CPU {usage[lab.id].cpu_percent.toFixed(1)}% · {bytes(usage[lab.id].memory_used)} /
              {" "}{bytes(usage[lab.id].memory_limit)} · {usage[lab.id].processes} processes
            </small>}<button onClick={() => void inspectUsage(lab.id)}>Check usage</button></td>
            <td><div className="wb-admin-row-actions">
              <button disabled={busy || lab.status !== "running"}
                onClick={() => void terminateLab(lab, "save")}>
                Save &amp; terminate
              </button>
              <button disabled={busy || lab.status !== "running"}
                style={{ color: "#fda4af", borderColor: "#73384a" }}
                onClick={() => void terminateLab(lab, "discard")}>
                Terminate without saving
              </button>
            </div></td>
          </tr>)}</tbody>
        </table>{!loading && !labs.length && <p className="wb-admin-empty">No active labs.</p>}</div>}

        {section === "Platform health" && <div className="wb-admin-health-grid">
          {services.map(service => <div className="wb-admin-card" key={service.name}>
            <div className="wb-admin-title-row"><h3>{service.name}</h3><Badge value={service.status} /></div>
            <p>{service.detail}</p>
            {service.latency_ms !== null && <small>{service.latency_ms} ms</small>}
          </div>)}
        </div>}

        {section === "Activity history" && <>
          <p className="wb-admin-note">Events are recorded from dashboard installation onward. Times use your browser's time zone.</p>
          <div className="wb-admin-table-wrap"><table>
            <thead><tr><th>Time</th><th>Account</th><th>Action</th><th>Target</th><th>Result</th></tr></thead>
            <tbody>{events.map(event => <tr key={event.id}>
              <td>{date(event.occurred_at)}</td><td>{event.actor_email || "System"}</td>
              <td>{label(event.action)}</td><td title={event.target_id ?? ""}>{event.target_id?.slice(0, 8) || "—"}</td>
              <td><Badge value={event.outcome} /></td>
            </tr>)}</tbody>
          </table>{!loading && !events.length && <p className="wb-admin-empty">No recorded activity yet.</p>}</div>
        </>}

        {paginated && <div className="wb-admin-pagination">
          <button disabled={page === 1 || loading} onClick={() => setPage(value => value - 1)}>Previous</button>
          <span>Page {page}{total !== null ? ` · ${total} results` : ""}</span>
          <button disabled={loading || (total !== null && page * 50 >= total)}
            onClick={() => setPage(value => value + 1)}>Next</button>
        </div>}
      </section>
    </div>
  </main>;
}
