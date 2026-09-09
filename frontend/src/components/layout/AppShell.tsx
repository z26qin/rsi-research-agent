import { useEffect, useState, type ReactNode } from "react";
import { NavLink, useNavigate, useLocation } from "react-router-dom";
import {
  Home,
  Search,
  BookOpen,
  Layers,
  Activity,
  Bot,
  Library,
  ArrowRight,
  Bell,
  ChevronDown,
  Plus,
  Menu,
  RefreshCw,
  PanelRight,
  Command,
  SlidersHorizontal,
} from "lucide-react";
import { useWorkspace } from "../../app/Workspace";
import { Modal, ScopeMark, Badge } from "../shared/UI";
const nav = [
  ["/", "Home", Home],
  ["/research", "Research", Search],
  ["/runs", "Runs & schedule", Activity],
  ["/sessions", "Sessions", Layers],
  ["/briefs", "Daily Briefs", Activity],
  ["/gaps", "Gaps", SlidersHorizontal],
  ["/agents", "Agents", Bot],
  ["/library", "Library", Library],
] as const;
export function AppShell({
  children,
  rail,
}: {
  children: ReactNode;
  rail?: ReactNode;
}) {
  const w = useWorkspace(),
    navigate = useNavigate(),
    location = useLocation();
  const [mode, setMode] = useState("Research"),
    [searchOpen, setSearchOpen] = useState(false),
    [query, setQuery] = useState(""),
    [menu, setMenu] = useState(false),
    [inspector, setInspector] = useState(false),
    [account, setAccount] = useState(false),
    [notifications, setNotifications] = useState(false);
  useEffect(() => {
    setMenu(false);
    setInspector(false);
  }, [location.pathname]);
  useEffect(() => {
    let pending = 0;
    const key = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setSearchOpen((o) => !o);
        return;
      }
      if (
        (e.target as HTMLElement)?.closest(
          'input,textarea,select,[contenteditable="true"]',
        )
      )
        return;
      if (Date.now() - pending < 900) {
        const path = (
          { h: "/", r: "/research", s: "/sessions" } as Record<string, string>
        )[e.key];
        if (path) {
          navigate(path);
          pending = 0;
          return;
        }
      }
      pending = e.key === "g" ? Date.now() : 0;
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [navigate]);
  const sidebar = (
    <>
      <div className="brand">
        <span>MOMENTUM</span>
        <p>Ideas. Evidence. Alpha.</p>
      </div>
      <nav aria-label="Main navigation">
        {nav.map(([to, label, Icon]) => (
          <NavLink key={to} to={to} end={to === "/"}>
            <Icon size={18} />
            {label}
          </NavLink>
        ))}
      </nav>
      <div className="coverage">
        <p className="eyebrow">RESEARCH FOCUS</p>
        {["NBIS", "Momentum", "AI Infra", "Market regime", "Positioning"].map(
          (s, i) => (
            <button
              key={s}
              onClick={() => navigate("/sessions?q=" + encodeURIComponent(s))}
            >
              <span className={"dot " + (!i ? "active" : "")} />
              {s}
            </button>
          ),
        )}
        <button className="muted" onClick={() => navigate("/research")}>
          <Plus size={14} /> New research
        </button>
      </div>
      <div className="sidebar-quote">
        A better
        <br />
        research process
        <br />
        compounds.
        <br />
        <span>—</span>
      </div>
    </>
  );
  const results = w.sessions.filter((s) =>
    (s.question + " " + s.title + " " + s.scope)
      .toLowerCase()
      .includes(query.toLowerCase()),
  );
  const evidences = w.sessions
    .flatMap((s) => s.evidence.map((e) => ({ s, e })))
    .filter(
      ({ e }) =>
        query.length > 1 && e.claim.toLowerCase().includes(query.toLowerCase()),
    )
    .slice(0, 8);
  const openResult = (path: string) => {
    navigate(path);
    setSearchOpen(false);
    setQuery("");
  };
  return (
    <div className="app-shell">
      <aside className="sidebar">{sidebar}</aside>
      <header className="topbar">
        <button
          className="icon-button mobile-menu"
          aria-label="Open navigation"
          onClick={() => setMenu(true)}
        >
          <Menu size={20} />
        </button>
        <button className="search-trigger" onClick={() => setSearchOpen(true)}>
          <Search size={18} />
          <span>
            {mode === "Ask"
              ? "Ask a quick question…"
              : mode === "Monitor"
                ? "Explore a monitoring scenario…"
                : "Research a company, theme, or market…"}
          </span>
          <kbd>⌘ K</kbd>
        </button>
        <div className="mode-selector" aria-label="Research mode">
          {["Ask", "Research", "Monitor"].map((m) => (
            <button
              key={m}
              className={m === mode ? "selected" : ""}
              onClick={() => setMode(m)}
            >
              {m}
            </button>
          ))}
        </div>
        <button
          className="icon-button notification-button"
          aria-label="Notifications"
          onClick={() => setNotifications(true)}
        >
          <Bell size={19} />
        </button>
        <button className="account-button" onClick={() => setAccount(true)}>
          <span className="avatar">A</span>
          <span>Aaron</span>
          <ChevronDown size={13} />
        </button>
      </header>
      <div className="workspace-body">
        <main id="main-content">{children}</main>
        {rail && (
          <aside className="context-rail" aria-label="Research inspector">
            {rail}
          </aside>
        )}
      </div>
      <button
        className="rail-toggle"
        onClick={() => setInspector(true)}
        aria-label="Open research inspector"
      >
        <PanelRight size={18} /> Inspector
      </button>
      <div className="source-footer">
        <span className={"dot " + (w.source === "demo" ? "" : "active")} />
        <button onClick={() => setAccount(true)}>
          {w.source === "demo" ? "Demo workspace" : "Local snapshot"}
        </button>
      </div>
      <Modal
        open={searchOpen}
        onOpenChange={setSearchOpen}
        title="Find your next insight"
      >
        <div className="command-search">
          <Search size={18} />
          <input
            autoFocus
            aria-label="Search research"
            placeholder="Search questions, evidence or research…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
        <div className="command-results">
          <p className="eyebrow">RESEARCH SESSIONS</p>
          {results.map((s) => (
            <button
              key={s.id}
              onClick={() =>
                openResult("/sessions/" + encodeURIComponent(s.id))
              }
            >
              <ScopeMark scope={s.scope} small />
              <span>{s.question}</span>
              <ArrowRight size={14} />
            </button>
          ))}
          {evidences.map(({ s, e }) => (
            <button
              key={s.id + e.taskId + e.id}
              onClick={() =>
                openResult(
                  "/sessions/" +
                    encodeURIComponent(s.id) +
                    "?tab=evidence&evidence=" +
                    encodeURIComponent(e.id) +
                    "&task=" +
                    encodeURIComponent(e.taskId),
                )
              }
            >
              <BookOpen size={16} />
              <span>{e.claim}</span>
              <Badge>Evidence</Badge>
            </button>
          ))}
          {w.briefs
            .filter(
              (b) =>
                query.length > 1 &&
                ("daily brief " + b.requested_as_of).includes(
                  query.toLowerCase(),
                ),
            )
            .map((b) => (
              <button
                key={b.id}
                onClick={() =>
                  openResult("/briefs/" + encodeURIComponent(b.id))
                }
              >
                <Activity size={16} />
                Daily brief · {b.requested_as_of}
              </button>
            ))}
          {!results.length && !evidences.length && (
            <p className="muted">No matching research. Try another phrase.</p>
          )}
          <button
            className="new-command"
            onClick={() =>
              openResult(
                "/research?intent=" +
                  mode.toLowerCase() +
                  "&q=" +
                  encodeURIComponent(query),
              )
            }
          >
            <Plus size={16} /> Start a {mode.toLowerCase()} demo
            <ArrowRight size={14} />
          </button>
        </div>
        <div className="command-hint">
          <Command size={12} /> K to open · Tab to select · Enter to navigate
        </div>
      </Modal>
      <Modal
        open={account}
        onOpenChange={setAccount}
        title="Workspace settings"
      >
        <p className="muted">
          Choose the research collection you want to explore.
        </p>
        <div className="source-options">
          {(["demo", "artifact"] as const).map((s) => (
            <button
              key={s}
              className={w.source === s ? "chosen" : ""}
              onClick={() => {
                w.setSource(s);
                setAccount(false);
              }}
            >
              <strong>
                {s === "demo" ? "Demo workspace" : "Local research artifacts"}
              </strong>
              <span>
                {s === "demo"
                  ? "Illustrative research and interactive agent scenarios."
                  : "Read-only snapshots of the existing research backend."}
              </span>
            </button>
          ))}
        </div>
        <button
          className="button"
          onClick={() => {
            w.refresh();
            setAccount(false);
          }}
        >
          <RefreshCw size={14} /> Refresh snapshot
        </button>
      </Modal>
      <Modal
        open={notifications}
        onOpenChange={setNotifications}
        title="Research notifications"
      >
        <p className="muted">Notifications reflect the selected collection.</p>
        {w.sessions.slice(0, 3).map((s) => (
          <button
            className="notification-row"
            key={s.id}
            onClick={() => {
              navigate("/sessions/" + s.id);
              setNotifications(false);
            }}
          >
            <ScopeMark scope={s.scope} />
            <span>
              {s.title}
              <small>
                {s.verification?.overall_status.replaceAll("_", " ") ??
                  "Not reviewed"}
              </small>
            </span>
            <ArrowRight size={14} />
          </button>
        ))}
      </Modal>
      <Modal open={menu} onOpenChange={setMenu} title="Momentum">
        <div className="mobile-nav">{sidebar}</div>
      </Modal>
      <Modal
        open={inspector}
        onOpenChange={setInspector}
        title="Research inspector"
      >
        {rail}
      </Modal>
    </div>
  );
}
