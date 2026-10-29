import { useEffect, useState } from "react";
import "./UsageStats.css";

type Metric = {
  cpu_percent: number | null; cpu_peak: number | null;
  memory_used: number; memory_total?: number;
  memory_peak?: number; memory_limit?: number;
  disk_used?: number; disk_total?: number; samples: number;
};
type Point = {
  at: number; until: number; lab_hours: number;
  concurrent_labs: number; concurrent_users: number;
  host: Metric | null; labs: Metric | null;
};
type Session = {
  lab_id: string; student_id: string; email: string | null; name: string | null;
  repository: string | null; started_at: number; ended_at: number | null;
  recorded_at: number; last_activity_at: number | null;
  close_reason: string | null; gui_started: number | null;
  gui_first_at: number | null; partial_history: number;
  range_seconds: number; total_seconds: number;
};
type User = {
  student_id: string; email: string | null; name: string | null;
  seconds: number; sessions: number; gui_sessions: number; gui_unknown: number;
};
type Report = {
  start: number; end: number; tracking_started_at: number; last_sample_at: number | null;
  summary: {
    seconds: number; sessions: number; users: number; average_seconds: number;
    peak_users: number; peak_labs: number; gui_sessions: number; gui_unknown: number;
  };
  series: Point[]; users: User[]; sessions: Session[]; total: number; page: number;
};
type Request = <T>(path: string, init?: RequestInit) => Promise<T>;
type Filters = {
  period: string; q: string; gui: string; start: string; end: string;
};

