import type { z } from "zod";
import type {
  TaskSchema,
  EvidenceSchema,
  ReportSchema,
  VerdictSchema,
  VerificationSchema,
  SynthesisSchema,
  TraceSchema,
  BriefSchema,
  GapSchema,
  ProfileSchema,
  DiagnosticSchema,
} from "../data/schemas";
export type Task = z.infer<typeof TaskSchema>;
export type Evidence = z.infer<typeof EvidenceSchema> & { taskId: string };
export type Report = z.infer<typeof ReportSchema>;
export type Verdict = z.infer<typeof VerdictSchema>;
export type Verification = z.infer<typeof VerificationSchema>;
export type Synthesis = z.infer<typeof SynthesisSchema>;
export type Trace = z.infer<typeof TraceSchema>;
export type Brief = z.infer<typeof BriefSchema> & { id: string };
export type Gap = z.infer<typeof GapSchema> & { id: string };
export type Profile = z.infer<typeof ProfileSchema>;
export type Diagnostic = z.infer<typeof DiagnosticSchema>;
export type Source = "demo" | "artifact";
export interface Session {
  id: string;
  question: string;
  title: string;
  scope: string;
  source: Source;
  snapshotAt: string;
  updatedAt?: string | null;
  tasks: Task[];
  reports: Report[];
  evidence: Evidence[];
  verification: Verification | null;
  synthesis: Synthesis | null;
  traces: Trace[];
  diagnostics: Diagnostic[];
  legacy: { file: string; text: string }[];
}
export interface ResearchDataSource {
  listSessions(): Promise<Session[]>;
  getSession(id: string): Promise<Session>;
  listDailyBriefs(): Promise<Brief[]>;
  getDailyBrief(id: string): Promise<Brief>;
  listGapLedgerEntries(): Promise<Gap[]>;
  listAgentProfiles(): Promise<Profile[]>;
}
