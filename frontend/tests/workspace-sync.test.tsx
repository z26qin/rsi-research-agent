import { it, expect, vi, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { WorkspaceProvider, useWorkspace } from "../src/app/Workspace";

function Reader() {
  const w = useWorkspace();
  return (
    <>
      <div>{w.sessions.map((s) => s.question).join(" / ")}</div>
      <div>{w.error}</div>
      <div>{w.sync?.message}</div>
    </>
  );
}
afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

it("automatically refreshes Artifact data and retains the last loaded session on disconnect", async () => {
  sessionStorage.setItem("momentum-source", "artifact");
  let version = 1,
    disconnected = false;
  vi.stubGlobal("fetch", async (url: string) => {
    if (disconnected) throw new Error("offline");
    return {
      ok: true,
      json: async () =>
        url.endsWith("sync-status.json")
          ? {
              state: "ready",
              message: "Read-only automatic sync",
              checkedAt: new Date().toISOString(),
            }
          : url.endsWith("index.json")
            ? {
                schemaVersion: 1,
                snapshotId: "v" + version,
                snapshotAt: "2026-05-29",
                availability: "complete",
                sessions: [
                  { id: "s", path: "snapshots/v" + version + "/s.json" },
                ],
                briefs: [],
                gaps: [],
                profiles: [],
                diagnostics: [],
              }
            : {
                id: "s",
                board: { question: "Observed version " + version, tasks: [] },
              },
    };
  });
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <WorkspaceProvider>
        <Reader />
      </WorkspaceProvider>
    </QueryClientProvider>,
  );
  await screen.findByText("Observed version 1");
  version = 2;
  await waitFor(
    () => expect(screen.getByText("Observed version 2")).toBeInTheDocument(),
    { timeout: 5500 },
  );
  disconnected = true;
  await waitFor(
    () =>
      expect(screen.getByText(/Snapshot refresh failed/)).toBeInTheDocument(),
    { timeout: 5500 },
  );
  expect(screen.getByText("Observed version 2")).toBeInTheDocument();
}, 12000);

it("marks an expired watcher heartbeat stale instead of claiming automatic sync is healthy", async () => {
  sessionStorage.setItem("momentum-source", "artifact");
  vi.stubGlobal("fetch", async (url: string) => ({
    ok: true,
    json: async () =>
      url.endsWith("sync-status.json")
        ? {
            state: "ready",
            message: "Read-only automatic sync",
            checkedAt: "2020-01-01",
          }
        : {
            schemaVersion: 1,
            snapshotId: "empty",
            snapshotAt: "2020-01-01",
            availability: "unavailable",
            sessions: [],
            briefs: [],
            gaps: [],
            profiles: [],
            diagnostics: [],
          },
  }));
  render(
    <QueryClientProvider client={new QueryClient()}>
      <WorkspaceProvider>
        <Reader />
      </WorkspaceProvider>
    </QueryClientProvider>,
  );
  await screen.findByText(
    "Automatic sync is not responding; showing last snapshot.",
  );
});
