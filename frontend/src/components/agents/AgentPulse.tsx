import { ArrowRight, MoreHorizontal, Clock, FileText } from "lucide-react";
import { Link } from "react-router-dom";
import { useWorkspace } from "../../app/Workspace";
import {
  ScopeMark,
  TaskIcon,
  Badge,
  formatDate,
  StateBadge,
} from "../shared/UI";
import type { Session } from "../../types";
export function AgentPulse({ session }: { session?: Session }) {
  const w = useWorkspace(),
    s = session ?? w.sessions[0];
  const complete = s?.tasks.filter((t) => t.status === "COMPLETED").length ?? 0,
    total = s?.tasks.length ?? 0;
  return (
    <>
      <section className="rail-card">
        <div className="rail-heading">
          <h2>Agent Pulse</h2>
          <span className="green inline-meta">
            <span className="dot active" />
            {w.source === "demo" ? "Demo activity" : "Task snapshot"}
          </span>
        </div>
        {s ? (
          <>
            <div className="agent-card">
              <div className="agent-title">
                <ScopeMark scope={s.scope} />
                <div>
                  <strong>{s.scope} Research</strong>
                  <p>
                    {s.tasks.some((t) => t.status === "ACTIVE")
                      ? "Research in progress (recorded)"
                      : s.tasks.some((t) => t.status === "BLOCKED")
                        ? "Blocked tasks in saved snapshot"
                        : "Saved research artifacts"}
                  </p>
                </div>
                <Link
                  to={"/sessions/" + encodeURIComponent(s.id)}
                  aria-label="Inspect research tasks"
                >
                  <MoreHorizontal size={17} />
                </Link>
              </div>
              <div className="progress-row">
                <div className="progress-track">
                  <span
                    style={{
                      width: (total ? (complete / total) * 100 : 0) + "%",
                    }}
                  />
                </div>
                <span>
                  {complete}/{total}
                </span>
              </div>
              <ul className="task-checklist">
                {s.tasks.map((t) => (
                  <li key={t.id}>
                    <TaskIcon status={t.status} />
                    <Link
                      to={
                        "/sessions/" +
                        encodeURIComponent(s.id) +
                        "?task=" +
                        t.id
                      }
                    >
                      {t.title}{" "}
                      <small>
                        · {t.kind} · {t.status.toLowerCase()}
                      </small>
                    </Link>
                  </li>
                ))}
                <li>
                  <TaskIcon status={s.verification ? "COMPLETED" : "PENDING"} />
                  <span>
                    Verifier artifact:{" "}
                    {s.verification?.overall_status ?? "not recorded"}
                  </span>
                </li>
                <li>
                  <TaskIcon status={s.synthesis ? "COMPLETED" : "PENDING"} />
                  <span>
                    Research synthesis:{" "}
                    {s.synthesis ? "available" : "not recorded"}
                  </span>
                </li>
              </ul>
              <p className="rail-caption">
                Task completion: {complete}/{total}. Not a live progress
                estimate.
              </p>
              {s.tasks
                .filter((t) => t.status === "BLOCKED" && t.error)
                .map((t) => (
                  <p className="flow-error" key={t.id}>
                    {t.title}: {t.error}
                  </p>
                ))}
            </div>
            <div className="agent-card">
              <div className="agent-title">
                <span className="monitor-mark">
                  <Clock size={23} />
                </span>
                <div>
                  <strong>Suggested review checks</strong>
                  <p>Reading checklist · not dispatched tasks</p>
                </div>
              </div>
              <div className="followup-note">
                <Badge tone="amber">
                  {s.verification?.gaps.length ?? 0} open questions
                </Badge>
              </div>
              <ul className="task-checklist">
                <li>
                  <TaskIcon status="PENDING" />
                  <span>Find independent corroboration</span>
                </li>
                <li>
                  <TaskIcon status="PENDING" />
                  <span>Review source coverage</span>
                </li>
                <li>
                  <TaskIcon status="PENDING" />
                  <span>Resolve conflicting evidence</span>
                </li>
              </ul>
            </div>
          </>
        ) : (
          <p className="muted">No task snapshot available.</p>
        )}
        <Link className="button rail-button" to="/agents">
          View all agents <ArrowRight size={14} />
        </Link>
      </section>
      <section className="rail-card">
        <div className="rail-heading">
          <h3>Recent activity</h3>
          <Link to="/sessions">
            View all <ArrowRight size={12} />
          </Link>
        </div>
        {w.sessions.slice(0, 3).map((s) => (
          <Link
            className="activity-row"
            key={s.id}
            to={"/sessions/" + encodeURIComponent(s.id)}
          >
            <span className="activity-date">
              {formatDate(
                s.source === "demo" ? s.snapshotAt : s.updatedAt,
              ).replace(", 2026", "")}
            </span>
            <ScopeMark small scope={s.scope} />
            <span>{s.scope} · Research update</span>
          </Link>
        ))}
        <p className="rail-caption">
          Recorded events ·{" "}
          {w.source === "demo" ? "illustrative data" : "local snapshot"}
        </p>
      </section>
      <section className="rail-card">
        <div className="rail-heading">
          <h3>Recent research</h3>
          <Link to="/library">
            View all <ArrowRight size={12} />
          </Link>
        </div>
        {w.sessions.slice(0, 3).map((s) => (
          <Link
            className="research-row"
            key={s.id}
            to={"/sessions/" + encodeURIComponent(s.id)}
          >
            <FileText size={15} />
            <span>
              {s.scope} —{" "}
              {s.reports[0]?.agent_role.includes("momentum")
                ? "Thesis review"
                : "Research update"}
            </span>
            <StateBadge status={s.reports[0]?.status ?? "unavailable"} />
          </Link>
        ))}
      </section>
    </>
  );
}
