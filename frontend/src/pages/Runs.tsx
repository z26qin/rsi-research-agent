import { useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { AppShell } from '../components/layout/AppShell';
import { Badge, formatDate } from '../components/shared/UI';
import { useWorkspace } from '../app/Workspace';
import { controlRequest, RunRequestSchema, type RunRequest, type ControlStatus } from '../data/control';

function readPending(kind: 'research' | 'brief'): RunRequest | undefined {
  try {
    const saved = sessionStorage.getItem('momentum-pending-' + kind);
    const parsed = RunRequestSchema.safeParse(JSON.parse(saved ?? 'null'));
    return parsed.success && parsed.data.kind === kind ? parsed.data : undefined;
  } catch { return undefined; }
}
function torontoTime(value: string | null) {
  return value ? new Date(value).toLocaleString('en-CA', {timeZone: 'America/Toronto'}) : 'Not scheduled';
}
export function Runs() {
  const w = useWorkspace(), [params] = useSearchParams();
  const [saved, setSaved] = useState<Partial<Record<'research' | 'brief', RunRequest>>>(() => ({research: readPending('research'), brief: readPending('brief')}));
  const research = saved.research?.kind === 'research' ? saved.research : undefined;
  const brief = saved.brief?.kind === 'brief' ? saved.brief : undefined;
  const [question, setQuestion] = useState(research?.question ?? params.get('q') ?? '');
  const [mode, setMode] = useState(research?.mode ?? 'auto'), [agents, setAgents] = useState(research?.agents ?? 1), [asOf, setAsOf] = useState(brief?.as_of ?? '');
  const [researchConfirmed, setResearchConfirmed] = useState(false), [briefConfirmed, setBriefConfirmed] = useState(false);
  const [pending, setPending] = useState(false), [notice, setNotice] = useState('');
  const query = useQuery<ControlStatus>({queryKey: ['control-status'], queryFn: () => controlRequest('/status'), retry: false, refetchInterval: 3000});
  const online = !!query.data && !query.error;
  const active = query.data?.jobs.some(j => ['starting', 'running'].includes(j.state));
  const disabled = !online || pending || active;
  function clearPending(kind: 'research' | 'brief') {
    setSaved(old => ({...old, [kind]: undefined}));
    try { sessionStorage.removeItem('momentum-pending-' + kind); } catch { /* storage unavailable */ }
    setResearchConfirmed(false); setBriefConfirmed(false);
  }
  useEffect(() => {
    for (const kind of ['research', 'brief'] as const) {
      if (saved[kind] && query.data?.jobs.some(j => j.request.request_id === saved[kind]?.request_id)) {
        clearPending(kind);
        setNotice('Previously submitted run found in history. It will not be submitted again.');
      }
    }
  }, [query.data, saved]);
  async function submit(kind: 'research' | 'brief') {
    if (pending) return;
    setPending(true); setNotice('');
    const request: RunRequest = saved[kind] ?? (kind === 'research'
      ? {kind, confirmed: true, request_id: crypto.randomUUID(), question: question.trim(), mode, agents: mode === 'single' ? 1 : agents}
      : {kind, confirmed: true, request_id: crypto.randomUUID(), as_of: asOf});
    setSaved(old => ({...old, [kind]: request}));
    try { sessionStorage.setItem('momentum-pending-' + kind, JSON.stringify(request)); } catch { /* in-memory recovery still available */ }
    try {
      await controlRequest('/jobs', request);
      clearPending(kind);
      setNotice('Run accepted. Follow the process below; artifacts appear after synchronization.');
      w.setSource('artifact'); await query.refetch();
    } catch (e) {
      setNotice(String(e instanceof Error ? e.message : e) + ' Check run history before retrying. The original request is retained for safe retry.');
    } finally { setPending(false); }
  }
  async function toggleSchedule() {
    if (!query.data || pending) return;
    setPending(true); setNotice('');
    try { await controlRequest('/schedule', {enabled: !query.data.schedule.enabled}); await query.refetch(); }
    catch (e) { setNotice(String(e instanceof Error ? e.message : e)); }
    finally { setPending(false); }
  }
  const schedule = query.data?.schedule;
  const proxy = query.data?.brief_source === 'etf-proxy';
  return <AppShell>
    <div className="page-title"><span className="eyebrow">LOCAL EXECUTION · NOT DEMO</span><h1>Runs & daily schedule.</h1><p>Research starts only with your confirmation. Daily Brief makes no LLM calls.</p></div>
    <div className="notice" role="status">{online ? 'Service online' : query.isPending ? 'Connecting to local service…' : 'Local control service is offline. Start it locally to enable execution.'}<button className="text-link" onClick={() => query.refetch()}>Refresh service status</button></div>
    {notice && <p className="notice" role="alert">{notice}</p>}
    {(['research', 'brief'] as const).filter(kind => saved[kind]).map(kind => <div className="notice" key={kind}>An uncertain {kind} request is saved. Retry sends exactly the original request. Check history before starting a new one; this does not cancel an accepted run.<button className="text-link" disabled={pending || active} onClick={() => clearPending(kind)}>Start a new {kind} request</button></div>)}
    <section className="latest-brief" aria-label="Daily brief schedule"><div className="section-head"><h2>Daily Brief schedule</h2><Badge>{schedule?.enabled ? 'ENABLED' : 'DISABLED / OFFLINE'}</Badge></div>
      <p><strong>08:00 · America/Toronto</strong> · daylight saving adjusts automatically.</p>
      <p>{proxy ? 'ETF proxy: downloads MTUM/SPY and optional VIX for the latest completed session. One scheduled collection per trading date; provider failure is not automatically retried as a new run.' : 'Latest completed NYSE session. Input checks every 15 minutes until 10:00; at most one scheduled engine attempt per trading date.'}</p>
      <div className="brief-timing"><span>Next check: {torontoTime(schedule?.next_check ?? null)}</span><span>State: {schedule?.state ?? 'unknown'}</span></div>
      <p>{schedule?.message ?? 'Schedule settings require the local service.'}</p>
      {schedule?.target && <p>Target as-of: {schedule.target} · checks: {schedule.checks}/9</p>}
      <button className="button" disabled={!online || pending} onClick={toggleSchedule}>{schedule?.enabled ? 'Disable daily brief schedule' : 'Enable daily brief schedule'}</button>
      <p className="brief-disclaimer">Computer must be awake and service running. No historical catch-up. Calendar: 2026–2028; unscheduled closures require an update. Disabling does not cancel an active run.</p>
    </section>
    <div className="run-forms">
      <form className="latest-brief" onSubmit={e => {e.preventDefault(); if (researchConfirmed && !disabled) void submit('research');}}>
        <h2>Run research</h2><label>Research question<textarea aria-label="Research question" disabled={pending || !!research} value={question} maxLength={4000} onChange={e => setQuestion(e.target.value)} required /></label>
        <div className="brief-timing"><label>Mode<select aria-label="Research mode" disabled={pending || !!research} value={mode} onChange={e => setMode(e.target.value as 'auto' | 'single' | 'team')}><option value="auto">Auto — identify question type</option><option value="single">Direct answer — Single analyst</option><option value="team">Deep research — Team</option></select></label><label>Research analysts<select aria-label="Analyst count" disabled={pending || !!research || mode === 'single'} value={mode === 'single' ? 1 : agents} onChange={e => setAgents(Number(e.target.value))}>{[1,2,3,4].map(n => <option key={n}>{n}</option>)}</select></label></div>
        <p className="brief-disclaimer">Auto uses transparent question rules: factual lookups use one analyst; comparisons, causal explanations and assessments use deep research. You can override it. Direct answers skip decomposition, engine warm-up and follow-up; independent verification remains separate. Deep research with one analyst still runs the full workflow.</p>
        <p className="brief-disclaimer">May incur API charges. Existing agent budgets apply. Service deadline: direct answer 2 minutes; deep research 15 minutes. No automatic retry.</p>
        <label className="run-confirm"><input type="checkbox" checked={researchConfirmed} onChange={e => setResearchConfirmed(e.target.checked)} />I authorize this research run and its backend API usage.</label>
        <button className="button dark" disabled={disabled || !researchConfirmed || !question.trim()}>Run research</button>
      </form>
      <form className="latest-brief" onSubmit={e => {e.preventDefault(); if (briefConfirmed && !disabled) void submit('brief');}}>
        <h2>Generate Daily Brief</h2><label>Completed-session date<input aria-label="Brief as-of date" disabled={pending || !!brief} type="date" value={asOf} onChange={e => setAsOf(e.target.value)} required /></label>
        <p className="brief-disclaimer">{proxy ? 'Bounded public-data collection for MTUM/SPY and optional VIX. No LLM calls or original-model risk score. Source collection budget: 120 seconds; service deadline: 3 minutes. Missing target-session prices withhold the market observations.' : 'One bounded engine run with cached inputs; no data fetching or LLM calls. Service deadline: 3 minutes. Missing coverage produces an unavailable assessment.'}</p>
        <label className="run-confirm"><input type="checkbox" checked={briefConfirmed} onChange={e => setBriefConfirmed(e.target.checked)} />I authorize generating this local Daily Brief.</label>
        <button className="button dark" disabled={disabled || !briefConfirmed || !asOf}>Generate daily brief</button>
      </form>
    </div>
    <section className="latest-brief"><h2>Run history</h2>{active && <p className="notice">A service-owned job is active. New submissions are blocked until it finishes.</p>}
      {!query.data?.jobs.length && <p className="muted">No service-owned runs recorded.</p>}
      {query.data?.jobs.map(job => <article key={job.id} className="run-history-item"><div className="brief-timing"><strong>{job.request.kind === 'research' ? job.request.question : 'Daily Brief · ' + job.request.as_of}</strong><Badge>{job.state === 'completed' ? 'Process finished' : job.state.replaceAll('_', ' ')}</Badge></div><p>{job.message}</p>
        {job.routing && <p>{job.routing.intent === 'direct_answer' ? 'Direct answer' : 'Deep research'} · {job.routing.reason}</p>}
        {job.answer_status && <p>Answer coverage: {{unknown:'unknown',unanswered:'Question unanswered',partial:'Partial answer',answer_available:'Answer available — not independently verified'}[job.answer_status]}</p>}
        <p className="muted">{job.scheduled ? 'Scheduled' : 'Manual'} · Started {formatDate(job.created_at)}{job.finished_at ? ' · Finished ' + formatDate(job.finished_at) : ''}</p>
        {['completed', 'unavailable', 'failed', 'timed_out', 'interrupted'].includes(job.state) && <Link className="text-link" onClick={() => w.setSource('artifact')} to={(job.request.kind === 'brief' ? '/briefs/' : '/sessions/') + encodeURIComponent(job.artifact_id)}>View saved artifacts →</Link>}
      </article>)}
      <p className="brief-disclaimer">Process completion is not independent verification. Direct CLI runs outside this service are not included in this run queue.</p>
    </section>
  </AppShell>;
}
