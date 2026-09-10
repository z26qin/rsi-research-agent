import type { Report } from '../../types';
import { StateBadge } from '../shared/UI';
import { NumericObservations } from './NumericObservations';

export function ResearchAnswer({report}: {report: Report}) {
  const sources = [...new Set([...(report.sources ?? []), ...report.findings.map(f => f.source_url)])]
    .filter((url): url is string => !!url && /^https?:\/\//i.test(url));
  return <section className="executive-summary" aria-label="Research answer">
    <h2>{report.title}</h2>
    <StateBadge status={report.status} />
    <p style={{whiteSpace:'pre-wrap'}}>{report.summary}</p>
    <NumericObservations metrics={report.metrics}/>
    <p className="muted">Data as-of: {report.as_of ?? 'unknown'} · Analyst answer, not independent verification.</p>
    {!!sources.length && <><h3>Sources / source leads</h3><ul>{sources.map(url =>
      <li key={url}><a href={url} target="_blank" rel="noopener noreferrer">{url}</a></li>)}</ul></>}
    {!!((report.limitations?.length ?? 0) + report.unanswered_questions.length) && <>
      <h3>Limitations & unanswered questions</h3><ul>
        {[...new Set([...(report.limitations ?? []), ...report.unanswered_questions])].map(item => <li key={item}>{item}</li>)}
      </ul></>}
  </section>;
}
