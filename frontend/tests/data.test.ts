import { describe, it, expect, vi, afterEach } from "vitest";
import { ArtifactResearchDataSource } from "../src/data/adapters";
import { normalizeSession, resolveVerdict } from "../src/data/normalize";
import { demoSessions } from "../src/data/mock";
import { advanceDemo } from "../src/data/demo";
describe("source semantics", () => {
  afterEach(() => vi.unstubAllGlobals());
  it("keeps valid sessions when a sibling is malformed and surfaces diagnostics", async () => {
    const adapter = new ArtifactResearchDataSource();
    vi.stubGlobal("fetch", async (url: string) => ({
      ok: true,
      json: async () =>
        url.endsWith("index.json")
          ? {
              schemaVersion: 1,
              snapshotId: "s",
              snapshotAt: "2026-05-29T20:00:00Z",
              availability: "partial",
              sessions: [
                { id: "ok", path: "snapshots/s/ok.json" },
                { id: "bad", path: "snapshots/s/bad.json" },
              ],
              briefs: [],
              gaps: [],
              profiles: [],
              diagnostics: [
                {
                  file: "reports",
                  code: "stale_source",
                  message: "Previous snapshot retained",
                },
              ],
            }
          : url.endsWith("ok.json")
            ? {
                id: "ok",
                board: { question: "Q", tasks: [] },
                reports: [],
                diagnostics: [],
              }
            : { not: "a session" },
    }));
    expect((await adapter.listSessions()).map((s) => s.id)).toEqual(["ok"]);
    expect(adapter.diagnostics.some((d) => d.code === "stale_source")).toBe(
      true,
    );
    expect(
      adapter.diagnostics.some((d) => d.code === "session_unavailable"),
    ).toBe(true);
  });
  it("does not apply a taskless verdict across duplicate evidence IDs", () => {
    const e = { id: "e", taskId: "a" };
    expect(
      resolveVerdict(
        e,
        [{ evidence_id: "e", claim: "Q", status: "verified" }],
        [e, { id: "e", taskId: "b" }],
      ),
    ).toBe("ambiguous");
  });
  it("keeps missing review distinct from unchecked and cannot invent a report", () => {
    const session = normalizeSession({
      id: "x",
      board: { question: "Q", tasks: [] },
      reports: [],
      traces: [],
      diagnostics: [],
    });
    expect(session.synthesis).toBeNull();
    expect(session.verification).toBeNull();
    expect(resolveVerdict({ id: "e", taskId: "t" }, [])).toBe("not_reviewed");
    expect(
      resolveVerdict({ id: "e", taskId: "t" }, [
        { evidence_id: "e", task_id: "t", status: "unchecked", claim: "Q" },
      ]),
    ).toBe("unchecked");
  });
  it("does not choose an optimistic verdict when references are ambiguous", () => {
    expect(
      resolveVerdict({ id: "e", taskId: "t" }, [
        { evidence_id: "e", task_id: "t", status: "verified", claim: "Q" },
        { evidence_id: "e", task_id: "t", status: "rejected", claim: "Q" },
      ]),
    ).toBe("ambiguous");
  });
  it("marks malformed task data partial rather than silently accepting it", () => {
    const session = normalizeSession({
      id: "bad",
      board: { question: "Q", tasks: [{ id: "x", status: "imaginary" }] },
      reports: [],
      diagnostics: [],
    });
    expect(session.diagnostics.length).toBeGreaterThan(0);
    expect(session.tasks).toHaveLength(0);
  });
  it("does not advance paused demo and never runs beyond final stage", () => {
    const initial = {
      session: structuredClone(demoSessions[0]),
      stage: 0,
      paused: true,
    };
    expect(advanceDemo(initial)).toEqual(initial);
    let running = { ...initial, paused: false };
    for (let i = 0; i < 20; i++) running = advanceDemo(running);
    expect(running.stage).toBe(5);
    expect(advanceDemo(running)).toEqual(running);
  });
});
