import { it, expect, afterEach, vi } from "vitest";
import {
  ArtifactResearchDataSource,
  MockResearchDataSource,
} from "../src/data/adapters";
import { demoSessions, demoBriefs, demoGaps, profiles } from "../src/data/mock";
import { normalizeSession } from "../src/data/normalize";
afterEach(() => vi.unstubAllGlobals());
it("loads all workspace collections from one pinned manifest and reuses unchanged snapshots", async () => {
  let indexes = 0,
    objects = 0;
  vi.stubGlobal("fetch", async (url: string) => ({
    ok: true,
    json: async () => {
      if (url.endsWith("index.json")) {
        indexes++;
        return { ...manifest, gaps: demoGaps, profiles };
      }
      objects++;
      return url.endsWith("ok.json")
        ? { id: "ok", board: { question: "Q", tasks: [] } }
        : { brief: demoBriefs[0] };
    },
  }));
  const a = new ArtifactResearchDataSource();
  const first = await a.loadWorkspace();
  expect(first.sessions[0].question).toBe("Q");
  expect(first.briefs[0].status).toBe("partial");
  expect(indexes).toBe(1);
  const reads = objects;
  await a.loadWorkspace();
  expect(indexes).toBe(2);
  expect(objects).toBe(reads);
  vi.stubGlobal("fetch", async () => {
    throw new Error("offline");
  });
  await expect(a.loadWorkspace()).rejects.toThrow("offline");
});
const manifest = {
  schemaVersion: 1,
  snapshotId: "s",
  snapshotAt: "2026-01-01",
  availability: "partial",
  sessions: [{ id: "ok", path: "snapshots/s/ok.json" }],
  briefs: [
    { id: "brief", path: "snapshots/s/brief.json" },
    { id: "broken", path: "snapshots/s/broken.json" },
  ],
  gaps: [...demoGaps, { invalid: true }],
  profiles: [...profiles, { invalid: true }],
  diagnostics: [],
};
function fixture() {
  vi.stubGlobal("fetch", async (url: string) => ({
    ok: true,
    json: async () =>
      url.endsWith("index.json")
        ? manifest
        : url.endsWith("ok.json")
          ? { id: "ok", board: { question: "Q", tasks: [] } }
          : url.endsWith("brief.json")
            ? { brief: demoBriefs[0] }
            : { brief: null },
  }));
}
it("validates every artifact collection independently", async () => {
  fixture();
  const a = new ArtifactResearchDataSource();
  expect((await a.getSession("ok")).question).toBe("Q");
  await expect(a.getSession("missing")).rejects.toThrow("not found");
  expect(await a.getDailyBrief("brief")).toMatchObject({
    id: "brief",
    status: "partial",
  });
  await expect(a.getDailyBrief("broken")).rejects.toThrow("not found");
  expect(await a.listDailyBriefs()).toHaveLength(1);
  expect(await a.listGapLedgerEntries()).toHaveLength(3);
  expect(await a.listAgentProfiles()).toHaveLength(profiles.length);
  expect(a.diagnostics.map((d) => d.code)).toEqual(
    expect.arrayContaining([
      "brief_unavailable",
      "invalid_gap",
      "invalid_profile",
    ]),
  );
  await expect(a.file("../secret")).rejects.toThrow("Invalid snapshot");
});
it("reports missing manifest rather than silently substituting Demo", async () => {
  vi.stubGlobal("fetch", async () => ({ ok: false }));
  await expect(new ArtifactResearchDataSource().listSessions()).rejects.toThrow(
    "Local snapshot is unavailable",
  );
});
it("retains the last valid workspace when a new board fails its typed schema", async () => {
  let broken = false;
  vi.stubGlobal("fetch", async (url: string) => ({
    ok: true,
    json: async () =>
      url.endsWith("index.json")
        ? {
            ...manifest,
            snapshotId: broken ? "bad" : "good",
            briefs: [],
            gaps: [],
            profiles: [],
          }
        : {
            id: "ok",
            board: { question: broken ? 7 : "Valid question", tasks: [] },
          },
  }));
  const a = new ArtifactResearchDataSource();
  await a.loadWorkspace();
  broken = true;
  const next = await a.loadWorkspace();
  expect(next.sessions[0].question).toBe("Valid question");
  expect(next.diagnostics.some((d) => d.code === "schema_invalid")).toBe(true);
  expect(next.error).toMatch(/last complete snapshot/);
});
it("retries unavailable objects even when the manifest version has not changed", async () => {
  let fail = true;
  vi.stubGlobal("fetch", async (url: string) => ({
    ok: url.endsWith("index.json") || !fail,
    json: async () =>
      url.endsWith("index.json")
        ? { ...manifest, briefs: [], gaps: [], profiles: [] }
        : { id: "ok", board: { question: "Recovered", tasks: [] } },
  }));
  const a = new ArtifactResearchDataSource();
  expect((await a.loadWorkspace()).sessions).toHaveLength(0);
  fail = false;
  expect((await a.loadWorkspace()).sessions[0]?.question).toBe("Recovered");
});
it("retains the complete last workspace when a new snapshot object cannot be loaded", async () => {
  let version = "first",
    failed = false;
  vi.stubGlobal("fetch", async (url: string) => ({
    ok: url.endsWith("index.json") || !failed,
    json: async () =>
      url.endsWith("index.json")
        ? {
            ...manifest,
            snapshotId: version,
            briefs: [],
            gaps: [],
            profiles: [],
          }
        : { id: "ok", board: { question: version, tasks: [] } },
  }));
  const a = new ArtifactResearchDataSource();
  await a.loadWorkspace();
  version = "second";
  failed = true;
  const retained = await a.loadWorkspace();
  expect(retained.sessions[0]?.question).toBe("first");
  expect(retained.error).toMatch(/last complete snapshot/);
  failed = false;
  expect((await a.loadWorkspace()).sessions[0]?.question).toBe("second");
});
it("Mock and artifact share the same read-only lookup contract", async () => {
  const a = new MockResearchDataSource();
  expect(await a.getSession(demoSessions[0].id)).toEqual(demoSessions[0]);
  expect(await a.getDailyBrief(demoBriefs[0].id)).toEqual(demoBriefs[0]);
  await expect(a.getSession("missing")).rejects.toThrow();
  await expect(a.getDailyBrief("missing")).rejects.toThrow();
  expect(await a.listGapLedgerEntries()).toHaveLength(3);
  expect(await a.listAgentProfiles()).toHaveLength(6);
});
it("normalizes actual field names without upgrading partial reports or conflicting traces", () => {
  const s = demoSessions[0],
    trace = s.traces[0];
  const result = normalizeSession({
    id: "artifact",
    board: { question: s.question, tasks: s.tasks },
    reports: [...s.reports, { broken: true }],
    verification: s.verification,
    synthesis: s.synthesis,
    traces: [
      trace,
      trace,
      { ...trace, observation: "conflict" },
      { broken: true },
    ],
    legacy: [],
  });
  expect(result.reports).toHaveLength(s.reports.length);
  expect(result.reports[0].status).toBe(s.reports[0].status);
  expect(result.traces).toHaveLength(1);
  expect(result.updatedAt).toBeTruthy();
  expect(result.diagnostics.map((d) => d.code)).toContain("conflicting_trace");
});
