import { useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import {
  ArrowRight,
  ArrowLeft,
  FileText,
  ShieldCheck,
  Search,
  Bot,
  BookOpen,
} from "lucide-react";
import { useWorkspace } from "../app/Workspace";
import { AppShell } from "../components/layout/AppShell";
import { AgentPulse } from "../components/agents/AgentPulse";
import {
  Empty,
  Badge,
  StateBadge,
  formatDate,
  SectionHeader,
} from "../components/shared/UI";
import { SourceNotice } from "./Dashboard";
import {BriefContext, briefValue} from '../components/dashboard/BriefContext';
export function DailyBriefs() {
  const w = useWorkspace(),
    { briefId } = useParams(),
    b = w.briefs.find((b) => b.id === briefId);
  const [params, setParams] = useSearchParams();
  return (
    <AppShell rail={<AgentPulse />}>
      <SourceNotice />
      <Link className="text-link" to="/runs">Generate a brief or manage the daily schedule →</Link>
      {briefId ? (
        b ? (
          <>
            <Link className="back-link" to="/briefs">
              <ArrowLeft size={14} /> All daily briefs
            </Link>
            <div className="page-title">
              <span className="eyebrow">{b.scope === 'long_only_etf_proxy' ? 'ETF PROXY' : 'MARKET / BOOK'}</span>
              <h1>{b.scope === 'long_only_etf_proxy' ? 'Daily ETF market brief.' : 'Daily market / book brief.'}</h1>
              <p>
                As of {b.requested_as_of} · {b.source_kind}
              </p>
              <StateBadge status={b.status} />
            </div>
            <BriefContext brief={b} />
            <div className="brief-metrics">
              {b.status === "unavailable" ? (
                <Empty title="Assessment withheld">
                  The underlying inputs or delivery checks were unavailable.
                </Empty>
              ) : (
                Object.entries(b.metrics).map(([key, m]) => (
                  <div key={key}>
                    <span>{key.replaceAll("_", " ")}</span>
                    <strong>{briefValue(b, m.value)}</strong>
                    <small>
                      {b.scope === 'long_only_etf_proxy' ? 'Adjusted-price observation · percent' : typeof m.value === "number"
                        ? "Monitoring score · not a probability"
                        : m.source_field}
                    </small>
                  </div>
                ))
              )}
            </div>
            <section className="research-document">
              <h2>What changed</h2>
              <p>{b.comparison_note}</p>
              {Object.entries(b.changes).map(([key, c]) => (
                <p key={key}>
                  {key}: {briefValue(b,c.previous)} → {briefValue(b,c.current)}
                </p>
              ))}
              <h2>Limitations & next checks</h2>
              <ul>
                {b.limitations.map((l) => (
                  <li key={l}>{l}</li>
                ))}
              </ul>
              <h2>Source timing</h2>
              <p>
                Requested assessment: {b.requested_as_of}
                <br />
                Data cutoff: {b.data_cutoff ?? "Unavailable"}
                <br />
                Generated: {formatDate(b.generated_at)}
              </p>
              <details className="trace-card">
                <summary>Delivery and input audit</summary>
                <pre>
                  {JSON.stringify(
                    {
                      delivery: b.delivery_contract,
                      readiness: b.readiness,
                      fingerprint: b.engine_fingerprint,
                    },
                    null,
                    2,
                  )}
                </pre>
              </details>
            </section>
          </>
        ) : (
          <Empty title={w.loading ? "Loading brief…" : "Brief not found"}>
            <Link to="/briefs">Return to briefs</Link>
          </Empty>
        )
      ) : (
        <>
          <div className="page-title">
            <span className="eyebrow">MARKET CONTEXT</span>
            <h1>The daily view.</h1>
            <p>
              As-of assessments with their evidence, timing and limitations
              intact.
            </p>
          </div>
          <label className="inline-search">
            <Search size={16} />
            <input
              aria-label="Filter briefs by date"
              placeholder="Filter by as-of date…"
              value={params.get("date") ?? ""}
              onChange={(e) =>
                setParams(e.target.value ? { date: e.target.value } : {})
              }
            />
          </label>
          <div className="library-list">
            {w.briefs
              .filter((b) =>
                b.requested_as_of.includes(params.get("date") ?? ""),
              )
              .map((b) => (
                <Link
                  className="library-item"
                  key={b.id}
                  to={"/briefs/" + encodeURIComponent(b.id)}
                >
                  <FileText size={22} />
                  <div>
                    <h3>Momentum daily brief — {b.requested_as_of}</h3>
                    <p>{b.source_kind} · {b.scope === 'long_only_etf_proxy' ? 'ETF observations; original model unavailable' : 'Market/book assessment'}</p>
                  </div>
                  <StateBadge status={b.status} />
                  <ArrowRight size={16} />
                </Link>
              ))}
          </div>
          {!w.briefs.length && <Empty title="No daily briefs available" />}
        </>
      )}
    </AppShell>
  );
}
export function Gaps() {
  const w = useWorkspace(),
    [params, setParams] = useSearchParams();
  const list = w.gaps.filter(
    (g) =>
      (!params.get("status") || g.status === params.get("status")) &&
      (!params.get("capability") || g.capability === params.get("capability")),
  );
  return (
    <AppShell rail={<AgentPulse />}>
      <SourceNotice />
      <div className="page-title">
        <span className="eyebrow">RESEARCH CONTINUITY</span>
        <h1>The questions still open.</h1>
        <p>
          Follow each evidence gap from its source to its recorded resolution.
        </p>
      </div>
      <div className="evidence-toolbar">
        <select
          aria-label="Gap status"
          value={params.get("status") ?? ""}
          onChange={(e) => {
            const n = new URLSearchParams(params);
            n.set("status", e.target.value);
            setParams(n);
          }}
        >
          <option value="">All statuses</option>
          {["OPEN", "CONSUMED", "CLOSED"].map((s) => (
            <option key={s}>{s}</option>
          ))}
        </select>
        <select
          aria-label="Gap capability"
          value={params.get("capability") ?? ""}
          onChange={(e) => {
            const n = new URLSearchParams(params);
            n.set("capability", e.target.value);
            setParams(n);
          }}
        >
          <option value="">All capabilities</option>
          {[
            "crowding",
            "unwind_crash",
            "engine_freshness",
            "source_quality",
          ].map((s) => (
            <option key={s} value={s}>
              {s.replaceAll("_", " ")}
            </option>
          ))}
        </select>
      </div>
      {list.map((g) => (
        <details className="gap-card" key={g.id}>
          <summary>
            <StateBadge status={g.status} />
            <h3>{g.claim}</h3>
            <Badge>{g.capability.replaceAll("_", " ")}</Badge>
          </summary>
          <p>{g.notes}</p>
          <p className="muted">Occurrence created {formatDate(g.created_at)}</p>
          {w.sessions.some((s) => s.id === g.source_session_id) ? (
            <Link
              className="text-link"
              to={
                "/sessions/" +
                encodeURIComponent(g.source_session_id!) +
                "?tab=evidence&evidence=" +
                encodeURIComponent(g.evidence_id)
              }
            >
              View source evidence <ArrowRight size={13} />
            </Link>
          ) : (
            <p>Source: {g.source_session_id ?? "Not recorded"}</p>
          )}
          {g.consumed_session_id && (
            <p>
              Consumed by:{" "}
              {w.sessions.some((s) => s.id === g.consumed_session_id) ? (
                <Link
                  to={
                    "/sessions/" +
                    encodeURIComponent(g.consumed_session_id) +
                    "?task=" +
                    encodeURIComponent(g.consumed_task_id ?? "")
                  }
                >
                  {g.consumed_session_id}
                </Link>
              ) : (
                g.consumed_session_id
              )}
            </p>
          )}
          {g.status === "CLOSED" && (
            <p className="muted">
              Closed in the ledger. A detailed closure reason was not recorded.
            </p>
          )}
        </details>
      ))}
      {!list.length && (
        <Empty title="No matching gaps">
          Change the filters to explore other occurrences.
        </Empty>
      )}
    </AppShell>
  );
}
export function Agents() {
  const w = useWorkspace(),
    [selected, setSelected] = useState("");
  const profile = w.profiles.find((p) => p.name === selected);
  const rail = profile ? (
    <section className="rail-card inspector-card">
      <span className="eyebrow">AGENT PROFILE</span>
      <h2>{profile.displayName}</h2>
      <p>{profile.description}</p>
      <h4 className="mt-6">Authorized tools</h4>
      <div className="tool-list">
        {profile.tools.map((t) => (
          <Badge key={t}>{t}</Badge>
        ))}
      </div>
      <p className="rail-caption">
        Tool registration does not grant authorization. This list reflects the
        explicit profile allowlist.
      </p>
      <h4>Recorded contributions</h4>
      {w.sessions
        .filter((s) => s.tasks.some((t) => t.profile === profile.name))
        .map((s) => (
          <Link className="activity-row" key={s.id} to={"/sessions/" + s.id}>
            {s.scope} research <ArrowRight size={13} />
          </Link>
        ))}
    </section>
  ) : (
    <AgentPulse />
  );
  return (
    <AppShell rail={rail}>
      <SourceNotice />
      <div className="page-title">
        <span className="eyebrow">YOUR RESEARCH TEAM</span>
        <h1>Different lenses. Better questions.</h1>
        <p>Purpose-built analysts, explicit tools, independent verification.</p>
      </div>
      <div className="agent-grid">
        {w.profiles.map((p) => (
          <button
            className={"profile-card " + (p.name === selected ? "chosen" : "")}
            key={p.name}
            onClick={() => setSelected(p.name)}
          >
            {p.kind === "verification" ? (
              <ShieldCheck size={26} />
            ) : (
              <Bot size={26} />
            )}
            <Badge>
              {p.kind === "verification"
                ? "Independent verification"
                : "Research analyst"}
            </Badge>
            <h2>{p.displayName}</h2>
            <p>{p.description}</p>
            <div className="profile-footer">
              <span>
                {
                  w.sessions
                    .flatMap((s) => s.tasks)
                    .filter((t) => t.profile === p.name).length
                }{" "}
                recorded tasks
              </span>
              <ArrowRight size={15} />
            </div>
          </button>
        ))}
      </div>
      {!w.loading && !w.profiles.length && (
        <Empty title="No agent profiles available">
          The explicit profile catalog could not be loaded.
        </Empty>
      )}
    </AppShell>
  );
}
export function Library() {
  const w = useWorkspace(),
    [params, setParams] = useSearchParams(),
    q = params.get("q") ?? "",
    type = params.get("type") ?? "all";
  const items = [
    ...w.sessions.map((s) => ({
      id: s.id,
      title: s.title,
      subtitle: s.question,
      type: "report",
      url: "/sessions/" + encodeURIComponent(s.id),
    })),
    ...w.sessions.flatMap((s) =>
      s.evidence.map((e) => ({
        id: s.id + e.taskId + e.id,
        title: e.claim,
        subtitle: e.source_name ?? "Source not recorded",
        type: "evidence",
        url:
          "/sessions/" +
          encodeURIComponent(s.id) +
          "?tab=evidence&evidence=" +
          encodeURIComponent(e.id) +
          "&task=" +
          encodeURIComponent(e.taskId),
      })),
    ),
    ...w.briefs.map((b) => ({
      id: b.id,
      title: "Daily brief — " + b.requested_as_of,
      subtitle: b.source_kind,
      type: "brief",
      url: "/briefs/" + encodeURIComponent(b.id),
    })),
  ].filter(
    (i) =>
      (type === "all" || i.type === type) &&
      (i.title + " " + i.subtitle).toLowerCase().includes(q.toLowerCase()),
  );
  return (
    <AppShell rail={<AgentPulse />}>
      <SourceNotice />
      <div className="page-title">
        <span className="eyebrow">YOUR RESEARCH MEMORY</span>
        <h1>Good research compounds.</h1>
        <p>Reports, evidence and daily briefs, all within reach.</p>
      </div>
      <div className="list-toolbar">
        <label className="inline-search">
          <Search size={16} />
          <input
            aria-label="Search library"
            value={q}
            placeholder="Search the library…"
            onChange={(e) => {
              const n = new URLSearchParams(params);
              n.set("q", e.target.value);
              setParams(n);
            }}
          />
        </label>
        <select
          aria-label="Library type"
          value={type}
          onChange={(e) => {
            const n = new URLSearchParams(params);
            n.set("type", e.target.value);
            setParams(n);
          }}
        >
          {["all", "report", "evidence", "brief"].map((t) => (
            <option key={t} value={t}>
              {t === "all" ? "All types" : t}
            </option>
          ))}
        </select>
      </div>
      <div className="library-list">
        {items.map((i) => (
          <Link key={i.id} className="library-item" to={i.url}>
            <BookOpen size={20} />
            <div>
              <h3>{i.title}</h3>
              <p>{i.subtitle}</p>
            </div>
            <Badge>{i.type}</Badge>
            <ArrowRight size={16} />
          </Link>
        ))}
      </div>
      {!items.length && <Empty title="No matching research" />}
    </AppShell>
  );
}
