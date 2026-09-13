import type { Report } from '../../types';

export function NumericObservations({metrics}: {metrics:Report['metrics']}) {
  if (!metrics?.length) return <p className="muted">No structured numeric observations available. Do not infer missing metrics from the narrative.</p>;
  return <section><h3>Numeric observations</h3><p className="muted">Source-reported analyst observations, not independently verified conclusions.</p>
    <div style={{overflowX:'auto'}}><table aria-label="Numeric observations"><thead><tr>
      <th>Metric</th><th>Value</th><th>Unit</th><th>Data as-of</th><th>Source / evidence</th>
    </tr></thead><tbody>{metrics.map((m,i)=><tr key={i}>
      <td>{m.name}</td><td>{m.value === null ? (m.missing_reason ?? 'Unavailable') : m.value}</td>
      <td>{m.unit}</td><td>{m.as_of ?? 'Unknown'}</td><td>
        {m.source_url && /^https?:\/\//i.test(m.source_url) ? <a href={m.source_url} target="_blank" rel="noopener noreferrer">Source</a> : 'No source'}
        {m.evidence_id && <small> · {m.evidence_id}</small>}
      </td></tr>)}</tbody></table></div></section>;
}
