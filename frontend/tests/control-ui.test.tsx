import { it, expect, vi, afterEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { WorkspaceProvider } from '../src/app/Workspace';
import { Runs } from '../src/pages/Runs';

const status = {service: 'online', checked_at: '2026-09-09T00:00:00Z', jobs: [],
  schedule: {enabled: false, timezone: 'America/Toronto', time: '08:00', state: 'disabled', message: 'Disabled', checks: 0, next_check: null},
  calendar: 'NYSE 2026–2028', limits: {research_seconds: 900, brief_seconds: 180}};
afterEach(() => { vi.unstubAllGlobals(); sessionStorage.clear(); });
function mount() {
  return render(<QueryClientProvider client={new QueryClient({defaultOptions: {queries: {retry: false}}})}><MemoryRouter><WorkspaceProvider><Runs /></WorkspaceProvider></MemoryRouter></QueryClientProvider>);
}
it('keeps execution unavailable when the local service is offline', async () => {
  vi.stubGlobal('fetch', async () => {throw new Error('offline');});
  mount();
  await screen.findByText(/Local control service is offline/);
  expect(screen.getByRole('button', {name: 'Run research'})).toBeDisabled();
});
it('distinguishes a finished process from an unanswered question and shows its route', async () => {
  const request = {kind:'research',question:'MTUM holdings',mode:'auto',agents:1,confirmed:true,request_id:'coverage-run'};
  vi.stubGlobal('fetch', async () => ({ok:true,json:async () => ({...status,jobs:[{
    id:'job-coverage',artifact_id:'saved',request,state:'completed',message:'Process ended',scheduled:false,
    created_at:status.checked_at,finished_at:status.checked_at,answer_status:'unanswered',
    routing:{mode:'single',intent:'direct_answer',reason:'Factual lookup'}
  }]})}));
  mount();
  expect(await screen.findByText('Process finished')).toBeVisible();
  expect(screen.getByText('Answer coverage: Question unanswered')).toBeVisible();
  expect(screen.getByText('Direct answer · Factual lookup')).toBeVisible();
});
it('requires explicit confirmation and sends only the approved research parameters', async () => {
  const writes: any[] = [];
  vi.stubGlobal('fetch', async (url: string, options?: RequestInit) => {
    if (options?.method === 'POST') writes.push(JSON.parse(String(options.body)));
    return {ok: true, json: async () => options?.method === 'POST' ? {id: 'new-job'} : status};
  });
  const user = userEvent.setup();
  mount();
  await screen.findByText('Service online');
  await user.type(screen.getByLabelText('Research question'), 'Explain the current risk');
  expect(screen.getByRole('button', {name: 'Run research'})).toBeDisabled();
  await user.click(screen.getByLabelText(/I authorize this research run/));
  await user.click(screen.getByRole('button', {name: 'Run research'}));
  await waitFor(() => expect(writes).toHaveLength(1));
  expect(writes[0]).toMatchObject({kind: 'research', question: 'Explain the current risk', confirmed: true, mode: 'auto', agents: 1});
  expect(writes[0].request_id).toBeTruthy();
});
it('toggles the Toronto schedule without submitting a research job', async () => {
  const writes: {url: string; body: unknown}[] = [];
  vi.stubGlobal('fetch', async (url: string, options?: RequestInit) => {
    if (options?.method === 'POST') writes.push({url, body: JSON.parse(String(options.body))});
    return {ok: true, json: async () => status};
  });
  const user = userEvent.setup();
  mount();
  await screen.findByText('Service online');
  await user.click(screen.getByRole('button', {name: 'Enable daily brief schedule'}));
  await waitFor(() => expect(writes).toEqual([{url: '/control/schedule', body: {enabled: true}}]));
  expect(screen.getByText(/08:00.*America\/Toronto/)).toBeInTheDocument();
});
it('restores the full uncertain request after refresh and permits an explicit new request', async () => {
  const saved = {kind: 'research', question: 'Original question', mode: 'single', agents: 1, confirmed: true, request_id: 'retained-key'};
  sessionStorage.setItem('momentum-pending-research', JSON.stringify(saved));
  const writes: unknown[] = [];
  vi.stubGlobal('fetch', async (_url: string, options?: RequestInit) => {
    if (options?.method === 'POST') { writes.push(JSON.parse(String(options.body))); throw new Error('connection lost'); }
    return {ok: true, json: async () => status};
  });
  const user = userEvent.setup(); mount();
  await screen.findByText('Service online');
  expect(screen.getByLabelText('Research question')).toHaveValue('Original question');
  expect(screen.getByLabelText('Research question')).toBeDisabled();
  await user.click(screen.getByLabelText(/I authorize this research run/));
  await user.click(screen.getByRole('button', {name: 'Run research'}));
  await waitFor(() => expect(writes).toEqual([saved]));
  await user.click(screen.getByRole('button', {name: 'Start a new research request'}));
  expect(screen.getByLabelText('Research question')).toBeEnabled();
  expect(sessionStorage.getItem('momentum-pending-research')).toBeNull();
  expect(screen.getByRole('button', {name: 'Run research'})).toBeDisabled();
});
it('reconciles an accepted pending brief from history and links its saved artifact', async () => {
  const request = {kind: 'brief', as_of: '2026-09-08', confirmed: true, request_id: 'accepted-brief'};
  sessionStorage.setItem('momentum-pending-brief', JSON.stringify(request));
  vi.stubGlobal('fetch', async () => ({ok: true, json: async () => ({...status, jobs: [{id:'job-1', artifact_id:'brief_saved', request, state:'unavailable', message:'Inputs missing', scheduled:true, created_at:status.checked_at, finished_at:status.checked_at}]})}));
  mount();
  await screen.findByText(/Previously submitted run found/);
  expect(sessionStorage.getItem('momentum-pending-brief')).toBeNull();
  expect(screen.getByRole('link', {name: /View saved artifacts/})).toHaveAttribute('href', '/briefs/brief_saved');
  expect(screen.getByLabelText('Brief as-of date')).toHaveValue('2026-09-08');
});
it('requires brief confirmation and submits the selected date only', async () => {
  const writes: unknown[] = [];
  vi.stubGlobal('fetch', async (_url: string, options?: RequestInit) => {
    if (options?.method === 'POST') writes.push(JSON.parse(String(options.body)));
    return {ok:true, json:async () => status};
  });
  const user = userEvent.setup(); mount();
  await screen.findByText('Service online');
  await user.type(screen.getByLabelText('Brief as-of date'), '2026-09-08');
  expect(screen.getByRole('button', {name:'Generate daily brief'})).toBeDisabled();
  await user.click(screen.getByLabelText(/I authorize generating/));
  await user.click(screen.getByRole('button', {name:'Generate daily brief'}));
  await waitFor(() => expect(writes).toHaveLength(1));
  expect(writes[0]).toMatchObject({kind:'brief', as_of:'2026-09-08', confirmed:true});
});
