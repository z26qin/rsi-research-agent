import { ArrowRight, Files, ShieldCheck } from "lucide-react";
import { Link } from "react-router-dom";
import type { Session } from "../../types";
import { ScopeMark, Badge, formatDate } from "../shared/UI";
export function ResearchCard({ session: s }: { session: Session }) {
  const verified =
    s.verification?.verdicts.filter((v) => v.status === "verified").length ?? 0;
  return (
    <article className="research-card">
      <div className="research-card-top">
        <ScopeMark scope={s.scope} />
        <div className="card-company">
          <strong>{s.scope}</strong>
          <p>
            {s.scope === "NBIS"
              ? "Company research"
              : s.scope === "Momentum"
                ? "Market mechanisms"
                : "Thematic research"}
          </p>
        </div>
        <div className="card-stamp">
          <Badge
            tone={s.verification?.overall_status === "fail" ? "red" : "amber"}
          >
            {s.reports[0]?.status ?? "unavailable"}
          </Badge>
          <small>
            {formatDate(
              s.source === "demo" ? s.snapshotAt : s.updatedAt,
            ).replace(", 2026", "")}
          </small>
        </div>
      </div>
      <Link
        className="card-headline"
        to={"/sessions/" + encodeURIComponent(s.id)}
      >
        <h3>{s.title}</h3>
      </Link>
      <p className="card-summary">
        {s.reports[0]?.summary ??
          "Open this session to review its available research artifacts."}
      </p>
      <div className="card-badges">
        <Badge tone="green">
          <ShieldCheck size={12} />
          {verified} verified
        </Badge>
        <Badge>{s.evidence.length} evidence items</Badge>
      </div>
      <div className="card-source">
        <Files size={12} />
        {s.source === "demo"
          ? "Illustrative sources · Demo research"
          : "Stored reports · Source evidence"}
      </div>
      <Link
        className="button card-cta"
        to={"/sessions/" + encodeURIComponent(s.id)}
      >
        Open research <ArrowRight size={14} />
      </Link>
    </article>
  );
}
