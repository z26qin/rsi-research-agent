import { useParams, useSearchParams, Link } from "react-router-dom";
import {
  ArrowLeft,
  ArrowRight,
  ChevronRight,
  Copy,
  FileText,
  ShieldCheck,
  Check,
  Clock,
} from "lucide-react";
import { useState } from "react";
import { RecordedFlow } from "../components/agents/RecordedFlow";
import { useWorkspace } from "../app/Workspace";
import { AppShell } from "../components/layout/AppShell";
import { AgentInspector } from "../components/agents/AgentInspector";
import {
  EvidenceCard,
  EvidenceInspector,
} from "../components/evidence/EvidenceCard";
import { ThesisDiff } from "../components/research/ThesisDiff";
import {
  Badge,
  StateBadge,
  TaskIcon,
  formatDate,
  Empty,
} from "../components/shared/UI";
import { resolveVerdict } from "../data/normalize";
import { SourceNotice } from "./Dashboard";
import type { Session } from "../types";
function Timeline({ session: s }: { session: Session }) {
  const events = [
    ...s.tasks.flatMap((t) => [
      {
        id: t.id + "-start",
        time: t.started_at,
        title: t.title,
        detail: t.assignment,
      },
      {
        id: t.id + "-end",
        time: t.completed_at,
        title: "Task " + t.status.toLowerCase(),
        detail: t.error ?? t.title,
      },
    ]),
    ...s.traces.map((t) => ({
      id: t.id,
      time: t.timestamp,
      title: "Stored " + t.tool + " observation",
      detail: t.observation,
    })),
  ]
    .filter((e) => e.time)
    .sort((a, b) => String(a.time).localeCompare(String(b.time)));
  return (
    <section className="timeline-section">
      <h2>Research timeline</h2>
      <p className="muted">Recorded events, connected to the work.</p>
      <div className="timeline">
        {events.map((e) => (
          <details key={e.id}>
            <summary>
              <span className="timeline-dot" />
              <time>{formatDate(e.time)}</time>
              <strong>{e.title}</strong>
              <ChevronRight size={14} />
            </summary>
            <p>{e.detail}</p>
          </details>
        ))}
        {!events.length && (
          <p className="muted">No timestamped events recorded.</p>
        )}
      </div>
    </section>
  );
}
export function SessionWorkspace() {
  const w = useWorkspace(),
    { sessionId } = useParams(),
    [params, setParams] = useSearchParams(),
    [copied, setCopied] = useState("");
  const s = w.sessions.find((s) => s.id === sessionId);
  if (!s)
    return (
      <AppShell>
        <SourceNotice />
        <Empty title={w.loading ? "Loading research…" : "Session not found"}>
          <Link to="/sessions">Return to sessions</Link>
        </Empty>
      </AppShell>
    );
  const requestedTab = params.get("tab") ?? "overview";
  const tab = ["overview", "evidence", "verification", "trace"].includes(
      requestedTab,
    )
      ? requestedTab
      : "overview",
    candidates = s.evidence.filter(
      (e) =>
        e.id === params.get("evidence") &&
        (!params.get("task") || e.taskId === params.get("task")),
    ),
    selectedEvidence = candidates.length === 1 ? candidates[0] : undefined,
    selectedTask = s.tasks.find((t) => t.id === params.get("task"));
  function select(updates: Record<string, string>) {
    const next = new URLSearchParams(params);
    Object.entries(updates).forEach(([k, v]) =>
      v ? next.set(k, v) : next.delete(k),
    );
    setParams(next);
  }
  const rail = selectedEvidence ? (
    <EvidenceInspector evidence={selectedEvidence} session={s} />
  ) : (
    <AgentInspector
      session={s}
      task={selectedTask}
      onSelect={(id) => select({ task: id, evidence: "" })}
    />
  );
  const visible = s.evidence.filter(
    (e) =>
      (!params.get("stance") || e.stance === params.get("stance")) &&
      (!params.get("verdict") ||
        resolveVerdict(e, s.verification?.verdicts ?? [], s.evidence) ===
          params.get("verdict")) &&
      (!params.get("category") || e.category === params.get("category")) &&
      (!params.get("confidence") ||
        e.confidence === params.get("confidence")) &&
      (!params.get("agent") || e.taskId === params.get("agent")),
  );
  const inspect = (id: string, taskId?: string) =>
    select({ tab: "evidence", evidence: id, task: taskId ?? "" });
  return (
    <AppShell rail={rail}>
      <SourceNotice />
      <Link className="back-link" to="/sessions">
        <ArrowLeft size={14} /> All research
      </Link>
      <div className="document-heading">
        <div className="inline-meta">
          <Badge>
            {s.source === "demo" ? "DEMO RESEARCH" : "LOCAL SNAPSHOT"}
          </Badge>
          <span>{formatDate(s.snapshotAt)}</span>
        </div>
        <h1>{s.title}</h1>
        <p>{s.question}</p>
        <div className="document-status">
          <StateBadge
            status={s.verification?.overall_status ?? "not_reviewed"}
          />
          <span>{s.evidence.length} evidence items</span>
          <span>{s.tasks.length} analyst tasks</span>
        </div>
      </div>
      <div className="document-tabs" role="tablist" aria-label="Research views">
        {["overview", "evidence", "verification", "trace"].map((t) => (
          <button
            key={t}
            role="tab"
            aria-selected={tab === t}
            onClick={() => select({ tab: t, evidence: "" })}
          >
            {t[0].toUpperCase() + t.slice(1)}
            {t === "evidence" && <span>{s.evidence.length}</span>}
          </button>
        ))}
      </div>
      {!!s.diagnostics.length && (
        <details className="notice">
          <summary>
            {s.diagnostics.length} data issue(s) · Partial snapshot
          </summary>
          {s.diagnostics.map((d, i) => (
            <p key={i}>
              {d.file}: {d.message}
            </p>
          ))}
        </details>
      )}
      {params.get("evidence") && !selectedEvidence && (
        <div className="notice">
          Referenced evidence unavailable.{" "}
          <button onClick={() => select({ evidence: "" })}>
            Clear selection
          </button>
        </div>
      )}
      {tab === "overview" && (
        <>
          <RecordedFlow session={s} />
          <div className="research-document">
            {s.synthesis ? (
              <>
                <div className="executive-summary">
                  <span className="eyebrow">THE RESEARCH VIEW</span>
                  <p>{s.synthesis.executive_summary}</p>
                </div>
                {Object.entries(s.synthesis.analysis_by_dimension).map(
                  ([heading, text]) => (
                    <section key={heading}>
                      <h2>{heading.replaceAll("_", " ")}</h2>
                      <p>{text}</p>
                    </section>
                  ),
                )}
                <section>
                  <h2>Risks & counter-evidence</h2>
                  <p>{s.synthesis.risk_assessment}</p>
                  {s.synthesis.dissenting_views.map((v) => (
                    <blockquote key={v}>{v}</blockquote>
                  ))}
                </section>
                <section>
                  <h2>What to investigate next</h2>
                  <ul className="research-list">
                    {s.synthesis.actionable_signals.map((v) => (
                      <li key={v}>
                        <ArrowRight size={14} />
                        {v}
                      </li>
                    ))}
                  </ul>
                  <p className="confidence-note">
                    Research confidence: {s.synthesis.confidence_level}
                  </p>
                </section>
                <button
                  className="button"
                  onClick={() => select({ tab: "evidence" })}
                >
                  Explore session evidence <ArrowRight size={14} />
                </button>
              </>
            ) : (
              <Empty title="Synthesis not yet available">
                The available task reports and evidence remain accessible.
              </Empty>
            )}
          </div>
          <section className="task-board">
            <h2>Behind the research</h2>
            {s.tasks.map((t) => (
              <button
                className={t.id === selectedTask?.id ? "selected" : ""}
                key={t.id}
                onClick={() => select({ task: t.id, evidence: "" })}
              >
                <TaskIcon status={t.status} />
                <span>
                  <strong>{t.title}</strong>
                  <small>
                    {t.profile.replaceAll("_", " ")} · {t.kind}
                  </small>
                </span>
                <StateBadge status={t.status} />
                <ChevronRight size={14} />
              </button>
            ))}
          </section>
          <section className="subreports">
            <h2>Analyst reports</h2>
            {s.reports.map((r) => (
              <details key={r.task_id}>
                <summary>
                  {r.title}
                  <StateBadge status={r.status} />
                </summary>
                <p>{r.summary}</p>
                <h4>Open questions</h4>
                <ul>
                  {r.unanswered_questions.map((q) => (
                    <li key={q}>{q}</li>
                  ))}
                </ul>
                {r.contradictions.map((c) => (
                  <blockquote key={c}>{c}</blockquote>
                ))}
              </details>
            ))}
            {s.legacy.map((l) => (
              <details key={l.file}>
                <summary>
                  {l.file}
                  <Badge>Legacy · partial</Badge>
                </summary>
                <pre>{l.text}</pre>
              </details>
            ))}
          </section>
          {s.source === "demo" && s.synthesis && (
            <ThesisDiff sessionId={s.id} />
          )}
          <Timeline session={s} />
        </>
      )}
      {tab === "evidence" && (
        <>
          <div className="evidence-toolbar">
            {[
              [
                "stance",
                "All stances",
                ["supporting", "contradicting", "neutral"],
              ],
              [
                "verdict",
                "All verdicts",
                [
                  "verified",
                  "weak",
                  "rejected",
                  "unchecked",
                  "not_reviewed",
                  "ambiguous",
                ],
              ],
              ["confidence", "All confidence", ["high", "medium", "low"]],
              [
                "category",
                "All categories",
                [
                  "market_regime",
                  "crowded_positioning",
                  "fundamental_repricing",
                  "contradicting_evidence",
                  "other",
                ],
              ],
            ].map(([key, label, options]) => (
              <select
                key={String(key)}
                aria-label={String(label)}
                value={params.get(String(key)) ?? ""}
                onChange={(e) => select({ [String(key)]: e.target.value })}
              >
                <option value="">{label}</option>
                {(options as string[]).map((o) => (
                  <option key={o} value={o}>
                    {o.replaceAll("_", " ")}
                  </option>
                ))}
              </select>
            ))}
            <select
              aria-label="All analysts"
              value={params.get("agent") ?? ""}
              onChange={(e) => select({ agent: e.target.value })}
            >
              <option value="">All analysts</option>
              {s.tasks.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.profile.replaceAll("_", " ")}
                </option>
              ))}
            </select>
          </div>
          {visible.map((e) => (
            <EvidenceCard
              key={e.taskId + e.id}
              evidence={e}
              session={s}
              onInspect={() => inspect(e.id, e.taskId)}
            />
          ))}
          {!visible.length && (
            <Empty title="No evidence matches these filters">
              <button
                className="button"
                onClick={() => setParams({ tab: "evidence" })}
              >
                Clear filters
              </button>
            </Empty>
          )}
        </>
      )}
      {tab === "verification" && (
        <>
          {s.verification ? (
            <>
              <section className="verification-summary">
                <ShieldCheck size={23} />
                <div>
                  <h2>Independent verification</h2>
                  <p>{s.verification.summary}</p>
                  <StateBadge status={s.verification.overall_status} />
                </div>
              </section>
              {s.verification.verdicts.map((v, i) => (
                <button
                  className="verdict-row"
                  key={v.evidence_id + i}
                  onClick={() => inspect(v.evidence_id, v.task_id ?? undefined)}
                >
                  <StateBadge status={v.status} />
                  <span>
                    <strong>{v.claim}</strong>
                    <small>{v.notes}</small>
                  </span>
                  <ChevronRight size={16} />
                </button>
              ))}
              <h2 className="mt-8">Research gaps</h2>
              {s.verification.gaps.map((g) => (
                <div className="gap-card" key={g.id}>
                  <Badge tone="amber">{g.kind.replaceAll("_", " ")}</Badge>
                  <h3>{g.claim}</h3>
                  <p>{g.notes}</p>
                  {g.evidence_id && (
                    <button
                      className="text-link"
                      onClick={() =>
                        inspect(g.evidence_id!, g.task_id ?? undefined)
                      }
                    >
                      Inspect referenced evidence <ArrowRight size={13} />
                    </button>
                  )}
                </div>
              ))}
              {s.verification.unsupported_claims.map((c) => (
                <p className="notice error" key={c}>
                  Unsupported: {c}
                </p>
              ))}
              {s.verification.missing_evidence.map((c) => (
                <p className="notice" key={c}>
                  Missing evidence: {c}
                </p>
              ))}
            </>
          ) : (
            <Empty title="Not reviewed">
              No verification artifact exists for this session.
            </Empty>
          )}
        </>
      )}
      {tab === "trace" && (
        <>
          <div className="section-head">
            <div>
              <h2>Recorded tool observations</h2>
              <p>
                {s.traces.length} stored traces ·{" "}
                {s.tasks.reduce((a, t) => a + (t.tool_calls ?? 0), 0)} reported
                task tool calls
              </p>
            </div>
          </div>
          {s.traces.map((t) => (
            <details
              className="trace-card"
              key={t.id}
              open={params.get("trace") === t.id}
            >
              <summary>
                <FileText size={16} />
                <strong>{t.tool}</strong>
                <span>{formatDate(t.timestamp)}</span>
                <Badge>{t.replay.method.replaceAll("_", " ")}</Badge>
                <ChevronRight size={14} />
              </summary>
              <h4>Arguments</h4>
              <pre>{JSON.stringify(t.arguments, null, 2)}</pre>
              <h4>Stored observation</h4>
              <pre>{t.observation}</pre>
              {t.truncated && <Badge tone="amber">Truncated observation</Badge>}
              <details>
                <summary>Provenance</summary>
                <pre>
                  {JSON.stringify(
                    { sha256: t.observation_sha256, replay: t.replay },
                    null,
                    2,
                  )}
                </pre>
              </details>
              <button
                className="button"
                onClick={async () => {
                  try {
                    await navigator.clipboard.writeText(t.observation);
                    setCopied(t.id);
                  } catch {
                    setCopied("unavailable");
                  }
                }}
              >
                {copied === t.id ? <Check size={14} /> : <Copy size={14} />}{" "}
                {copied === t.id ? "Copied" : "Copy observation"}
              </button>
              {copied === "unavailable" && (
                <p role="status">
                  Clipboard unavailable; select the observation text to copy.
                </p>
              )}
            </details>
          ))}
          {!s.traces.length && (
            <Empty title="No stored traces">
              Only recorded engine and search observations appear here.
            </Empty>
          )}
        </>
      )}
    </AppShell>
  );
}
