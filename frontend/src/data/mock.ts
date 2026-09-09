import type { Session, Brief, Gap, Profile, Task, Report } from "../types";
const date = "2026-05-29T20:00:00Z";
export const profiles: Profile[] = [
  {
    name: "momentum_analyst",
    displayName: "Momentum analyst",
    description:
      "Investigates market regime, momentum fragility and unwind mechanisms.",
    tools: ["engine_query", "market_data", "web_search", "file_reader"],
    kind: "research",
  },
  {
    name: "flow_analyst",
    displayName: "Flow analyst",
    description:
      "Examines crowded positioning, ownership and liquidity evidence.",
    tools: ["engine_query", "market_data", "web_search", "file_reader"],
    kind: "research",
  },
  {
    name: "macro_analyst",
    displayName: "Macro analyst",
    description: "Places observed market moves in their macroeconomic context.",
    tools: ["market_data", "web_search", "file_reader"],
    kind: "research",
  },
  {
    name: "credit_analyst",
    displayName: "Credit analyst",
    description: "Reviews balance-sheet resilience and financing conditions.",
    tools: ["market_data", "web_search", "file_reader"],
    kind: "research",
  },
  {
    name: "technicals_analyst",
    displayName: "Technicals analyst",
    description:
      "Studies price structure, breadth and technical corroboration.",
    tools: ["market_data", "web_search", "file_reader"],
    kind: "research",
  },
  {
    name: "verifier",
    displayName: "Independent verifier",
    description:
      "Judges existing evidence; does not introduce new research claims.",
    tools: ["engine_query", "market_data", "web_search", "file_reader"],
    kind: "verification",
  },
];
const questions = [
  "Does capacity expansion change the NBIS investment thesis?",
  "Is momentum fragility building beneath a normal market regime?",
  "How concentrated is the AI infrastructure demand narrative?",
];
const headlines = [
  "Capacity is expanding. The demand question remains.",
  "A calm market can still carry crowded risk.",
  "The AI buildout has more than one side.",
];
const summaries = [
  "Capacity plans support the growth narrative, while customer concentration and funding needs call for a closer look.",
  "The illustrative engine assessment shows a normal regime. Positioning and unwind evidence still need independent checks.",
  "Partnership announcements strengthen the demand case. Timing, execution and source quality remain open questions.",
];
export const demoSessions: Session[] = questions.map((question, i) => {
  const id = ["demo-nbis", "demo-momentum", "demo-ai"][i];
  const tasks: Task[] = [
    "momentum_analyst",
    "flow_analyst",
    "macro_analyst",
  ].map((profile, j) => ({
    id: id + "-task-" + j,
    title: [
      "Assess the core thesis",
      "Check positioning evidence",
      "Review the macro context",
    ][j],
    assignment:
      question +
      " Focus: " +
      profiles.find((p) => p.name === profile)?.description,
    profile,
    status:
      i === 1 && j === 1
        ? "BLOCKED"
        : i === 0 && j === 2
          ? "ACTIVE"
          : "COMPLETED",
    kind: "research",
    created_at: date,
    started_at: date,
    completed_at: j === 2 ? null : date,
    tool_calls: [4, 3, 2][j],
    tokens_used: [1842, 1206, 938][j],
    error:
      i === 1 && j === 1
        ? "Primary positioning evidence was unavailable within the research budget."
        : null,
  }));
  const reports: Report[] = tasks.slice(0, 2).map((t, j) => ({
    task_id: t.id,
    title: j === 0 ? headlines[i] : "Counter-evidence and open questions",
    agent_role: t.profile,
    status: "partial",
    summary:
      j === 0
        ? summaries[i]
        : "Source coverage is incomplete. This sample illustrates how contrary evidence remains visible alongside the working thesis.",
    findings: [
      {
        id: id + "-e" + j,
        claim:
          j === 0
            ? [
                "Capacity expansion could ease a near-term supply constraint.",
                "Normal regime classification does not establish low overall risk.",
                "Announced partnerships provide evidence of customer interest.",
              ][i]
            : [
                "Customer concentration limits confidence in a broad demand conclusion.",
                "Direct positioning data is missing from the available source set.",
                "Public announcements alone do not establish realized utilization.",
              ][i],
        category: j === 0 ? "fundamental_repricing" : "contradicting_evidence",
        stance: j === 0 ? "supporting" : "contradicting",
        confidence: j === 0 ? "medium" : "low",
        source_name:
          j === 0
            ? "Illustrative company disclosure"
            : "Research coverage review",
        source_url: null,
        excerpt:
          j === 0
            ? "Sample excerpt: planned infrastructure investment remains subject to delivery schedules, financing and customer commitments."
            : "No independently corroborated utilization or positioning series is included in this demonstration.",
        published_at: date,
        retrieved_at: date,
        agent_id: t.id,
      },
    ],
    unanswered_questions: [
      "What would independently confirm the demand and utilization assumptions?",
    ],
    contradictions:
      j === 1
        ? ["Announced capacity is not the same as delivered capacity."]
        : [],
  }));
  const verification = {
    overall_status: "pass_with_caveats" as const,
    summary:
      "Illustrative verification: the bounded observation is supported; broader conclusions remain unchecked.",
    timestamp: date,
    verdicts: reports.map((r, j) => ({
      evidence_id: r.findings[0].id,
      task_id: r.task_id,
      claim: r.findings[0].claim,
      status: j === 0 ? ("verified" as const) : ("unchecked" as const),
      notes:
        j === 0
          ? "The sample claim stays within the scope of its illustrative source."
          : "Independent corroboration is not present.",
      issues: [],
    })),
    gaps: [
      {
        id: id + "-gap",
        kind: "missing_evidence",
        claim:
          "Obtain independently dated evidence of utilization or positioning.",
        notes: "This is a sample research gap.",
        evidence_id: reports[1].findings[0].id,
        task_id: tasks[1].id,
      },
    ],
    unsupported_claims: [],
    missing_evidence: [
      "A primary-source series to test the broader interpretation.",
    ],
  };
  return {
    id,
    question,
    title: headlines[i],
    scope: ["NBIS", "Momentum", "AI Infra"][i],
    source: "demo",
    snapshotAt: date,
    tasks,
    reports,
    evidence: reports.flatMap((r) =>
      r.findings.map((e) => ({ ...e, taskId: r.task_id })),
    ),
    verification,
    synthesis: {
      question,
      executive_summary: summaries[i],
      analysis_by_dimension: {
        "What changed":
          i === 0
            ? "The illustrative source set points to additional infrastructure capacity. This shifts the research focus from announced supply to delivery and utilization."
            : summaries[i],
        "Why it matters":
          "The investment interpretation depends on more than the headline. Execution, concentration and the quality of independent evidence determine how much weight the observation deserves.",
        "Thesis impact":
          "Maintain the working thesis with explicit conditions. Separate what the source establishes from the broader interpretation.",
      },
      risk_assessment:
        "The evidence is incomplete. Delivery risk, customer concentration and funding conditions remain material open questions.",
      actionable_signals: [
        "Check delivered capacity against announced milestones.",
        "Seek independent corroboration of utilization.",
        "Revisit the thesis when primary evidence changes.",
      ],
      confidence_level: "Medium — limited source coverage",
      dissenting_views: [
        "Capacity growth may run ahead of realized customer demand.",
      ],
      timestamp: date,
    },
    traces: [
      {
        id: id + "-trace",
        tool: "web_search",
        arguments: { query: question },
        observation:
          "DEMO OBSERVATION — a stored example source set for this research question. This record was not obtained through a live search.",
        observation_sha256: "demo-observation",
        truncated: false,
        timestamp: date,
        agent_id: tasks[0].id,
        agent_role: tasks[0].profile,
        replay: { method: "stored_observation", query: question },
      },
    ],
    diagnostics: [],
    legacy: [],
  };
});
export const demoBriefs: Brief[] = [
  {
    id: "demo-brief",
    schema_version: "daily_brief_v1",
    scope: "market/book",
    requested_as_of: "2026-05-29",
    generated_at: date,
    status: "partial",
    source_kind: "Illustrative historical engine",
    data_cutoff: date,
    metrics: {
      overall_risk_state: {
        value: "normal",
        source_field: "/overall_risk_state",
      },
      monitoring_severity_score: {
        value: 42,
        source_field: "/monitoring_severity_score",
      },
      crowded_unwind: {
        value: 58,
        source_field: "/mechanism_scores/crowded_unwind",
      },
      book_vulnerability: {
        value: 36,
        source_field: "/mechanism_scores/book_vulnerability",
      },
    },
    changes: {},
    comparison_note: "No comparable previous brief supplied.",
    limitations: [
      "Demo values illustrate the reading experience; they are not a current market assessment.",
      "Monitoring scores are not crash probabilities. A normal regime does not establish low overall risk.",
    ],
    delivery_contract: { verdict: "demo" },
    readiness: {},
    engine_fingerprint: "demo",
  },
];
export const demoGaps: Gap[] = demoSessions.map((s, i) => ({
  id: s.id + "-gap",
  evidence_id: s.evidence[1].id,
  capability: i === 1 ? "crowding" : "source_quality",
  status: i === 2 ? "CLOSED" : "OPEN",
  gap_kind: "missing_evidence",
  claim: s.verification!.gaps[0].claim,
  notes: "Sample occurrence retained for research continuity.",
  source_session_id: s.id,
  created_at: date,
}));
