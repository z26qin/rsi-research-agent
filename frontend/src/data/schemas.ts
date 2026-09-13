import { z } from "zod";
export const TaskSchema = z.object({
  id: z.string(),
  title: z.string(),
  assignment: z.string(),
  profile: z.string(),
  status: z.enum(["PENDING", "ACTIVE", "COMPLETED", "BLOCKED", "CANCELLED"]),
  kind: z.enum(["research", "gap", "replan", "followup"]).default("research"),
  started_at: z.string().nullable().optional(),
  completed_at: z.string().nullable().optional(),
  created_at: z.string().optional(),
  tool_calls: z.number().nonnegative().optional(),
  tokens_used: z.number().nonnegative().optional(),
  error: z.string().nullable().optional(),
  error_type: z.string().nullable().optional(),
});
export const EvidenceSchema = z.object({
  id: z.string(),
  claim: z.string(),
  category: z.enum([
    "market_regime",
    "crowded_positioning",
    "fundamental_repricing",
    "contradicting_evidence",
    "other",
  ]),
  stance: z.enum(["supporting", "contradicting", "neutral"]),
  confidence: z.enum(["high", "medium", "low"]),
  source_name: z.string().nullable().optional(),
  source_url: z.string().nullable().optional(),
  excerpt: z.string().nullable().optional(),
  published_at: z.string().nullable().optional(),
  retrieved_at: z.string().optional(),
  agent_id: z.string().nullable().optional(),
});
export const MetricSchema = z.object({
  name:z.string(), value:z.number().finite().nullable(), unit:z.string(),
  as_of:z.string().nullable().optional(),source_url:z.string().nullable().optional(),
  evidence_id:z.string().nullable().optional(),missing_reason:z.string().nullable().optional(),
});
export const ReportSchema = z.object({
  task_id: z.string(),
  title: z.string(),
  agent_role: z.string(),
  findings: z.array(EvidenceSchema),
  summary: z.string(),
  as_of: z.string().nullable().optional(),
  sources: z.array(z.string()).optional(),
  limitations: z.array(z.string()).optional(),
  metrics: z.array(MetricSchema).optional(),
  unanswered_questions: z.array(z.string()).default([]),
  contradictions: z.array(z.string()).default([]),
  status: z.enum(["complete", "partial", "insufficient_evidence"]),
});
export const VerdictSchema = z.object({
  evidence_id: z.string(),
  task_id: z.string().nullable().optional(),
  claim: z.string(),
  status: z.enum(["verified", "weak", "rejected", "unchecked"]),
  notes: z.string().default(""),
  issues: z.array(z.string()).default([]),
});
export const VerificationSchema = z.object({
  overall_status: z.enum(["pass", "pass_with_caveats", "fail"]),
  summary: z.string(),
  timestamp: z.string().optional(),
  verdicts: z.array(VerdictSchema),
  unsupported_claims: z.array(z.string()).default([]),
  missing_evidence: z.array(z.string()).default([]),
  gaps: z
    .array(
      z.object({
        id: z.string(),
        kind: z.string(),
        claim: z.string(),
        notes: z.string().default(""),
        evidence_id: z.string().nullable().optional(),
        task_id: z.string().nullable().optional(),
      }),
    )
    .default([]),
});
export const SynthesisSchema = z.object({
  question: z.string(),
  executive_summary: z.string(),
  metrics: z.array(MetricSchema).optional(),
  analysis_by_dimension: z.record(z.string(), z.string()),
  risk_assessment: z.string(),
  actionable_signals: z.array(z.string()),
  confidence_level: z.string(),
  dissenting_views: z.array(z.string()),
  timestamp: z.string(),
});
export const TraceSchema = z.object({
  id: z.string(),
  tool: z.enum(["engine_query", "web_search", "read_url"]),
  arguments: z.record(z.string(), z.unknown()),
  observation: z.string(),
  observation_sha256: z.string(),
  truncated: z.boolean().default(false),
  timestamp: z.string(),
  agent_id: z.string().nullable().optional(),
  agent_role: z.string().nullable().optional(),
  replay: z.object({
    method: z.enum(["engine_snapshot", "stored_observation"]),
    source: z.string().nullable().optional(),
    source_path: z.string().nullable().optional(),
    as_of: z.string().nullable().optional(),
    query: z.string().nullable().optional(),
  }),
});
const EngineBriefSchema = z.object({
  schema_version: z.literal("daily_brief_v1"),
  scope: z.literal("market/book"),
  requested_as_of: z.string(),
  generated_at: z.string(),
  status: z.enum(["partial", "unavailable"]),
  source_kind: z.string(),
  data_cutoff: z.string().nullable().optional(),
  metrics: z.record(
    z.string(),
    z.object({
      value: z.union([z.string(), z.number()]).nullable(),
      source_field: z.string(),
    }),
  ),
  changes: z.record(
    z.string(),
    z.object({
      previous: z.union([z.string(), z.number()]),
      current: z.union([z.string(), z.number()]),
      delta: z.number().optional(),
      source_field: z.string().optional(),
    }),
  ),
  comparison_note: z.string(),
  limitations: z.array(z.string()),
  delivery_contract: z.record(z.string(), z.unknown()).default({}),
  readiness: z.record(z.string(), z.unknown()).default({}),
  engine_fingerprint: z.string().nullable().optional(),
});
const ProxyBriefSchema = z.object({
  schema_version: z.literal('etf_proxy_brief_v1'), calculation_version: z.literal('etf_proxy_metrics_v1'),
  scope: z.literal('long_only_etf_proxy'), requested_as_of:z.string(), generated_at:z.string(),
  status:z.enum(['partial','unavailable']), metrics:z.record(z.string(),z.number().finite().nullable()),
  sources:z.record(z.string(),z.object({status:z.string(),latest_date:z.string().optional(),fetched_at:z.string().optional(),source:z.string().optional()})),
  vix:z.object({value:z.number(),observation_date:z.string(),stale:z.boolean()}).partial().default({}),
  changes:z.record(z.string(),z.object({previous:z.number(),current:z.number(),delta:z.number()})),
  comparison_note:z.string(), limitations:z.array(z.string()), llm_requests:z.literal(0),
  factor_context:z.object({model_status:z.literal('unavailable'),inputs:z.record(z.string(),z.object({as_of:z.string().nullable()}))}).optional(),
}).transform(b => ({...b, source_kind:'ETF proxy · MTUM / SPY', data_cutoff:b.requested_as_of + ' · completed session',
  metrics:Object.fromEntries(Object.entries(b.status === 'partial' ? b.metrics : {}).map(([name,value]) => [name,{value,source_field:'ETF adjusted-price snapshot'}])),
  delivery_contract:{status:'Proxy only; original engine not run'}, readiness:{sources:b.sources,factor_context:b.factor_context}, engine_fingerprint:null,
}));
export const BriefSchema = z.union([EngineBriefSchema, ProxyBriefSchema]);
export const GapSchema = z.object({
  evidence_id: z.string(),
  capability: z.enum([
    "crowding",
    "unwind_crash",
    "engine_freshness",
    "source_quality",
  ]),
  status: z.enum(["OPEN", "CONSUMED", "CLOSED"]),
  gap_kind: z.string(),
  claim: z.string(),
  notes: z.string().default(""),
  source_session_id: z.string().nullable().optional(),
  consumed_session_id: z.string().nullable().optional(),
  consumed_task_id: z.string().nullable().optional(),
  created_at: z.string(),
});
export const ProfileSchema = z.object({
  name: z.string(),
  displayName: z.string(),
  description: z.string(),
  tools: z.array(z.string()),
  kind: z.enum(["research", "verification"]),
});
export const DiagnosticSchema = z.object({
  file: z.string(),
  code: z.string(),
  message: z.string(),
});
export const ManifestSchema = z.object({
  schemaVersion: z.literal(1),
  snapshotId: z.string(),
  snapshotAt: z.string(),
  availability: z.enum(["complete", "partial", "unavailable"]),
  sessions: z.array(z.object({ id: z.string(), path: z.string() })),
  briefs: z.array(z.object({ id: z.string(), path: z.string() })),
  gaps: z.array(z.unknown()),
  profiles: z.array(z.unknown()),
  diagnostics: z.array(DiagnosticSchema),
});