function date(value: number | null) {
  return value === null ? "—" : new Date(value * 1000).toLocaleString();
}
function duration(seconds: number) {
  const mins = Math.floor(Math.max(0, seconds) / 60);
  return mins < 60 ? `${mins}m` : `${Math.floor(mins / 60)}h ${mins % 60}m`;
}
function guiLabel(value: number | null) {
  return value === null ? "Unknown" : value ? "Started" : "Not started";
}
function reason(value: string | null) {
  return value ? value.replace(/[:_]/g, " ") : "Still open";
}
function localDate(value: number) {
  const d = new Date(value);
  return new Date(value - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
}

function Chart({ title, points, value, unit, color = "#a78bfa", bars = false }: {
  title: string; points: Point[];
  value: (point: Point) => number | null | undefined;
  unit: string; color?: string; bars?: boolean;
}) {
  const values = points.map(value);
  const known = values.filter((v): v is number => v !== null && v !== undefined && Number.isFinite(v));
  const maximum = Math.max(1, ...known);
  const width = 760, height = 210, left = 52, top = 15, plotWidth = 690, plotHeight = 150;
  const x = (index: number) => left + (index + .5) / Math.max(1, points.length) * plotWidth;
  const y = (v: number) => top + plotHeight * (1 - v / maximum);
  const paths: string[] = [];
  let path = "";
  values.forEach((v, index) => {
    if (v === null || v === undefined || !Number.isFinite(v)) {
      if (path) paths.push(path);
      path = "";
    } else {
      path += `${path ? " L" : "M"}${x(index)},${y(v)}`;
    }
  });
  if (path) paths.push(path);
  return <div className="wb-admin-card wb-usage-chart">
    <h3>{title}</h3>
    {!known.length ? <p className="wb-admin-empty">No measurements in this range yet.</p> :
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${title}, ${unit}. Timestamps use your browser time zone.`}>
        {[0, .5, 1].map(fraction => <g key={fraction}>
          <line x1={left} x2={left + plotWidth} y1={y(maximum * fraction)} y2={y(maximum * fraction)}
            stroke="#293244" />
          <text x={left - 8} y={y(maximum * fraction) + 4} textAnchor="end">
            {(maximum * fraction).toFixed(maximum < 10 ? 1 : 0)}
          </text>
        </g>)}
        {!bars && paths.map((d, i) => <path key={i} d={d} fill="none" stroke={color} strokeWidth="2" />)}
        {values.map((v, index) => v === null || v === undefined ? null :
          bars ? <rect key={index} x={x(index) - plotWidth / points.length * .4}
            y={y(v)} width={Math.max(1, plotWidth / points.length * .8)}
            height={Math.max(0, top + plotHeight - y(v))} fill={color}>
            <title>{date(points[index].at)} – {date(points[index].until)}: {v.toFixed(2)} {unit}</title>
          </rect> :
          <circle key={index} cx={x(index)} cy={y(v)} r="2.5" fill={color}>
            <title>{date(points[index].at)} – {date(points[index].until)}: {v.toFixed(2)} {unit}</title>
          </circle>)}
        {[0, .5, 1].map((fraction, i) => {
          const index = Math.round((points.length - 1) * fraction);
          return <text key={i} x={left + plotWidth * fraction} y={195}
            textAnchor={i === 0 ? "start" : i === 2 ? "end" : "middle"}>
            {new Date(points[index].at * 1000).toLocaleString(undefined, {
              month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
            })}
          </text>;
        })}
      </svg>}
    <small>{unit}. Hover over a point for its time and value. Missing measurements remain gaps.</small>
  </div>;
}

export default function UsageStats({ request, reload }: { request: Request; reload: number }) {
  const [draft, setDraft] = useState<Filters>({
    period: "24h", q: "", gui: "all",
    start: localDate(Date.now() - 86400000), end: localDate(Date.now()),
  });
  const [filters, setFilters] = useState(draft);
  const [page, setPage] = useState(1);
  const [labId, setLabId] = useState("");
  const [data, setData] = useState<Report | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [refresh, setRefresh] = useState(0);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError("");
    const params = new URLSearchParams({
      period: filters.period, q: filters.q, gui: filters.gui, page: String(page),
    });
    if (filters.period === "custom") {
      const start = new Date(filters.start).getTime() / 1000;
      const end = new Date(filters.end).getTime() / 1000;
      if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) {
        setError("Choose a valid start and end time.");
        setLoading(false);
        setData(null);
        return;
      }
      params.set("start", String(start)); params.set("end", String(end));
    }
    if (labId) params.set("lab_id", labId);
    void request<Report>(`/usage?${params}`).then(result => {
      if (active) setData(result);
    }).catch(err => {
      if (active) {
        setError(err instanceof Error ? err.message : "Usage stats unavailable.");
        setData(null);
      }
    }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [request, reload, refresh, filters, page, labId]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      if (!document.hidden) setRefresh(value => value + 1);
    }, 60000);
    return () => window.clearInterval(timer);
  }, []);

  function exportUsers() {
    if (!data) return;
    const cell = (value: unknown) => {
      let text = String(value ?? "");
      if (/^[=+\-@\t\r]/.test(text)) text = "'" + text;
      return `"${text.replace(/"/g, '""')}"`;
    };
    const rows = [
      ["User ID", "Email", "Name", "Hours in range", "Sessions", "GUI started", "GUI unknown"],
      ...data.users.map(user => [
        user.student_id, user.email, user.name,
        (user.seconds / 3600).toFixed(3), user.sessions, user.gui_sessions, user.gui_unknown,
      ]),
    ];
    const blob = new Blob(["\uFEFF" + rows.map(row => row.map(cell).join(",")).join("\r\n")],
      { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url; link.download = "wibyte-usage-by-user.csv"; link.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  const summary = data?.summary;
  const maxUser = Math.max(1, ...(data?.users.map(user => user.seconds) ?? []));
  const gb = (bytes: number | null | undefined) => bytes === null || bytes === undefined ? null : bytes / 1024 ** 3;

  return <div className="wb-usage">
    <form className="wb-admin-search wb-usage-filters" onSubmit={event => {
      event.preventDefault(); setFilters({ ...draft }); setPage(1); setLabId("");
    }}>
      <label>Time range<select value={draft.period}
        onChange={event => setDraft({ ...draft, period: event.target.value })}>
        <option value="24h">Past 24 hours</option><option value="week">Past week</option>
        <option value="month">Past 30 days</option><option value="all">All time</option>
        <option value="custom">Custom dates</option>
      </select></label>
      <label>User<input placeholder="Email, name or user ID" value={draft.q}
        onChange={event => setDraft({ ...draft, q: event.target.value })} /></label>
      <label>GUI<select value={draft.gui}
        onChange={event => setDraft({ ...draft, gui: event.target.value })}>
        <option value="all">All sessions</option><option value="yes">GUI started</option>
        <option value="no">GUI not started</option><option value="unknown">GUI unknown</option>
      </select></label>
      {draft.period === "custom" && <>
        <label>From<input type="datetime-local" required value={draft.start}
          onChange={event => setDraft({ ...draft, start: event.target.value })} /></label>
        <label>To<input type="datetime-local" required value={draft.end}
          onChange={event => setDraft({ ...draft, end: event.target.value })} /></label>
      </>}
      <button type="submit" disabled={loading}>Apply filters</button>
    </form>

    {labId && <div className="wb-admin-warning">
      Showing lab {labId}.{" "}
      <button onClick={() => { setLabId(""); setPage(1); }}>Show all matching labs</button>
    </div>}
    {error && <div className="wb-admin-error" role="alert">{error}</div>}
    {loading && <p role="status">Updating usage stats…</p>}

    {data && summary && <>
      <p className="wb-admin-note">
        {date(data.start)} – {date(data.end)}. Times use your browser time zone.
        Monitoring began {date(data.tracking_started_at)}.
        Lab hours include idle time until closure; they do not measure active coding.
        Existing sessions can have partial history. “GUI started” does not measure interaction.
      </p>
      {(!data.last_sample_at || Date.now() / 1000 - data.last_sample_at > 180) &&
        <div className="wb-admin-warning">Resource monitoring has no recent sample. Charts may contain gaps.</div>}

      <div className="wb-admin-stats">
        {[
          ["Lab hours", (summary.seconds / 3600).toFixed(2)],
          ["Unique users", summary.users], ["Sessions", summary.sessions],
          ["Average time in range", duration(summary.average_seconds)],
          ["Peak concurrent users", summary.peak_users], ["Peak concurrent labs", summary.peak_labs],
          ["GUI started", `${summary.gui_sessions} sessions`],
          ["GUI history unknown", `${summary.gui_unknown} sessions`],
        ].map(([title, value]) => <div className="wb-admin-stat" key={title}>
          <span>{title}</span><strong>{value}</strong>
        </div>)}
      </div>

      <div className="wb-usage-grid">
        <Chart title="Lab hours over time" points={data.series} value={p => p.lab_hours} unit="lab hours per interval" bars />
        <Chart title="Concurrent users" points={data.series} value={p => p.concurrent_users} unit="peak users per interval" color="#38bdf8" />
        <Chart title="Concurrent labs" points={data.series} value={p => p.concurrent_labs} unit="peak labs per interval" color="#34d399" />
        <Chart title="VPS CPU — whole platform" points={data.series} value={p => p.host?.cpu_percent} unit="average CPU %" />
        <Chart title="VPS memory — whole platform" points={data.series} value={p => gb(p.host?.memory_used)} unit="average GB" color="#38bdf8" />
        <Chart title="VPS disk — whole platform" points={data.series} value={p => gb(p.host?.disk_used)} unit="maximum used GB" color="#fbbf24" />
        <Chart title={labId ? "Selected lab CPU" : "CPU per sampled lab — matching sessions"}
          points={data.series} value={p => p.labs?.cpu_percent} unit="average CPU %; 100% = one core" />
        <Chart title={labId ? "Selected lab memory" : "Memory per sampled lab — matching sessions"}
          points={data.series} value={p => gb(p.labs?.memory_used)} unit="average GB" color="#34d399" />
      </div>

      <div className="wb-admin-card">
        <h3>Session timeline</h3>
        <p className="wb-admin-note">
          Showing the current page of sessions. Bars cover time within the selected range.
          Select a session to inspect its own resource charts.
        </p>
        <div className="wb-usage-timeline-axis">
          <small>{date(data.start)}</small><small>{date(data.end)}</small>
        </div>
        {data.sessions.map(session => {
          const start = Math.max(data.start, session.started_at);
          const end = Math.min(data.end, session.ended_at ?? data.end);
          return <button className="wb-usage-session" key={session.lab_id}
            onClick={() => { setLabId(session.lab_id); setPage(1); }}
            title={`${session.email || session.student_id} · ${session.lab_id}\n${date(session.started_at)} – ${session.ended_at === null ? "Still open" : date(session.ended_at)}\n${duration(session.total_seconds)} · GUI ${guiLabel(session.gui_started)}`}>
            <span>{session.email || session.student_id}<small>{session.lab_id.slice(0, 8)} · {duration(session.range_seconds)}</small></span>
            <span className="wb-usage-track"><span className="wb-usage-bar" style={{
              left: `${100 * (start - data.start) / (data.end - data.start)}%`,
              width: `${Math.max(.3, 100 * (end - start) / (data.end - data.start))}%`,
              background: session.gui_started === 1 ? "#38bdf8" : "#a78bfa",
            }} /></span>
          </button>;
        })}
        {!data.sessions.length && <p className="wb-admin-empty">No sessions match these filters.</p>}
      </div>

      <div className="wb-admin-card">
        <div className="wb-admin-title-row">
          <h3>Usage by user</h3><button onClick={exportUsers}>Export user totals CSV</button>
        </div>
        <small>Hours are clipped to the selected date range. Chart shows the top 20 users.</small>
        {data.users.slice(0, 20).map(user => <div className="wb-usage-user" key={user.student_id}>
          <span>{user.email || user.student_id}</span>
          <div className="wb-usage-track"><span className="wb-usage-bar"
            style={{ width: `${100 * user.seconds / maxUser}%` }} /></div>
          <strong>{(user.seconds / 3600).toFixed(2)}h</strong>
        </div>)}
      </div>

      <h3 className="wb-usage-heading">Session details</h3>
      <div className="wb-admin-table-wrap"><table>
        <thead><tr><th>User / lab</th><th>Repository</th><th>Start / end</th>
          <th>Duration</th><th>GUI</th><th>Closure</th></tr></thead>
        <tbody>{data.sessions.map(session => <tr key={session.lab_id}>
          <td><strong>{session.email || session.student_id}</strong><small>{session.lab_id}</small>
            <button onClick={() => { setLabId(session.lab_id); setPage(1); }}>Inspect lab</button></td>
          <td>{session.repository || "Not recorded"}</td>
          <td><small>Start: {date(session.started_at)}</small>
            <small>End: {session.ended_at === null ? "Still open" : date(session.ended_at)}</small>
            <small>Last activity: {date(session.last_activity_at)}</small></td>
          <td>{duration(session.total_seconds)} total<small>{duration(session.range_seconds)} in range</small>
            {session.partial_history === 1 && <small>Partial monitoring history</small>}</td>
          <td>{guiLabel(session.gui_started)}<small>{date(session.gui_first_at)}</small></td>
          <td>{reason(session.close_reason)}</td>
        </tr>)}</tbody>
      </table></div>
      <div className="wb-admin-pagination">
        <button disabled={page === 1 || loading} onClick={() => setPage(p => p - 1)}>Previous</button>
        <span>Page {page} · {data.total} sessions</span>
        <button disabled={loading || page * 50 >= data.total} onClick={() => setPage(p => p + 1)}>Next</button>
      </div>
    </>}
  </div>;
}
