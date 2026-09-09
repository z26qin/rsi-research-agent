import { z } from 'zod';
export const RunRequestSchema = z.discriminatedUnion('kind', [
  z.object({kind: z.literal('research'), request_id: z.string().min(8), confirmed: z.literal(true), question: z.string().min(1).max(4000), mode: z.enum(['single', 'team']), agents: z.number().int().min(1).max(4)}),
  z.object({kind: z.literal('brief'), request_id: z.string().min(8), confirmed: z.literal(true), as_of: z.string().regex(/^\d{4}-\d{2}-\d{2}$/)}),
]);
export type RunRequest = z.infer<typeof RunRequestSchema>;
export const ControlStatusSchema = z.object({
  service: z.literal('online'), checked_at: z.string(), calendar: z.string(),
  brief_source: z.enum(['engine','etf-proxy']).default('engine'),
  limits: z.object({research_seconds: z.number(), brief_seconds: z.number()}),
  jobs: z.array(z.object({id: z.string(), artifact_id: z.string(),
    state: z.enum(['starting', 'running', 'completed', 'unavailable', 'failed', 'timed_out', 'interrupted']),
    message: z.string(), scheduled: z.boolean(), created_at: z.string(), finished_at: z.string().nullable(),
    request: RunRequestSchema})),
  schedule: z.object({enabled: z.boolean(), timezone: z.string(), time: z.string(), state: z.string(),
    message: z.string(), checks: z.number(), next_check: z.string().nullable(), target: z.string().optional()}),
});
export type ControlStatus = z.infer<typeof ControlStatusSchema>;
export async function controlRequest(endpoint: '/status' | '/jobs' | '/schedule', payload?: unknown) {
  const response = await fetch('/control' + endpoint, {
    method: payload === undefined ? 'GET' : 'POST', cache: 'no-store', headers: {'Content-Type': 'application/json'},
    body: payload === undefined ? undefined : JSON.stringify(payload), signal: AbortSignal.timeout(12000),
  });
  const value = await response.json();
  if (!response.ok) throw new Error(typeof value?.error === 'string' ? value.error : 'Local service request failed');
  return endpoint === '/status' ? ControlStatusSchema.parse(value) : value;
}
