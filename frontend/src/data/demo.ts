import type { Session } from "../types";
import { z } from "zod";
import {
  TaskSchema,
  ReportSchema,
  EvidenceSchema,
  VerificationSchema,
  SynthesisSchema,
  TraceSchema,
  DiagnosticSchema,
} from "./schemas";
const SessionSchema = z.object({
  id: z.string(),
  question: z.string(),
  title: z.string(),
  scope: z.string(),
  source: z.literal("demo"),
  snapshotAt: z.string(),
  tasks: z.array(TaskSchema),
  reports: z.array(ReportSchema),
  evidence: z.array(EvidenceSchema.extend({ taskId: z.string() })),
  verification: VerificationSchema.nullable(),
  synthesis: SynthesisSchema.nullable(),
  traces: z.array(TraceSchema),
  diagnostics: z.array(DiagnosticSchema),
  legacy: z.array(z.object({ file: z.string(), text: z.string() })),
});
export function restoreDemo(raw: unknown): DemoState | null {
  const result = z
    .object({
      session: SessionSchema,
      template: SessionSchema,
      stage: z.number().int().min(0).max(5),
      paused: z.boolean(),
    })
    .safeParse(raw);
  return result.success ? result.data : null;
}
export interface DemoState {
  session: Session;
  stage: number;
  paused: boolean;
  template?: Session;
}
export const stages = [
  "Preparing research",
  "Decomposing the question",
  "Analysts researching",
  "Checking evidence",
  "Writing the synthesis",
  "Research complete",
];
export function advanceDemo(state: DemoState): DemoState {
  if (state.paused || state.stage >= 5) return state;
  const stage = state.stage + 1;
  const template = state.template ?? state.session;
  return {
    ...state,
    stage,
    session: {
      ...state.session,
      reports: stage >= 3 ? template.reports : [],
      evidence: stage >= 3 ? template.evidence : [],
      traces: stage >= 2 ? template.traces : [],
      verification: stage >= 4 ? template.verification : null,
      synthesis: stage >= 5 ? template.synthesis : null,
      tasks: state.session.tasks.map((t, i) => ({
        ...t,
        tool_calls: stage >= 3 ? template.tasks[i]?.tool_calls : 0,
        tokens_used: stage >= 3 ? template.tasks[i]?.tokens_used : 0,
        status:
          stage >= 3
            ? "COMPLETED"
            : stage >= 2
              ? i === 0
                ? "COMPLETED"
                : "ACTIVE"
              : "PENDING",
      })),
    },
  };
}
