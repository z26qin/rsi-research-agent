import type {
  ResearchDataSource,
  Session,
  Brief,
  Gap,
  Profile,
  Diagnostic,
} from "../types";
import { demoSessions, demoBriefs, demoGaps, profiles } from "./mock";
import {
  ManifestSchema,
  BriefSchema,
  GapSchema,
  ProfileSchema,
} from "./schemas";
import { normalizeSession } from "./normalize";
import { z } from "zod";
export class MockResearchDataSource implements ResearchDataSource {
  async listSessions() {
    return demoSessions;
  }
  async getSession(id: string) {
    const s = demoSessions.find((s) => s.id === id);
    if (!s) throw new Error("Session not found");
    return s;
  }
  async listDailyBriefs() {
    return demoBriefs;
  }
  async getDailyBrief(id: string) {
    const b = demoBriefs.find((b) => b.id === id);
    if (!b) throw new Error("Brief not found");
    return b;
  }
  async listGapLedgerEntries() {
    return demoGaps;
  }
  async listAgentProfiles() {
    return profiles;
  }
}
async function read(path: string) {
  const response = await fetch("/artifacts/" + path, { cache: "no-store" });
  if (!response.ok)
    throw new Error(
      "Local snapshot is unavailable. Run sync:artifacts and refresh.",
    );
  return response.json();
}
export class ArtifactResearchDataSource implements ResearchDataSource {
  private pinned?: z.infer<typeof ManifestSchema>;
  private cached?: Awaited<ReturnType<ArtifactResearchDataSource["collect"]>>;
  private cachedKey?: string;
  async loadWorkspace() {
    const manifest = ManifestSchema.parse(await read("index.json"));
    const key = JSON.stringify(manifest);
    if (this.cached && this.cachedKey === key) return this.cached;
    // A separate scoped adapter prevents overlap between successive refreshes.
    const scoped = new ArtifactResearchDataSource();
    scoped.pinned = manifest;
    const result = await scoped.collect();
    const incomplete = result.diagnostics.some((d) =>
      [
        "session_unavailable",
        "brief_unavailable",
        "schema_invalid",
        "invalid_gap",
        "invalid_profile",
      ].includes(d.code),
    );
    if (incomplete && this.cached)
      return {
        ...this.cached,
        diagnostics: result.diagnostics,
        error:
          "Some snapshot files are unavailable; showing last complete snapshot.",
      };
    if (!incomplete) {
      this.cached = result;
      this.cachedKey = key;
    }
    return result;
  }
  async collect() {
    const manifest = await this.manifest();
    const [sessions, briefs, gaps, profiles] = await Promise.all([
      this.listSessions(),
      this.listDailyBriefs(),
      this.listGapLedgerEntries(),
      this.listAgentProfiles(),
    ]);
    sessions.sort((a, b) =>
      (b.updatedAt ?? "").localeCompare(a.updatedAt ?? ""),
    );
    briefs.sort(
      (a, b) =>
        b.requested_as_of.localeCompare(a.requested_as_of) ||
        b.generated_at.localeCompare(a.generated_at),
    );
    return {
      sessions,
      briefs,
      gaps,
      profiles,
      diagnostics: [
        ...this.diagnostics,
        ...sessions.flatMap((s) =>
          s.diagnostics.map((d) => ({ ...d, file: s.id + "/" + d.file })),
        ),
      ],
      snapshotAt: manifest.snapshotAt,
      snapshotId: manifest.snapshotId,
      error: "",
    };
  }
  diagnostics: Diagnostic[] = [];
  addDiagnostic(d: Diagnostic) {
    if (
      !this.diagnostics.some(
        (x) =>
          x.file === d.file && x.code === d.code && x.message === d.message,
      )
    )
      this.diagnostics.push(d);
  }
  async manifest() {
    const m = this.pinned ?? ManifestSchema.parse(await read("index.json"));
    m.diagnostics.forEach((d) => this.addDiagnostic(d));
    return m;
  }
  async file(path: string) {
    if (!/^snapshots\/[a-zA-Z0-9_-]+\/[a-zA-Z0-9_.-]+\.json$/.test(path))
      throw new Error("Invalid snapshot reference");
    return read(path);
  }
  async listSessions() {
    const m = await this.manifest();
    const rows = await Promise.all(
      m.sessions.map(async (r) => {
        try {
          return normalizeSession(await this.file(r.path));
        } catch (e) {
          this.addDiagnostic({
            file: r.path,
            code: "session_unavailable",
            message: String(e),
          });
          return null;
        }
      }),
    );
    return rows.filter((s): s is Session => s !== null);
  }
  async getSession(id: string) {
    const m = await this.manifest();
    const row = m.sessions.find((s) => s.id === id);
    if (!row) throw new Error("Session not found");
    return normalizeSession(await this.file(row.path));
  }
  async listDailyBriefs(): Promise<Brief[]> {
    const m = await this.manifest();
    return Promise.all(
      m.briefs.map(async (r) => {
        try {
          const envelope = z
            .object({ brief: BriefSchema })
            .parse(await this.file(r.path));
          return { ...envelope.brief, id: r.id };
        } catch (e) {
          this.addDiagnostic({
            file: r.path,
            code: "brief_unavailable",
            message: String(e),
          });
          return null;
        }
      }),
    ).then((rows) => rows.filter((b): b is Brief => b !== null));
  }
  async getDailyBrief(id: string) {
    const b = (await this.listDailyBriefs()).find((b) => b.id === id);
    if (!b) throw new Error("Brief not found");
    return b;
  }
  async listGapLedgerEntries(): Promise<Gap[]> {
    const m = await this.manifest();
    return m.gaps.flatMap((row, i) => {
      const r = GapSchema.safeParse(row);
      if (r.success)
        return [
          {
            ...r.data,
            id: JSON.stringify([
              r.data.source_session_id ?? "unknown-" + i,
              r.data.evidence_id,
            ]),
          },
        ];
      this.addDiagnostic({
        file: "gap_ledger.jsonl",
        code: "invalid_gap",
        message: "Gap row " + (i + 1) + " failed schema validation.",
      });
      return [];
    });
  }
  async listAgentProfiles(): Promise<Profile[]> {
    const m = await this.manifest();
    return m.profiles.flatMap((row) => {
      const r = ProfileSchema.safeParse(row);
      if (r.success) return [r.data];
      this.addDiagnostic({
        file: "profiles",
        code: "invalid_profile",
        message: "A profile failed schema validation.",
      });
      return [];
    });
  }
}
