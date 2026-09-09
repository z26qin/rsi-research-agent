import { it, expect } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { LatestBrief } from "../src/components/dashboard/LatestBrief";
import { RecordedFlow } from "../src/components/agents/RecordedFlow";
import { demoBriefs, demoSessions } from "../src/data/mock";

it("keeps the latest available brief visible without hiding a newer failed attempt", () => {
  const earlier = {
    ...demoBriefs[0],
    id: "earlier",
    requested_as_of: "2026-05-28",
  };
  const failed = {
    ...earlier,
    id: "failed",
    requested_as_of: "2026-05-29",
    status: "unavailable" as const,
    metrics: {},
  };
  render(
    <MemoryRouter>
      <LatestBrief briefs={[failed, earlier]} />
    </MemoryRouter>,
  );
  expect(
    screen.getByRole("link", { name: /Read daily brief/ }),
  ).toHaveAttribute("href", "/briefs/earlier");
  expect(screen.getByRole("link", { name: /Newer attempt/ })).toHaveAttribute(
    "href",
    "/briefs/failed",
  );
  expect(screen.getByText(/not a probability/)).toBeInTheDocument();
});

it("does not invent metrics when only unavailable briefs exist", () => {
  render(
    <MemoryRouter>
      <LatestBrief
        briefs={[{ ...demoBriefs[0], status: "unavailable", metrics: {} }]}
      />
    </MemoryRouter>,
  );
  expect(screen.getByText(/Assessment withheld/)).toBeInTheDocument();
  expect(screen.queryByText(/Monitoring severity/)).not.toBeInTheDocument();
});

it("shows empty brief state without offering a backend launch", () => {
  render(
    <MemoryRouter>
      <LatestBrief briefs={[]} />
    </MemoryRouter>,
  );
  expect(screen.getByText("No daily brief available")).toBeInTheDocument();
  expect(screen.queryByRole("button")).not.toBeInTheDocument();
});

it("shows recorded task kinds, blocked causes and separate verification outcome", () => {
  const base = demoSessions[0];
  const task = {
    ...base.tasks[0],
    id: "blocked",
    kind: "replan" as const,
    status: "BLOCKED" as const,
    error: "Input coverage missing",
  };
  render(
    <MemoryRouter>
      <RecordedFlow
        session={{
          ...base,
          tasks: [task],
          synthesis: null,
          verification: null,
        }}
      />
    </MemoryRouter>,
  );
  const flow = screen.getByRole("region", { name: "Recorded agent flow" });
  expect(within(flow).getByText("Replan")).toBeInTheDocument();
  expect(within(flow).getByText("Input coverage missing")).toBeInTheDocument();
  expect(within(flow).getByText(/No verifier artifact/)).toBeInTheDocument();
  expect(within(flow).getByText(/not process liveness/)).toBeInTheDocument();
  expect(
    within(flow).getByRole("link", { name: /Inspect task/ }),
  ).toHaveAttribute("href", "/sessions/" + base.id + "?task=blocked");
});
