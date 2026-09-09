import { Bookmark, ArrowUpRight, Quote, ShieldCheck } from "lucide-react";
import type { Evidence, Session } from "../../types";
import { Badge, StateBadge, formatDate } from "../shared/UI";
import { resolveVerdict } from "../../data/normalize";
import { useReviewMark } from "../../hooks/useReviewMark";
export function EvidenceCard({
  evidence: e,
  session: s,
  onInspect,
}: {
  evidence: Evidence;
  session: Session;
  onInspect: () => void;
}) {
  const review = useReviewMark(
    JSON.stringify([s.source, s.id, e.taskId, e.id, e.claim]),
  );
  const status = resolveVerdict(e, s.verification?.verdicts ?? [], s.evidence);
  return (
    <article className="evidence-card">
      <div className="evidence-meta">
        <Badge>{e.stance}</Badge>
        <span>{e.category.replaceAll("_", " ")}</span>
        <button
          className={"icon-button " + (review.value === "saved" ? "green" : "")}
          aria-label={"Save evidence: " + e.claim}
          onClick={() => review.mark(review.value === "saved" ? "" : "saved")}
        >
          <Bookmark size={15} />
        </button>
      </div>
      <h3>{e.claim}</h3>
      <div className="evidence-source">
        <Quote size={15} />
        <strong>{e.source_name ?? "Source not recorded"}</strong>
        <small>{formatDate(e.published_at)}</small>
      </div>
      {e.excerpt && <blockquote>{e.excerpt}</blockquote>}
      <div className="evidence-bottom">
        <span>
          Agent confidence <strong>{e.confidence}</strong>
        </span>
        <StateBadge status={status} />
        <button className="text-link" onClick={onInspect}>
          Inspect evidence <ArrowUpRight size={14} />
        </button>
      </div>
      {review.notice && <small role="status">{review.notice}</small>}
    </article>
  );
}
export function EvidenceInspector({
  evidence: e,
  session: s,
}: {
  evidence: Evidence;
  session: Session;
}) {
  const verdicts =
    s.verification?.verdicts.filter(
      (v) => v.evidence_id === e.id && (!v.task_id || v.task_id === e.taskId),
    ) ?? [];
  const safeUrl =
    e.source_url && /^https?:\/\//i.test(e.source_url) ? e.source_url : null;
  return (
    <section className="rail-card inspector-card">
      <span className="eyebrow">EVIDENCE INSPECTOR</span>
      <h2>{e.claim}</h2>
      <StateBadge
        status={resolveVerdict(e, s.verification?.verdicts ?? [], s.evidence)}
      />
      <div className="inspector-section">
        <h4>Source</h4>
        <p>{e.source_name ?? "Source not recorded"}</p>
        {safeUrl ? (
          <a
            className="text-link"
            href={safeUrl}
            target="_blank"
            rel="noopener noreferrer"
          >
            Open source <ArrowUpRight size={13} />
          </a>
        ) : (
          <small className="muted">Source link unavailable</small>
        )}
      </div>
      <div className="inspector-section">
        <h4>Source excerpt</h4>
        <p>{e.excerpt ?? "No excerpt was recorded."}</p>
      </div>
      <div className="inspector-section">
        <h4>
          <ShieldCheck size={14} /> Independent verification
        </h4>
        {resolveVerdict(e, s.verification?.verdicts ?? [], s.evidence) ===
        "ambiguous" ? (
          <p>
            Conflicting or unscoped verdicts cannot be uniquely linked to this
            evidence. Review the original verification records.
          </p>
        ) : verdicts.length ? (
          verdicts.map((v, i) => <p key={i}>{v.notes || v.status}</p>)
        ) : (
          <p>This evidence has not been reviewed.</p>
        )}
      </div>
      <dl className="metadata-list">
        <dt>Stance</dt>
        <dd>{e.stance}</dd>
        <dt>Agent confidence</dt>
        <dd>{e.confidence}</dd>
        <dt>Retrieved</dt>
        <dd>{formatDate(e.retrieved_at)}</dd>
      </dl>
      <details>
        <summary>Record identifiers</summary>
        <code>
          {e.id}
          <br />
          {e.taskId}
        </code>
      </details>
    </section>
  );
}
