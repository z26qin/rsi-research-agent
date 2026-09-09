/// <reference types="node" />
import { it, expect, vi, onTestFinished } from "vitest";
import {
  mkdtempSync,
  mkdirSync,
  writeFileSync,
  readFileSync,
  rmSync,
} from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { execFileSync } from "node:child_process";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { WorkspaceProvider } from "../src/app/Workspace";
import { App } from "../src/app/App";
import { demoBriefs, demoSessions } from "../src/data/mock";

it("imports backend-shaped files through Python and automatically renders a new brief on Home", async () => {
  const temp = mkdtempSync(path.join(tmpdir(), "momentum-integration-"));
  onTestFinished(() => rmSync(temp, { recursive: true, force: true }));
  const reports = path.join(temp, "reports"),
    output = path.join(temp, "output");
  mkdirSync(path.join(reports, "session"), { recursive: true });
  const board = {
    question: "Temporary integration research",
    tasks: demoSessions[0].tasks,
  };
  writeFileSync(
    path.join(reports, "session/task_board.json"),
    JSON.stringify(board),
  );
  const sync = () =>
    execFileSync(
      "python3",
      [
        "scripts/artifact_watch.py",
        "--once",
        "--project-root",
        temp,
        "--reports-root",
        reports,
        "--output-root",
        output,
      ],
      { cwd: process.cwd() },
    );
  sync();
  expect(
    JSON.parse(readFileSync(path.join(output, "sync-status.json"), "utf8"))
      .state,
  ).toBe("ready");
  expect(
    JSON.parse(readFileSync(path.join(output, "index.json"), "utf8")).sessions,
  ).toHaveLength(1);
  sessionStorage.setItem("momentum-source", "artifact");
  vi.stubGlobal("fetch", async (url: string) => {
    try {
      return {
        ok: true,
        json: async () =>
          JSON.parse(
            readFileSync(
              path.join(output, url.replace("/artifacts/", "")),
              "utf8",
            ),
          ),
      };
    } catch {
      return { ok: false };
    }
  });
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const view = render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <WorkspaceProvider>
          <App />
        </WorkspaceProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  try {
    await screen.findByText("No daily brief available");
    await screen.findAllByText("Temporary integration research");
    mkdirSync(path.join(reports, "brief_test"));
    writeFileSync(
      path.join(reports, "brief_test/brief.json"),
      JSON.stringify({ ...demoBriefs[0], requested_as_of: "2026-05-29" }),
    );
    sync();
    await waitFor(
      () =>
        expect(
          screen.getByRole("link", { name: "Read daily brief" }),
        ).toHaveAttribute("href", "/briefs/brief_test"),
      { timeout: 5500 },
    );
    expect(
      JSON.parse(
        readFileSync(path.join(reports, "session/task_board.json"), "utf8"),
      ),
    ).toEqual(board);
  } finally {
    view.unmount();
    client.clear();
    vi.unstubAllGlobals();
    rmSync(temp, { recursive: true, force: true });
  }
}, 10000);
