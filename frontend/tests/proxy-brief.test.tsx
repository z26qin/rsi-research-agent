import {it, expect} from 'vitest';
import {render, screen} from '@testing-library/react';
import {MemoryRouter} from 'react-router-dom';
import {BriefSchema} from '../src/data/schemas';
import {LatestBrief} from '../src/components/dashboard/LatestBrief';

const raw = {schema_version:'etf_proxy_brief_v1', calculation_version:'etf_proxy_metrics_v1', scope:'long_only_etf_proxy', requested_as_of:'2026-09-08', generated_at:'2026-09-09T12:00:00Z', status:'partial', metrics:{'MTUM.return_1d':0.0123,'SPY.return_1d':0.004,'relative.return_21d':null,'MTUM.volatility_21d':0.2}, sources:{MTUM:{status:'ok',latest_date:'2026-09-08'}}, vix:{}, changes:{}, comparison_note:'No previous proxy brief supplied.', limitations:['Proxy only'], llm_requests:0, factor_context:{model_status:'unavailable',inputs:{french:{as_of:'2026-07-31'}}}};
it('normalizes proxy percentages without inventing original engine scores', () => {
  const parsed = BriefSchema.safeParse(raw);
  expect(parsed.success).toBe(true);
  if (!parsed.success) return;
  expect(parsed.data.metrics['MTUM.return_1d'].value).toBe(0.0123);
  expect(parsed.data.metrics.overall_risk_state).toBeUndefined();
  render(<MemoryRouter><LatestBrief briefs={[{...parsed.data,id:'proxy-1'}]} /></MemoryRouter>);
  expect(screen.getByText('1.23%')).toBeInTheDocument();
  expect(screen.getByText(/Original model assessment unavailable/)).toBeInTheDocument();
  expect(screen.getByText(/2026-07-31/)).toBeInTheDocument();
});
it('withholds all proxy metrics when status is unavailable', () => {
  const parsed = BriefSchema.safeParse({...raw,status:'unavailable'});
  expect(parsed.success).toBe(true);
  if (parsed.success) expect(parsed.data.metrics).toEqual({});
});
