import { it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { ResearchAnswer } from '../src/components/research/ResearchAnswer';
import { ReportSchema, TraceSchema } from '../src/data/schemas';

it('renders numeric observations with units and missing values without substituting zero', () => {
  const report=ReportSchema.parse({task_id:'t',title:'Numeric view',agent_role:'momentum_analyst',summary:'Measured risk',status:'partial',findings:[],metrics:[
    {name:'21-day realized volatility',value:23.4,unit:'% annualized',as_of:'2026-09-08',source_url:'https://example.com',evidence_id:'e'},
    {name:'Short interest',value:null,unit:'% float',missing_reason:'No dated observation'}]});
  render(<ResearchAnswer report={report}/>);
  expect(screen.getByRole('table',{name:'Numeric observations'})).toBeVisible();
  expect(screen.getByText('23.4')).toBeVisible();
  expect(screen.getByText('% annualized')).toBeVisible();
  expect(screen.getByText('No dated observation')).toBeVisible();
});

it('shows a structured partial answer, observation date, evidence gaps and safe sources', () => {
  const report = ReportSchema.parse({task_id:'t',title:'Holdings',agent_role:'momentum_analyst',
    summary:'1. AAA — 10%\n2. BBB — 8%', status:'partial',findings:[],as_of:'2026-09-08',
    sources:['https://example.com/fund','javascript:alert(1)'],limitations:['Only two holdings available'],
    unanswered_questions:['Remaining eight holdings?']});
  render(<ResearchAnswer report={report} />);
  expect(screen.getByText(/AAA — 10%/)).toBeVisible();
  expect(screen.getByText(/2026-09-08/)).toBeVisible();
  expect(screen.getByText('Only two holdings available')).toBeVisible();
  expect(screen.getByText('Remaining eight holdings?')).toBeVisible();
  expect(screen.getAllByRole('link')).toHaveLength(1);
  expect(screen.getByText(/not independent verification/i)).toBeVisible();
});

it('accepts archived page-content traces and does not invent a legacy report date', () => {
  const report = ReportSchema.parse({task_id:'t',title:'Legacy',agent_role:'momentum_analyst',summary:'Saved answer',status:'partial',findings:[]});
  render(<ResearchAnswer report={report} />);
  expect(screen.getByText(/Data as-of: unknown/)).toBeVisible();
  expect(TraceSchema.safeParse({id:'r',tool:'read_url',arguments:{url:'https://example.com'},observation:'content',observation_sha256:'abc',timestamp:'2026-09-08',replay:{method:'stored_observation'}}).success).toBe(true);
});
