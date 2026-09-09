import { z } from "zod";
import {
  TaskSchema,
  ReportSchema,
  VerificationSchema,
  SynthesisSchema,
  TraceSchema,
  DiagnosticSchema,
} from "./schemas";
import type { Session, Verdict, Diagnostic } from "../types";
export function resolveVerdict(
  evidence: { id: string; taskId: string },
  verdicts: Pick<Verdict, "evidence_id" | "task_id" | "status" | "claim">[],
  allEvidence: { id: string; taskId: string }[] = [evidence],
) {
  const matches = verdicts.filter(
    (v) =>
      v.evidence_id === evidence.id &&
      (!v.task_id || v.task_id === evidence.taskId),
  );
  if (
    matches.some((v) => !v.task_id) &&
    allEvidence.filter((e) => e.id === evidence.id).length !== 1
  )
    return "ambiguous";
  if (matches.length > 1) return "ambiguous";
  return matches[0]?.status ?? "not_reviewed";
}
export function normalizeSession(raw: unknown): Session {
  const shell = z
    .object({
      id: z.string(),
      board: z.unknown().optional(),
      reports: z.array(z.unknown()).default([]),
      synthesis: z.unknown().optional(),
      verification: z.unknown().optional(),
      traces: z.array(z.unknown()).default([]),
      diagnostics: z.array(DiagnosticSchema).default([]),
      legacy: z
        .array(z.object({ file: z.string(), text: z.string() }))
        .default([]),
      snapshotAt: z.string().optional(),
    })
    .parse(raw);
  const diagnostics: Diagnostic[] = [...shell.diagnostics];
  function parse<T>(
    schema: z.ZodType<T>,
    data: unknown,
    file: string,
  ): T | null {
    if (data == null) return null;
    const result = schema.safeParse(data);
    if (result.success) return result.data;
    diagnostics.push({
      file,
      code: "schema_invalid",
      message: result.error.issues
        .map((i) => i.path.join(".") + ": " + i.message)
        .join("; "),
    });
    return null;
  }
  const board = parse(
    z.object({ question: z.string(), tasks: z.array(z.unknown()).default([]) }),
    shell.board,
    "task_board.json",
  );
  const tasks = (board?.tasks ?? []).flatMap((t) => {
    const parsed = parse(TaskSchema, t, "task_board.json");
    return parsed ? [parsed] : [];
  });
  const reports = shell.reports.flatMap((r) => {
    const parsed = parse(ReportSchema, r, "sub_reports");
    return parsed ? [parsed] : [];
  });
  const verification = parse(
    VerificationSchema,
    shell.verification,
    "verification.json",
  );
  const synthesis = parse(SynthesisSchema, shell.synthesis, "synthesis.json");
  const evidence = reports.flatMap((r) =>
    r.findings.map((e) => ({ ...e, taskId: r.task_id })),
  );
  const seen = new Map<string, string>();
  const traces = shell.traces.flatMap((t) => {
    const parsed = parse(TraceSchema, t, "traces.jsonl");
    if (!parsed) return [];
    const content = JSON.stringify(parsed);
    if (seen.has(parsed.id)) {
      if (seen.get(parsed.id) !== content)
        diagnostics.push({
          file: "traces.jsonl",
          code: "conflicting_trace",
          message: "Conflicting trace ID: " + parsed.id,
        });
      return [];
    }
    seen.set(parsed.id, content);
    return [parsed];
  });
  return {
    id: shell.id,
    question: board?.question ?? synthesis?.question ?? "Research session",
    title: reports[0]?.title ?? board?.question ?? "Research session",
    scope: "Research",
    source: "artifact",
    snapshotAt: shell.snapshotAt ?? "",
    updatedAt:
      [
        ...tasks.flatMap((t) => [t.created_at, t.started_at, t.completed_at]),
        ...traces.map((t) => t.timestamp),
        synthesis?.timestamp,
        verification?.timestamp,
      ]
        .filter((v): v is string => !!v && Number.isFinite(Date.parse(v)))
        .sort((a, b) => Date.parse(b) - Date.parse(a))[0] ?? null,
    tasks,
    reports,
    evidence,
    verification,
    synthesis,
    traces,
    diagnostics,
    legacy: shell.legacy,
  };
}
