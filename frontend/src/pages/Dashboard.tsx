import { Link, useSearchParams } from "react-router-dom";
import { useState } from "react";
import { ArrowRight, Search, RefreshCw } from "lucide-react";
import { useWorkspace } from "../app/Workspace";
import { AppShell } from "../components/layout/AppShell";
import { AgentPulse } from "../components/agents/AgentPulse";
import { ResearchCard } from "../components/dashboard/ResearchCard";
import { LatestBrief } from "../components/dashboard/LatestBrief";
import {
  SectionHeader,
  StateBadge,
  ScopeMark,
  formatDate,
  Empty,
  Badge,
} from "../components/shared/UI";
import type { Session } from "../types";
export function SessionTable({ sessions }: { sessions: Session[] }) {
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Research</th>
            <th>Tasks</th>
            <th>Evidence</th>
            <th>Verification</th>
            <th>Last update</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {sessions.map((s) => (
            <tr key={s.id}>
              <td>
                <Link
                  to={"/sessions/" + encodeURIComponent(s.id)}
                  className="table-research"
                >
                  <ScopeMark small scope={s.scope} />
                  <span>
                    <strong>{s.scope}</strong>
                    <small>{s.question}</small>
                  </span>
                </Link>
              </td>
              <td>
                {s.tasks.filter((t) => t.status === "COMPLETED").length}/
                {s.tasks.length}
              </td>
              <td>{s.evidence.length}</td>
              <td>
                <StateBadge
                  status={s.verification?.overall_status ?? "not_reviewed"}
                />
              </td>
              <td>
                {formatDate(s.source === "demo" ? s.snapshotAt : s.updatedAt)}
              </td>
              <td>
                <Link
                  aria-label={"Open " + s.scope + " session"}
                  to={"/sessions/" + encodeURIComponent(s.id)}
                >
                  <ArrowRight size={14} />
                </Link>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {!sessions.length && (
        <Empty title="No matching sessions">
          Try another filter or start a research demo.
        </Empty>
      )}
    </div>
  );
}
export function SourceNotice() {
  const w = useWorkspace();
  return (
    <>
      {w.source === "artifact" && (
        <div
          className={"notice " + (w.sync?.state === "stale" ? "error" : "")}
          role="status"
        >
          {w.sync?.message ?? "Checking automatic sync…"} · Snapshot:{" "}
          {formatDate(w.snapshotAt)}
          <small>
            Read-only · saved task states do not prove an agent is running.
          </small>
        </div>
      )}
      {w.diagnostics.length > 0 && (
        <details className="notice">
          <summary>Snapshot notices · {w.diagnostics.length}</summary>
          {w.diagnostics.map((d, i) => (
            <p key={i}>
              <strong>{d.code}</strong> · {d.file}: {d.message}
            </p>
          ))}
        </details>
      )}
      {w.error && (
        <div role="alert" className="notice error">
          {w.error}
          <button onClick={w.refresh}>
            <RefreshCw size={14} />
            Retry
          </button>
        </div>
      )}
      {w.source === "artifact" &&
        !w.loading &&
        !w.sessions.length &&
        !w.error && (
          <div className="notice">
            No local research sessions found. New saved artifacts appear
            automatically while local sync is active, or{" "}
            <button onClick={() => w.setSource("demo")}>
              explore the demo workspace
            </button>
            .
          </div>
        )}
      {w.storageNotice && <div className="notice">{w.storageNotice}</div>}
    </>
  );
}
export function Dashboard() {
  const w = useWorkspace(),
    [filter, setFilter] = useState("All research");
  const active = w.sessions
    .flatMap((s) => s.tasks)
    .filter((t) => t.status === "ACTIVE").length;
  const unchecked = w.sessions
    .flatMap((s) => s.verification?.verdicts ?? [])
    .filter((v) => v.status === "unchecked").length;
  const visible = w.sessions.filter(
    (s) =>
      filter !== "Needs review" || s.verification?.overall_status !== "pass",
  );
  return (
    <AppShell rail={<AgentPulse />}>
      <SourceNotice />
      <div className="hero">
        <div>
          <h1>Good evening, Aaron.</h1>
          <p>Here’s what changed — and where your research goes next.</p>
        </div>
        <div className="hero-date">
          <span>
            {w.source === "demo"
              ? "Your research, in focus"
              : formatDate(w.snapshotAt)}
          </span>
          <small>
            {w.source === "demo"
              ? "Demo workspace · Historical examples"
              : "Read-only research snapshot"}
          </small>
        </div>
      </div>
      <section className="metrics-strip">
        <div>
          <strong>{w.sessions.length}</strong>
          <span>Research sessions</span>
          <small>In this workspace</small>
        </div>
        <div>
          <strong>{active}</strong>
          <span>Recorded active</span>
          <small>From task snapshots</small>
        </div>
        <div>
          <strong className="green">{unchecked}</strong>
          <span>Evidence to review</span>
          <small>Awaiting corroboration</small>
        </div>
        <blockquote>
          “Information is leverage
          <br />
          when turned into action.”<cite>— MOMENTUM</cite>
        </blockquote>
      </section>
      <LatestBrief briefs={w.briefs} />
      <section className="updates-section">
        <SectionHeader
          title="Top updates"
          subtitle="The latest findings across your research."
          to="/sessions"
          label="View all research"
        />
        <div className="research-grid">
          {w.sessions.slice(0, 3).map((s) => (
            <ResearchCard key={s.id} session={s} />
          ))}
        </div>
        {w.loading && <Empty title="Loading your research…" />}
      </section>
      <section className="sessions-section">
        <div className="section-head">
          <h2>Research workspace</h2>
          <div className="table-filters">
            {["All research", "Needs review"].map((f) => (
              <button
                key={f}
                className={f === filter ? "selected" : ""}
                onClick={() => setFilter(f)}
              >
                {f}
              </button>
            ))}
          </div>
          <Link className="text-link" to="/sessions">
            View all <ArrowRight size={14} />
          </Link>
        </div>
        <SessionTable sessions={visible} />
      </section>
      <div className="page-footnote">
        <Badge>{w.source === "demo" ? "DEMO" : "SNAPSHOT"}</Badge>
        {w.source === "demo"
          ? "Illustrative research. No live model calls or market data."
          : "Task states reflect saved files, not process liveness."}
        <Link to="/briefs">
          Latest daily brief <ArrowRight size={12} />
        </Link>
      </div>
    </AppShell>
  );
}
export function Sessions() {
  const w = useWorkspace(),
    [params, setParams] = useSearchParams();
  const q = params.get("q") ?? "";
  const sessions = w.sessions.filter((s) =>
    (s.question + " " + s.scope + " " + s.title)
      .toLowerCase()
      .includes(q.toLowerCase()),
  );
  return (
    <AppShell rail={<AgentPulse />}>
      <SourceNotice />
      <div className="page-title">
        <span className="eyebrow">YOUR RESEARCH</span>
        <h1>Every question, a clearer view.</h1>
        <p>Explore the work, the evidence, and the questions still open.</p>
      </div>
      <div className="list-toolbar">
        <label className="inline-search">
          <Search size={16} />
          <input
            aria-label="Filter sessions"
            placeholder="Filter research…"
            value={q}
            onChange={(e) =>
              setParams(e.target.value ? { q: e.target.value } : {})
            }
          />
        </label>
        <Link className="button dark" to="/research">
          New research <ArrowRight size={14} />
        </Link>
      </div>
      <SessionTable sessions={sessions} />
    </AppShell>
  );
}
