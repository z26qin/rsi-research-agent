import { Routes, Route, Link } from "react-router-dom";
import { Dashboard, Sessions } from "../pages/Dashboard";
import { SessionWorkspace } from "../pages/SessionWorkspace";
import { Research } from "../pages/Research";
import { Runs } from "../pages/Runs";
import { DailyBriefs, Gaps, Agents, Library } from "../pages/Supporting";
import { AppShell } from "../components/layout/AppShell";
import { Empty } from "../components/shared/UI";
export function App() {
  return (
    <Routes>
      <Route path="/" element={<Dashboard />} />
      <Route path="/sessions" element={<Sessions />} />
      <Route path="/sessions/:sessionId" element={<SessionWorkspace />} />
      <Route path="/research" element={<Research />} />
      <Route path="/runs" element={<Runs />} />
      <Route path="/briefs" element={<DailyBriefs />} />
      <Route path="/briefs/:briefId" element={<DailyBriefs />} />
      <Route path="/gaps" element={<Gaps />} />
      <Route path="/agents" element={<Agents />} />
      <Route path="/library" element={<Library />} />
      <Route
        path="*"
        element={
          <AppShell>
            <Empty title="Page not found">
              <Link to="/">Return home</Link>
            </Empty>
          </AppShell>
        }
      />
    </Routes>
  );
}
