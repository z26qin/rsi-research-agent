import { FileText, ArrowRight } from "lucide-react";
import type { Session, Task } from "../../types";
import { TaskIcon, StateBadge, formatDate, Badge } from "../shared/UI";
export function AgentInspector({
  session: s,
  task,
  onSelect,
}: {
  session: Session;
  task?: Task;
  onSelect: (id: string) => void;
}) {
  const selected = task ?? s.tasks[0];
  return (
    <section className="rail-card inspector-card">
      <div className="rail-heading">
        <span className="eyebrow">RESEARCH RUN</span>
        <Badge>{s.source === "demo" ? "DEMO" : "SNAPSHOT"}</Badge>
      </div>
      <h2>{s.scope} Research</h2>
      <p className="muted">Recorded work behind the research.</p>
      <div className="inspector-section">
        <h4>Goal</h4>
        <p>{s.question}</p>
      </div>
      <div className="inspector-section">
        <h4>Research plan</h4>
        <ul className="inspector-plan">
          {s.tasks.map((t) => (
            <li key={t.id}>
              <button
                className={t.id === selected?.id ? "selected" : ""}
                onClick={() => onSelect(t.id)}
              >
                <TaskIcon status={t.status} />
                <span>
                  {t.title}
                  <small>{t.profile.replaceAll("_", " ")}</small>
                </span>
              </button>
            </li>
          ))}
        </ul>
      </div>
      {selected && (
        <>
          <div className="inspector-section">
            <div className="rail-heading">
              <h4>Selected task</h4>
              <StateBadge status={selected.status} />
            </div>
            <p>{selected.assignment}</p>
            {selected.error && (
              <div className="notice error">{selected.error}</div>
            )}
            <Badge>{selected.kind}</Badge>
          </div>
          <div className="inspector-metrics">
            <div>
              <span>Tool calls</span>
              <strong>{selected.tool_calls ?? "—"}</strong>
            </div>
            <div>
              <span>Tokens</span>
              <strong>{selected.tokens_used?.toLocaleString() ?? "—"}</strong>
            </div>
            <div>
              <span>Evidence</span>
              <strong>
                {s.evidence.filter((e) => e.taskId === selected.id).length}
              </strong>
            </div>
            <div>
              <span>Stored traces</span>
              <strong>
                {s.traces.filter((t) => t.agent_id === selected.id).length}
              </strong>
            </div>
          </div>
        </>
      )}
      <p className="rail-caption">
        Snapshot · {formatDate(s.snapshotAt)}
        <br />
        Recorded status does not establish process liveness.
      </p>
    </section>
  );
}
