import { useEffect, useState } from "react";
import { useNavigate, useSearchParams, Link } from "react-router-dom";
import {
  ArrowRight,
  Play,
  Pause,
  RotateCcw,
  Search,
  Check,
} from "lucide-react";
import { AppShell } from "../components/layout/AppShell";
import { AgentPulse } from "../components/agents/AgentPulse";
import { Badge } from "../components/shared/UI";
import { useWorkspace } from "../app/Workspace";
import { demoSessions } from "../data/mock";
import { advanceDemo, stages } from "../data/demo";
import type { Session } from "../types";
export function Research() {
  const w = useWorkspace(),
    [params] = useSearchParams(),
    [question, setQuestion] = useState(params.get("q") ?? ""),
    [scenario, setScenario] = useState(
      params.get("intent") === "monitor" ? 1 : 0,
    ),
    [mode, setMode] = useState(
      params.get("intent") === "ask" ? "single" : "team",
    ),
    [count, setCount] = useState(3),
    [focus, setFocus] = useState("Balanced research");
  const [error, setError] = useState("");
  useEffect(() => {
    if (!w.demo || w.demo.paused || w.demo.stage >= 5) return;
    const timer = setTimeout(() => w.setDemo(advanceDemo(w.demo!)), 3000);
    return () => clearTimeout(timer);
  }, [w.demo]);
  function start() {
    if (!question.trim()) {
      setError("Add a research question to begin.");
      return;
    }
    setError("");
    const original = structuredClone(demoSessions[scenario]);
    const max = mode === "single" ? 1 : count;
    const tasks = Array.from({ length: max }, (_, i) => ({
      ...original.tasks[i % original.tasks.length],
      id: "demo-run-task-" + i,
      status: "PENDING" as const,
    }));
    // Demo evidence stays associated with the planned tasks that produced it.
    const mapped = original.reports.slice(0, max).map((r, i) => ({
      ...r,
      task_id: tasks[i].id,
      findings: r.findings.map((e) => ({ ...e, agent_id: tasks[i].id })),
    }));
    const template: Session = {
      ...original,
      id: "demo-run",
      question: question.trim(),
      title: original.title,
      tasks,
      reports: mapped,
      evidence: mapped.flatMap((r) =>
        r.findings.map((e) => ({ ...e, taskId: r.task_id })),
      ),
      verification: original.verification
        ? {
            ...original.verification,
            verdicts: original.verification.verdicts
              .slice(0, max)
              .map((v, i) => ({ ...v, task_id: tasks[i].id })),
            gaps: [],
          }
        : null,
      traces: original.traces.map((t) => ({ ...t, agent_id: tasks[0].id })),
      synthesis: original.synthesis
        ? {
            ...original.synthesis,
            question: question.trim(),
            executive_summary:
              "DEMO SCENARIO — " + original.synthesis.executive_summary,
          }
        : null,
    };
    w.setSource("demo");
    w.setDemo({
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
        tasks: tasks.map((t) => ({
          ...t,
          tool_calls: 0,
          tokens_used: 0,
          started_at: null,
          completed_at: null,
        })),
      },
    });
  }
  return (
    <AppShell rail={<AgentPulse session={w.demo?.session} />}>
      <div className="notice">This page is a browser-only Demo. <Link className="text-link" to={"/runs?q=" + encodeURIComponent(question)}>Run real backend research →</Link></div>
      <div className="page-title">
        <span className="eyebrow">A QUESTION WORTH ASKING</span>
        <h1>Make room for a better answer.</h1>
        <p>Frame the question. Follow the evidence. See the work.</p>
      </div>
      <div className="research-composer">
        <div className="rail-heading">
          <h2>Start a research session</h2>
          <Badge>DEMO</Badge>
        </div>
        <label htmlFor="question">What would you like to investigate?</label>
        <textarea
          id="question"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="Is recent weakness a momentum unwind, or a fundamental repricing?"
          rows={4}
        />
        <div className="composer-options">
          <label>
            Research mode
            <select value={mode} onChange={(e) => setMode(e.target.value)}>
              <option value="team">Analyst team</option>
              <option value="single">Single analyst</option>
            </select>
          </label>
          <label>
            Analysts
            <select
              value={mode === "single" ? 1 : count}
              disabled={mode === "single"}
              onChange={(e) => setCount(Number(e.target.value))}
            >
              {[1, 2, 3, 4].map((n) => (
                <option key={n}>{n}</option>
              ))}
            </select>
          </label>
          <label>
            Focus
            <select value={focus} onChange={(e) => setFocus(e.target.value)}>
              {["Balanced research", "Counter-evidence", "Source quality"].map(
                (f) => (
                  <option key={f}>{f}</option>
                ),
              )}
            </select>
          </label>
        </div>
        <p className="eyebrow">CHOOSE AN ILLUSTRATIVE SCENARIO</p>
        <div className="scenario-options">
          {demoSessions.map((s, i) => (
            <button
              key={s.id}
              className={i === scenario ? "chosen" : ""}
              onClick={() => {
                setScenario(i);
                if (!question) setQuestion(s.question);
              }}
            >
              <span>{s.scope}</span>
              <small>{s.question}</small>
            </button>
          ))}
        </div>
        <div className="example-plan">
          <h4>Example plan · {focus}</h4>
          <p>
            {focus === "Counter-evidence"
              ? "Prioritize contradictory sources and test the strongest objection."
              : focus === "Source quality"
                ? "Prioritize primary sources, dates and independent corroboration."
                : "Explore the thesis, challenge the assumptions and verify the evidence."}
          </p>
          <span>Research → Evidence → Verification → Synthesis</span>
        </div>
        {error && (
          <p role="alert" className="red">
            {error}
          </p>
        )}
        <div className="composer-footer">
          <span>
            No live model calls. Results come from the selected scenario.
          </span>
          <button className="button dark" onClick={start}>
            Start demo <ArrowRight size={15} />
          </button>
        </div>
      </div>
      {w.demo && (
        <section className="demo-run">
          <div className="rail-heading">
            <div>
              <span className="eyebrow">DEMO RUN</span>
              <h2 aria-live="polite">{stages[w.demo.stage]}</h2>
            </div>
            <Badge>
              {w.demo.paused
                ? "Paused"
                : w.demo.stage === 5
                  ? "Complete"
                  : "Playing"}
            </Badge>
          </div>
          <div className="demo-stages">
            {stages.map((s, i) => (
              <div key={s} className={i <= w.demo!.stage ? "done" : ""}>
                <span>{i < w.demo!.stage ? <Check size={13} /> : i + 1}</span>
                <small>{s}</small>
              </div>
            ))}
          </div>
          <div className="diff-actions">
            <button
              className="button"
              disabled={w.demo.stage === 5}
              onClick={() => w.setDemo({ ...w.demo!, paused: !w.demo!.paused })}
            >
              {w.demo.paused ? <Play size={14} /> : <Pause size={14} />}{" "}
              {w.demo.paused ? "Continue" : "Pause"}
            </button>
            <button className="button" onClick={() => w.setDemo(null)}>
              <RotateCcw size={14} />
              Reset
            </button>
            <Link className="button dark" to="/sessions/demo-run">
              Open workspace <ArrowRight size={14} />
            </Link>
          </div>
          <p className="diff-note">
            The demo advances while this page is open. Returning resumes from
            the saved step.
          </p>
        </section>
      )}
    </AppShell>
  );
}
