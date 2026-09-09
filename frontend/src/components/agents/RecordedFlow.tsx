import { Link } from "react-router-dom";
import type { Session, Task } from "../../types";
import { StateBadge, formatDate } from "../shared/UI";

const groups: [Task["kind"], string][] = [
  ["research", "Research"],
  ["gap", "Gap seed"],
  ["replan", "Replan"],
  ["followup", "Follow-up"],
];
export function RecordedFlow({ session: s }: { session: Session }) {
  return (
    <section className="recorded-flow" aria-label="Recorded agent flow">
      <h2>Recorded agent flow</h2>
      <p className="muted">
        Saved task states, not process liveness. Last recorded event:{" "}
        {formatDate(
          s.updatedAt ?? (s.source === "demo" ? s.snapshotAt : undefined),
        )}
        .
      </p>
      <p className="brief-disclaimer">
        Decomposition and engine warm-up are not timed here unless recorded.
        Optional task groups appear only when present.
      </p>
      <div className="flow-groups">
        {groups.map(([kind, label]) => {
          const tasks = s.tasks.filter((t) => t.kind === kind);
          if (!tasks.length) return null;
          return (
            <div className="flow-group" key={kind}>
              <h3>{label}</h3>
              <ul>
                {tasks.map((t) => (
                  <li key={t.id}>
                    <div className="brief-timing">
                      <Link
                        aria-label={"Inspect task: " + t.title}
                        to={
                          "/sessions/" +
                          encodeURIComponent(s.id) +
                          "?task=" +
                          encodeURIComponent(t.id)
                        }
                      >
                        {t.title}
                      </Link>
                      <StateBadge status={t.status} />
                    </div>
                    <small>
                      {t.profile.replaceAll("_", " ")} · Report:{" "}
                      {s.reports.find((r) => r.task_id === t.id)?.status ??
                        "not recorded"}
                    </small>
                    {t.error && <p className="flow-error">{t.error}</p>}
                  </li>
                ))}
              </ul>
            </div>
          );
        })}
      </div>
      {!s.tasks.length && <p>No task board available.</p>}
      <div className="flow-outcomes">
        <div>
          <h3>Independent verification</h3>
          {s.verification ? (
            <>
              <StateBadge status={s.verification.overall_status} />
              <p>
                {s.verification.verdicts.length} recorded verdicts ·{" "}
                {s.verification.gaps.length} recorded gaps
              </p>
            </>
          ) : (
            <p>No verifier artifact recorded.</p>
          )}
        </div>
        <div>
          <h3>Research synthesis</h3>
          <p>
            {s.synthesis
              ? "Synthesis artifact available"
              : "No synthesis artifact recorded."}
          </p>
          <small>
            Artifact presence does not establish that every claim is verified.
          </small>
        </div>
      </div>
    </section>
  );
}
