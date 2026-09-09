import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { WorkspaceProvider } from "../src/app/Workspace";
import { App } from "../src/app/App";
import { advanceDemo, restoreDemo } from "../src/data/demo";
import { demoSessions } from "../src/data/mock";
import { normalizeSession } from "../src/data/normalize";

function mount(route = "/") {
  return render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter initialEntries={[route]}>
        <WorkspaceProvider>
          <App />
        </WorkspaceProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}
describe("interactive research workspace", () => {
  afterEach(() => vi.unstubAllGlobals());
  it("keeps independent bookmarks and ignores corrupt review storage", async () => {
    sessionStorage.setItem("momentum-review-v1", "null");
    const user = userEvent.setup();
    mount("/sessions/demo-nbis?tab=evidence");
    const saves = await screen.findAllByRole("button", {
      name: /Save evidence:/,
    });
    await user.click(saves[0]);
    await user.click(saves[1]);
    expect(
      Object.values(JSON.parse(sessionStorage.getItem("momentum-review-v1")!)),
    ).toEqual(["saved", "saved"]);
  });
  it("uses the command intent to preselect a relevant Demo scenario", async () => {
    mount("/research?intent=monitor");
    expect(
      screen.getByRole("button", { name: /Is momentum fragility/ }),
    ).toHaveClass("chosen");
  });
  it("reviews a thesis, follows verification and filters evidence", async () => {
    const user = userEvent.setup();
    mount("/sessions/demo-nbis");
    await user.click(await screen.findByRole("button", { name: "Reject" }));
    expect(screen.getByRole("status")).toHaveTextContent(
      "Verification is unchanged",
    );
    await user.click(screen.getByRole("button", { name: "Accept" }));
    await user.click(screen.getByRole("button", { name: "Investigate" }));
    await user.click(screen.getByRole("tab", { name: "Verification" }));
    expect(
      screen.getByRole("heading", { name: "Independent verification" }),
    ).toBeInTheDocument();
    await user.click(
      screen.getByRole("button", { name: /Inspect referenced evidence/ }),
    );
    await user.selectOptions(screen.getByLabelText("All verdicts"), "rejected");
    expect(
      screen.getByRole("heading", {
        name: "No evidence matches these filters",
      }),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Clear filters" }));
    await user.selectOptions(
      screen.getByLabelText("All stances"),
      "contradicting",
    );
    expect(
      screen.getAllByRole("button", { name: /Save evidence/ }),
    ).toHaveLength(1);
  });
  it("opens recorded trace and copies the observation", async () => {
    const user = userEvent.setup();
    mount("/sessions/demo-nbis?tab=trace");
    await user.click(await screen.findByText("web_search", { exact: true }));
    await user.click(screen.getByRole("button", { name: "Copy observation" }));
    expect(screen.getByRole("button", { name: "Copied" })).toBeInTheDocument();
  });
  it("filters sessions and exposes empty matches", async () => {
    const user = userEvent.setup();
    mount("/sessions");
    const input = await screen.findByRole("textbox");
    await user.type(input, "zzzz-no-research");
    expect(
      screen.getByRole("heading", { name: "No matching sessions" }),
    ).toBeInTheDocument();
    await user.clear(input);
    await user.type(input, "NBIS");
    expect(
      screen.getByRole("link", { name: "Open NBIS session" }),
    ).toBeInTheDocument();
  });
  it("reads brief metadata and source audit", async () => {
    const user = userEvent.setup();
    mount("/briefs");
    await user.click(
      await screen.findByRole("link", { name: /Momentum daily brief/ }),
    );
    expect(
      screen.getAllByText(/Monitoring score · not a probability/),
    ).toHaveLength(3);
    await user.click(screen.getByText("Delivery and input audit"));
    expect(
      screen.getByText(/engine_fingerprint|demo-fingerprint|fingerprint/),
    ).toBeInTheDocument();
  });
  it("filters gap occurrences without merging them", async () => {
    const user = userEvent.setup();
    mount("/gaps");
    await waitFor(() =>
      expect(screen.getAllByText(/Occurrence created/)).toHaveLength(3),
    );
    await user.selectOptions(screen.getByLabelText("Gap status"), "CLOSED");
    expect(screen.getAllByText(/Occurrence created/)).toHaveLength(1);
    expect(
      screen.getByText(/detailed closure reason was not recorded/),
    ).toBeInTheDocument();
    await user.selectOptions(
      screen.getByLabelText("Gap capability"),
      "engine_freshness",
    );
    expect(
      screen.getByRole("heading", { name: "No matching gaps" }),
    ).toBeInTheDocument();
  });
  it("opens a profile's explicit tools and searches the library", async () => {
    const user = userEvent.setup();
    mount("/agents");
    await user.click(
      await screen.findByRole("button", { name: /Momentum analyst/ }),
    );
    expect(
      screen.getByRole("heading", { name: "Authorized tools" }),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("link", { name: "Library" }));
    await user.selectOptions(screen.getByLabelText("Library type"), "evidence");
    await user.type(screen.getByLabelText("Search library"), "zzzz");
    expect(
      screen.getByRole("heading", { name: "No matching research" }),
    ).toBeInTheDocument();
  });
  it("surfaces importer diagnostics, persists source, and keeps failures explicit", async () => {
    vi.stubGlobal("fetch", async () => ({
      ok: true,
      json: async () => ({
        schemaVersion: 1,
        snapshotId: "s",
        snapshotAt: "2026-01-01",
        availability: "partial",
        sessions: [],
        briefs: [],
        gaps: [],
        profiles: [],
        diagnostics: [
          {
            file: "reports",
            code: "source_changed",
            message: "Previous snapshot retained",
          },
        ],
      }),
    }));
    const user = userEvent.setup();
    mount();
    await user.click(screen.getByRole("button", { name: "Demo workspace" }));
    await user.click(
      screen.getByRole("button", { name: /Local research artifacts/ }),
    );
    expect(sessionStorage.getItem("momentum-source")).toBe("artifact");
    expect(
      await screen.findByText(/Previous snapshot retained/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/No local research sessions found/),
    ).toBeInTheDocument();
  });
  it("does not call import time the research update time", () => {
    const s = normalizeSession({
      id: "x",
      snapshotAt: "2026-09-08T00:00:00Z",
      board: { question: "Q", tasks: [] },
    });
    expect(s.updatedAt).toBeNull();
  });
  it("validates restored demo states and reveals outputs in order", () => {
    expect(
      restoreDemo({ session: { source: "demo", tasks: [] }, stage: 200 }),
    ).toBeNull();
    const template = structuredClone(demoSessions[0]);
    let state = {
      stage: 0,
      paused: false,
      template,
      session: {
        ...template,
        reports: [],
        evidence: [],
        verification: null,
        synthesis: null,
        traces: [],
      },
    };
    const one = advanceDemo(state);
    expect(one.session.evidence).toHaveLength(0);
    expect(one.session.synthesis).toBeNull();
    let final = one;
    for (let i = 0; i < 5; i++) final = advanceDemo(final);
    expect(final.session.synthesis).toEqual(template.synthesis);
    expect(restoreDemo(final)?.stage).toBe(5);
  });
  it("validates a question and starts with no completed outputs", async () => {
    const user = userEvent.setup();
    mount("/research");
    await user.click(screen.getByRole("button", { name: "Start demo" }));
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Add a research question",
    );
    await user.type(
      screen.getByLabelText("What would you like to investigate?"),
      "Why is risk changing?",
    );
    await user.click(screen.getByRole("button", { name: "Start demo" }));
    expect(
      screen.getByRole("heading", { name: "Preparing research" }),
    ).toBeInTheDocument();
    const saved = JSON.parse(sessionStorage.getItem("momentum-demo-v1")!);
    expect(saved.session.synthesis).toBeNull();
    expect(saved.session.evidence).toHaveLength(0);
    await user.click(screen.getByRole("button", { name: "Pause" }));
    expect(JSON.parse(sessionStorage.getItem("momentum-demo-v1")!).paused).toBe(
      true,
    );
  });
  it("opens search by keyboard and restores focus on Escape", async () => {
    const user = userEvent.setup();
    mount();
    const trigger = await screen.findByRole("button", {
      name: /Research a company/,
    });
    trigger.focus();
    await user.keyboard("{Control>}k{/Control}");
    const input = screen.getByRole("textbox", { name: "Search research" });
    await user.type(input, "capacity");
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    await user.keyboard("{Escape}");
    await waitFor(() => expect(trigger).toHaveFocus());
  });
  it("renders evidence and preserves verifier status when saving locally", async () => {
    const user = userEvent.setup();
    mount("/sessions/demo-nbis?tab=evidence");
    const save = (
      await screen.findAllByRole("button", { name: /Save evidence:/ })
    )[0];
    await user.click(save);
    expect(screen.getAllByText("verified").length).toBeGreaterThan(0);
    expect(demoSessions[0].verification?.verdicts[0].status).toBe("verified");
    await user.click(
      screen.getAllByRole("button", { name: "Inspect evidence" })[0],
    );
    expect(screen.getByText("EVIDENCE INSPECTOR")).toBeInTheDocument();
  });
  it.each([
    ["/briefs", "Daily briefs"],
    ["/gaps", "The questions still open."],
    ["/agents", "A small team. Different perspectives."],
    ["/library", "Your research, connected."],
  ])("opens %s", async (route) => {
    mount(route);
    await waitFor(() =>
      expect(screen.getByRole("main")).not.toBeEmptyDOMElement(),
    );
    expect(screen.queryByText("Page not found")).not.toBeInTheDocument();
  });
});
