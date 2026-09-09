import type {Brief} from '../../types';
export function briefValue(brief:Brief, value:string | number | null | undefined) {
  if (value === null || value === undefined) return 'Unavailable';
  return brief.scope === 'long_only_etf_proxy' && typeof value === 'number' ? (value * 100).toFixed(2) + '%' : String(value);
}
export function BriefContext({brief}:{brief:Brief}) {
  if (brief.scope !== 'long_only_etf_proxy') return null;
  return <div className="notice">
    <p>{brief.status === 'partial' ? 'Market observations available' : 'Market observations unavailable'} · Original model assessment unavailable.</p>
    <p>MTUM is a long-only ETF proxy, not the model book. No engine risk scores or crash probability.</p>
    {Object.entries(brief.sources).map(([name,s]) => <p key={name}>{name}: {s.latest_date ?? 'Unavailable'} · {s.status}{s.fetched_at ? ' · retrieved ' + s.fetched_at : ''}</p>)}
    {brief.vix.value !== undefined && <p>VIX: {brief.vix.value} index points · {brief.vix.observation_date}{brief.vix.stale ? ' · lagged' : ''}</p>}
    <p>Factor cache background — not used to calculate ETF observations:</p>
    {Object.entries(brief.factor_context?.inputs ?? {}).map(([name,s]) => <p key={name}>{name}: {s.as_of ?? 'Unavailable'}{s.as_of && s.as_of < brief.requested_as_of ? ' · lagged' : ''}</p>)}
    {!brief.factor_context && <p>Factor cache context unavailable.</p>}
  </div>;
}
