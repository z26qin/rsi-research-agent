import { Link } from "react-router-dom";
import { ArrowRight } from "lucide-react";
import type { Brief } from "../../types";
import { StateBadge, formatDate } from "../shared/UI";
import {BriefContext, briefValue} from './BriefContext';

export function LatestBrief({ briefs }: { briefs: Brief[] }) {
  const sorted = [...briefs].sort(
    (a, b) =>
      b.requested_as_of.localeCompare(a.requested_as_of) ||
      b.generated_at.localeCompare(a.generated_at),
  );
  const available = sorted.find((b) => b.status === "partial");
  const brief = available ?? sorted[0];
  const newer = available && sorted[0] !== available ? sorted[0] : null;
  return (
    <section className="latest-brief" aria-label="Latest daily brief">
      <div className="section-head">
        <div>
          <span className="eyebrow">{brief?.scope === 'long_only_etf_proxy' ? 'ETF MARKET OBSERVATIONS' : 'MARKET / BOOK · ENGINE ASSESSMENT'}</span>
          <h2>Latest daily brief</h2>
        </div>
        <Link className="text-link" to="/briefs">
          All briefs <ArrowRight size={14} />
        </Link>
      </div>
      {!brief ? (
        <p className="muted">No daily brief available</p>
      ) : (
        <>
          <div className="brief-timing">
            <strong>As of {brief.requested_as_of}</strong>
            <StateBadge status={brief.status} />
            <span>{brief.source_kind}</span>
          </div>
          <p className="muted">
            Data cutoff: {brief.data_cutoff ?? "Unavailable"} · Generated:{" "}
            {formatDate(brief.generated_at)}
          </p>
          {newer && (
            <p className="notice">
              <Link to={"/briefs/" + encodeURIComponent(newer.id)}>
                Newer attempt · {newer.requested_as_of} · assessment unavailable
              </Link>
              . Showing the latest available assessment below.
            </p>
          )}
          <BriefContext brief={brief} />
          {brief.status === "unavailable" ? (
            <p className="notice">
              Assessment withheld — inputs or delivery checks failed.
            </p>
          ) : (
            <>
              <div className="brief-overview-metrics">
                {(brief.scope === 'long_only_etf_proxy' ? [
                  ['MTUM.return_1d','MTUM · 1 day'], ['SPY.return_1d','SPY · 1 day'],
                  ['relative.return_21d','Relative · 21 sessions'], ['MTUM.volatility_21d','MTUM · annualized volatility'],
                ] : [
                  ["overall_risk_state", "Overall risk state"],
                  ["mechanical_unwind_state", "Mechanical unwind"],
                  ["pm_posture", "PM posture"],
                  ["monitoring_severity_score", "Monitoring severity"],
                ]).map(([key, label]) => (
                  <div key={key}>
                    <span>{label}</span>
                    <strong>
                      {briefValue(brief, brief.metrics[key]?.value)}
                    </strong>
                  </div>
                ))}
              </div>
              <p className="brief-disclaimer">
                {brief.scope === 'long_only_etf_proxy' ? 'Completed-session adjusted-price observations, not an intraday live feed or personal portfolio assessment.' : 'Monitoring scores are 0–100, not a probability. Historical/as-of context, not a live feed or personal portfolio assessment.'}
              </p>
              <details>
                <summary>What changed & limitations</summary>
                <p>{brief.comparison_note}</p>
                {Object.entries(brief.changes).map(([key, change]) => (
                  <p key={key}>
                    {key.replaceAll("_", " ")}: {briefValue(brief, change.previous)} →{" "}
                    {briefValue(brief, change.current)}
                  </p>
                ))}
                <ul>
                  {brief.limitations.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              </details>
            </>
          )}
          <Link
            className="button"
            to={"/briefs/" + encodeURIComponent(brief.id)}
          >
            Read daily brief <ArrowRight size={14} />
          </Link>
        </>
      )}
    </section>
  );
}
