import { Check, Search, X } from "lucide-react";
import { useReviewMark } from "../../hooks/useReviewMark";
export function ThesisDiff({ sessionId }: { sessionId: string }) {
  const { value, mark, notice } = useReviewMark("demo-diff-v1:" + sessionId);
  return (
    <section className="thesis-diff">
      <div className="rail-heading">
        <span className="eyebrow">THESIS CHANGE</span>
        <span className="muted text-xs">Illustrative proposal</span>
      </div>
      <div className="diff-previous">
        <span>Previous</span>
        <p>Infrastructure capacity remains the key constraint.</p>
      </div>
      <div className="diff-new">
        <span>New evidence</span>
        <p>
          Planned capacity has increased; delivery and utilization remain
          unconfirmed.
        </p>
        <span>Proposed update</span>
        <p>Test the demand assumptions before strengthening the thesis.</p>
      </div>
      <div className="diff-actions">
        <button className="button dark" onClick={() => mark("accepted")}>
          <Check size={14} />
          Accept
        </button>
        <button className="button" onClick={() => mark("rejected")}>
          <X size={14} />
          Reject
        </button>
        <button className="text-link" onClick={() => mark("investigate")}>
          <Search size={14} />
          Investigate
        </button>
      </div>
      <p className="diff-note" role="status">
        {value
          ? "Marked " + value + " for your review. Verification is unchanged."
          : "Local review only. This proposal is part of the demo."}
        {notice}
      </p>
    </section>
  );
}
