import { useEffect, useRef, useState } from "react";
import {
  Activity,
  ArrowDownLeft,
  ArrowUpRight,
  BookOpen,
  Box,
  ChevronRight,
  CircleHelp,
  Code2,
  Compass,
  Crosshair,
  Expand,
  FlaskConical,
  Home,
  Layers3,
  Leaf,
  MessageCircle,
  Moon,
  Pause,
  Play,
  Plus,
  Radio,
  RotateCcw,
  ShieldCheck,
  Sun,
  Users,
  Workflow,
  X,
  Minus,
} from "lucide-react";
import { createSocietyScene } from "./scene";
import {
  departmentOf,
  departments,
  prettyTool,
  statusLabel,
  useSociety,
} from "./model";
import "./society.css";

const deptIcons = {
  headquarters: Home,
  research: FlaskConical,
  engineering: Code2,
  communications: MessageCircle,
  knowledge: BookOpen,
  operations: Workflow,
};
const activeStatuses = new Set(["working", "thinking", "waiting"]);
const avatarColors = [
  "#ca8264",
  "#608e82",
  "#729eaf",
  "#dab469",
  "#9496b7",
  "#c69d94",
];
function avatarColor(id: string) {
  let hash = 0;
  for (const char of id) hash = ((hash << 5) - hash + char.charCodeAt(0)) | 0;
  return avatarColors[Math.abs(hash) % avatarColors.length];
}
function timeAgo(timestamp: number) {
  const seconds = Math.max(0, Math.floor(Date.now() / 1000 - timestamp));
  return seconds < 60
    ? "now"
    : seconds < 3600
      ? `${Math.floor(seconds / 60)}m`
      : `${Math.floor(seconds / 3600)}h`;
}

export default function Society() {
  const [demo, setDemo] = useState(
    new URLSearchParams(location.search).get("demo") === "1",
  );
  const { snapshot, connection } = useSociety(demo);
  const [tab, setTab] = useState<"residents" | "activity">("residents");
  const [selected, setSelected] = useState<string | null>(null);
  const [department, setDepartment] = useState<string | null>(null);
  const [night, setNight] = useState(false);
  const [paused, setPaused] = useState(false);
  const [labels, setLabels] = useState(true);
  const [help, setHelp] = useState(false);
  const [sceneError, setSceneError] = useState(false);
  const [clock, setClock] = useState(new Date());
  const host = useRef<HTMLDivElement>(null);
  const scene = useRef<ReturnType<typeof createSocietyScene> | null>(null);
  const helpButton = useRef<HTMLButtonElement>(null);
  const helpClose = useRef<HTMLButtonElement>(null);
  const seenEvents = useRef(new Set<string>());
  const eventEpoch = useRef<number>(0);
  useEffect(() => {
    document.title = "Agent Society · EloPhanto";
    const previous = document.documentElement.style.colorScheme;
    document.documentElement.style.colorScheme = "light";
    const timer = setInterval(() => setClock(new Date()), 1000);
    if (host.current) {
      try {
        scene.current = createSocietyScene(host.current, {
          onSelectAgent: (id) => {
            setSelected(id);
            setTab("residents");
          },
          onSelectDepartment: setDepartment,
        });
      } catch (error) {
        console.error("Society renderer:", error);
        setSceneError(true);
      }
    }
    return () => {
      scene.current?.dispose();
      scene.current = null;
      clearInterval(timer);
      document.documentElement.style.colorScheme = previous;
    };
  }, []);
  useEffect(() => {
    scene.current?.setAgents(snapshot.agents);
  }, [snapshot.agents]);
  useEffect(() => {
    if (eventEpoch.current !== snapshot.started_at) {
      seenEvents.current.clear();
      eventEpoch.current = snapshot.started_at;
    }
    const fresh = [...snapshot.events].sort(
      (a, b) => a.timestamp - b.timestamp,
    );
    for (const event of fresh) {
      const id = String(event.id);
      if (
        !seenEvents.current.has(id) &&
        event.kind === "tool_started" &&
        event.timestamp > Date.now() / 1000 - 15
      ) {
        scene.current?.visitDepartment(event.agent_id, event.department);
      }
    }
    seenEvents.current = new Set(
      snapshot.events.map((event) => String(event.id)),
    );
  }, [snapshot.events, snapshot.started_at]);
  useEffect(() => {
    scene.current?.setSelectedAgent(selected);
  }, [selected]);
  useEffect(() => {
    scene.current?.focusDepartment(department);
  }, [department]);
  useEffect(() => {
    scene.current?.setNight(night);
  }, [night]);
  useEffect(() => {
    scene.current?.setPaused(paused || connection === "offline");
  }, [paused, connection]);
  useEffect(() => {
    scene.current?.setLabels(labels);
  }, [labels]);
  useEffect(() => {
    if (help) helpClose.current?.focus();
  }, [help]);
  useEffect(() => {
    if (selected && !snapshot.agents.some((a) => a.id === selected))
      setSelected(null);
  }, [selected, snapshot.agents]);
  const closeHelp = () => {
    setHelp(false);
    helpButton.current?.focus();
  };
  const current = snapshot.agents.find((a) => a.id === selected);
  const visibleResidents = department
    ? snapshot.agents.filter((a) => a.department === department)
    : snapshot.agents;
  const focusedDepartment = department ? departmentOf(department) : null;
  const events = [...snapshot.events]
    .sort((a, b) => b.timestamp - a.timestamp)
    .slice(0, 30);
  const live = connection === "live";
  const reset = () => {
    setDepartment(null);
    setSelected(null);
    scene.current?.resetView();
  };

  return (
    <div
      className={`society-app ${night ? "society-night" : ""} ${snapshot.agents.length > 6 ? "society-many-residents" : ""}`}
    >
      <a className="society-skip" href="#society-residents">
        Skip to agent activity
      </a>
      <header className="society-header">
        <a
          className="society-brand"
          href="/society/"
          aria-label="Agent Society home"
        >
          <span className="society-brand-icon">
            <Box size={22} strokeWidth={1.7} />
          </span>
          <span>
            EloPhanto<span className="society-brand-divider">/</span>
            <strong>Society</strong>
          </span>
          <span className="society-beta">LAB</span>
        </a>
        <div className="society-header-center">
          <span className="society-live-dot" /> A place for every curious mind
        </div>
        <div className="society-header-actions">
          <span className={`society-connection ${connection}`} role="status">
            <span />
            {demo
              ? "Demo campus"
              : live
                ? "Connected to CLI"
                : connection === "connecting"
                  ? "Connecting"
                  : "Reconnecting"}
          </span>
          <button
            className="society-icon-button"
            ref={helpButton}
            aria-label="About the society"
            onClick={() => setHelp(true)}
          >
            <CircleHelp size={19} />
          </button>
        </div>
      </header>
      <main className="society-layout">
        <section
          className="society-world"
          aria-label="Interactive isometric agent campus"
        >
          <div className="society-world-heading">
            <div className="society-eyebrow">
              <span /> THE LIVING WORKSPACE{" "}
              <span className="society-edition">VOL. 01</span>
            </div>
            <h1>
              Your agents,
              <br />
              <em>in their element.</em>
            </h1>
            <p>Small footsteps. Big ideas. All happening here.</p>
            <div className="society-world-metrics">
              <span>
                <b>{snapshot.stats.total.toString().padStart(2, "0")}</b>{" "}
                residents
              </span>
              <i />
              <span>
                <b>{snapshot.stats.active.toString().padStart(2, "0")}</b> at
                work
              </span>
              <i />
              <span>
                <b>06</b> departments
              </span>
            </div>
          </div>
          <div className="society-world-badge">
            <Compass size={18} />
            <span>
              ELOPHANTO CAMPUS
              <small>
                {night ? "After hours" : "A little world of possibility"}
              </small>
            </span>
          </div>
          <div
            className="society-canvas"
            ref={host}
            aria-label="Drag to explore the campus, scroll to zoom, or select a department below"
          />
          {sceneError && (
            <div className="society-scene-error">
              <Box size={32} />
              <h2>The campus needs WebGL</h2>
              <p>
                Enable hardware acceleration in your browser to see the world.
                Live activity is still available alongside it.
              </p>
            </div>
          )}
          {!demo && connection !== "live" && (
            <div className="society-offline-notice">
              <Radio size={17} />
              <span>
                {connection === "connecting"
                  ? "Waiting for your CLI to arrive…"
                  : "Waiting for the agent connection. The campus will reconnect automatically."}
              </span>
              <button onClick={() => setDemo(true)}>
                Explore demo <ArrowUpRight size={14} />
              </button>
            </div>
          )}
          {demo && (
            <div className="society-demo-notice">
              <span>DEMO</span> A preview with simulated residents.
              <button
                onClick={() => {
                  setDemo(false);
                  reset();
                }}
              >
                Return to live <ArrowUpRight size={13} />
              </button>
            </div>
          )}
          <div className="society-world-bottom">
            <span className="society-explore-hint">
              <Crosshair size={14} /> Drag to explore <span>·</span> Scroll to
              get closer
            </span>
            <div
              className="society-view-controls"
              aria-label="Campus view controls"
            >
              <button
                aria-label={paused ? "Resume animation" : "Pause animation"}
                title={paused ? "Resume animation" : "Pause animation"}
                aria-pressed={paused}
                onClick={() => setPaused(!paused)}
              >
                {paused ? <Play size={16} /> : <Pause size={16} />}
              </button>
              <span />
              <button
                aria-label="Zoom out"
                onClick={() => scene.current?.zoom(-1)}
              >
                <Minus size={17} />
              </button>
              <button
                aria-label="Zoom in"
                onClick={() => scene.current?.zoom(1)}
              >
                <Plus size={17} />
              </button>
              <span />
              <button aria-label="Reset campus view" onClick={reset}>
                <RotateCcw size={16} />
              </button>
              <button
                aria-label="Toggle department labels"
                aria-pressed={labels}
                onClick={() => setLabels(!labels)}
              >
                <Layers3 size={17} />
              </button>
              <button
                aria-label={night ? "Switch to daylight" : "Switch to evening"}
                aria-pressed={night}
                onClick={() => setNight(!night)}
              >
                {night ? <Moon size={17} /> : <Sun size={18} />}
              </button>
              <button
                aria-label="Toggle fullscreen"
                onClick={() => {
                  if (document.fullscreenElement)
                    void document.exitFullscreen().catch(() => {});
                  else
                    void document.documentElement
                      .requestFullscreen?.()
                      .catch(() => {});
                }}
              >
                <Expand size={16} />
              </button>
            </div>
          </div>
        </section>
        <aside
          className="society-sidebar"
          id="society-residents"
          aria-label="Society activity"
        >
          <div className="society-sidebar-heading">
            <div>
              <span className="society-eyebrow">
                THE PEOPLE BEHIND THE PROGRESS
              </span>
              <h2>
                Campus pulse
                <span className="society-pulse-mark">
                  <Activity size={18} />
                </span>
              </h2>
            </div>
          </div>
          <div className="society-summary">
            <div>
              <span className="society-summary-icon">
                <Workflow size={18} />
              </span>
              <span>
                <b>{snapshot.stats.completed}</b>
                <small>tools completed</small>
              </span>
            </div>
            <div>
              <span
                className={`society-summary-icon ${snapshot.stats.errors ? "has-errors" : ""}`}
              >
                <Leaf size={18} />
              </span>
              <span>
                <b>{snapshot.stats.errors}</b>
                <small>tool errors</small>
              </span>
            </div>
          </div>
          <div
            className="society-tabs"
            role="tablist"
            aria-label="Campus information"
            onKeyDown={(event) => {
              if (
                ["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)
              ) {
                event.preventDefault();
                const next =
                  event.key === "Home"
                    ? "residents"
                    : event.key === "End"
                      ? "activity"
                      : tab === "residents"
                        ? "activity"
                        : "residents";
                setTab(next);
                document.getElementById(`${next}-tab`)?.focus();
              }
            }}
          >
            <button
              role="tab"
              id="residents-tab"
              tabIndex={tab === "residents" ? 0 : -1}
              aria-controls="residents-panel"
              aria-selected={tab === "residents"}
              onClick={() => setTab("residents")}
            >
              <Users size={15} /> Residents{" "}
              <span>{snapshot.agents.length}</span>
            </button>
            <button
              role="tab"
              id="activity-tab"
              tabIndex={tab === "activity" ? 0 : -1}
              aria-controls="activity-panel"
              aria-selected={tab === "activity"}
              onClick={() => setTab("activity")}
            >
              <Activity size={15} /> Activity
            </button>
          </div>
          {focusedDepartment && (
            <div className="society-filter">
              <span style={{ color: focusedDepartment.color }}>
                {focusedDepartment.name}
              </span>
              <button
                aria-label="Clear department filter"
                onClick={() => {
                  setDepartment(null);
                  scene.current?.resetView();
                }}
              >
                <X size={14} />
              </button>
            </div>
          )}
          <div
            className="society-panel"
            role="tabpanel"
            id={`${tab}-panel`}
            aria-labelledby={`${tab}-tab`}
          >
            {tab === "residents" ? (
              <>
                <div className="society-list-heading">
                  <span>
                    {focusedDepartment
                      ? "IN THIS DEPARTMENT"
                      : "AROUND THE CAMPUS"}
                  </span>
                  <span>
                    {live ? "LIVE" : demo ? "DEMO" : "OFFLINE"}{" "}
                    <span
                      className={`society-tiny-dot ${live || demo ? "active" : ""}`}
                    />
                  </span>
                </div>
                <div className="society-resident-list">
                  {visibleResidents.map((resident) => {
                    const dept = departmentOf(resident.department);
                    return (
                      <button
                        className={`society-resident ${selected === resident.id ? "selected" : ""}`}
                        key={resident.id}
                        aria-pressed={selected === resident.id}
                        onClick={() =>
                          setSelected(
                            selected === resident.id ? null : resident.id,
                          )
                        }
                      >
                        <span
                          className="society-avatar"
                          style={
                            {
                              "--avatar-color": avatarColor(resident.id),
                            } as React.CSSProperties
                          }
                        >
                          <span className="society-avatar-face">
                            <i />
                            <i />
                          </span>
                          <span
                            className={`society-resident-dot ${resident.status}`}
                          />
                        </span>
                        <span className="society-resident-info">
                          <span>
                            <strong>{resident.name}</strong>
                            {resident.kind === "main" && <small>LEAD</small>}
                          </span>
                          <span>
                            <i style={{ background: dept.color }} />
                            {dept.name}
                          </span>
                        </span>
                        <span
                          className={`society-resident-status ${resident.status}`}
                        >
                          {statusLabel(resident.status)}
                          <ChevronRight size={13} />
                        </span>
                      </button>
                    );
                  })}
                </div>
                {!visibleResidents.length && (
                  <div className="society-empty">
                    <Users size={30} />
                    <h3>
                      {department
                        ? "A quiet corner, for now."
                        : "Room for great minds."}
                    </h3>
                    <p>
                      {department
                        ? "Residents arrive here as their work calls for it."
                        : "Your agent and its collaborators will appear here when the CLI connects."}
                    </p>
                  </div>
                )}
              </>
            ) : (
              <>
                <div className="society-list-heading">
                  <span>THE LATEST FOOTSTEPS</span>
                  <span>{events.length} EVENTS</span>
                </div>
                <div className="society-events">
                  {events.map((event, i) => {
                    const who = snapshot.agents.find(
                      (a) => a.id === event.agent_id,
                    );
                    return (
                      <div className="society-event" key={`${event.id}-${i}`}>
                        <span
                          className={`society-event-mark ${event.status === "error" ? "error" : ""}`}
                        >
                          <ArrowDownLeft size={13} />
                        </span>
                        <div>
                          <strong>
                            {who?.name ?? "Agent"}
                            <span
                              className={`society-event-kind ${event.status}`}
                            >
                              {event.kind
                                .replace(/^tool_/, "")
                                .replace(/_/g, " ")}
                            </span>
                          </strong>
                          <p>
                            {event.tool
                              ? prettyTool(event.tool)
                              : event.kind.replace(/_/g, " ")}
                          </p>
                          <small>{departmentOf(event.department).name}</small>
                        </div>
                        <time>{timeAgo(event.timestamp)}</time>
                      </div>
                    );
                  })}
                </div>
                {!events.length && (
                  <div className="society-empty">
                    <Activity size={30} />
                    <h3>Every step tells a story.</h3>
                    <p>
                      Real tool activity will appear here as your agents work.
                    </p>
                  </div>
                )}
              </>
            )}
          </div>
          {current ? (
            <div className="society-detail">
              <div className="society-detail-top">
                <span className="society-eyebrow">RESIDENT SPOTLIGHT</span>
                <button
                  aria-label="Close resident spotlight"
                  onClick={() => setSelected(null)}
                >
                  <X size={15} />
                </button>
              </div>
              <h3>
                {current.name}
                <span>
                  {current.kind === "main"
                    ? "Lead agent"
                    : current.kind === "kid"
                      ? "Child agent"
                      : current.kind === "delegate"
                        ? "Delegate"
                        : current.kind === "specialist"
                          ? "Specialist"
                          : "Swarm agent"}
                </span>
              </h3>
              <p>
                <span
                  className={`society-tiny-dot ${activeStatuses.has(current.status) ? "active" : ""}`}
                />
                {statusLabel(current.status)} in{" "}
                {departmentOf(current.department).name}
              </p>
              {current.tool && <code>{current.tool}</code>}
              <button
                className="society-follow"
                onClick={() => setDepartment(current.department)}
              >
                Visit department <ArrowUpRight size={14} />
              </button>
            </div>
          ) : (
            <div className="society-sidebar-note">
              <span className="society-note-art">
                <Leaf size={24} strokeWidth={1.2} />
              </span>
              <h3>A society that grows with you.</h3>
              <p>
                {demo
                  ? "These residents are simulated. Switch to live to watch your own agents."
                  : "Every resident is a real agent. Their next destination follows their next task."}
              </p>
              <span>
                Made of little moments <span>✳</span>
              </span>
            </div>
          )}
        </aside>
        <nav className="society-departments" aria-label="Departments">
          <div className="society-dock-title">
            <span>FIND YOUR WAY</span>
            <strong>
              The departments <ArrowUpRight size={14} />
            </strong>
          </div>
          <div className="society-department-buttons">
            {departments.map((dept) => {
              const Icon = deptIcons[dept.id];
              const count = snapshot.agents.filter(
                (a) => a.department === dept.id && a.status !== "offline",
              ).length;
              return (
                <button
                  key={dept.id}
                  className={department === dept.id ? "selected" : ""}
                  aria-pressed={department === dept.id}
                  onClick={() => {
                    const next = department === dept.id ? null : dept.id;
                    setDepartment(next);
                    if (!next) scene.current?.resetView();
                  }}
                  title={dept.description}
                >
                  <span
                    className="society-dept-icon"
                    style={
                      { "--dept-color": dept.color } as React.CSSProperties
                    }
                  >
                    <Icon size={20} strokeWidth={1.6} />
                  </span>
                  <span>
                    {dept.short}
                    <small>
                      {count} {count === 1 ? "resident" : "residents"}
                    </small>
                  </span>
                </button>
              );
            })}
          </div>
        </nav>
      </main>
      <footer className="society-footer">
        <span>
          <ShieldCheck size={14} /> Separate browser · read-only view
        </span>
        <span className="society-footer-center">
          {paused
            ? "Animation paused · telemetry stays live"
            : demo
              ? "SIMULATED ACTIVITY · DEMO MODE"
              : live
                ? "In step with your CLI"
                : "Your campus is waiting for a connection"}
          <span className="society-footer-star">✳</span>
        </span>
        <time>
          {clock.toLocaleTimeString([], {
            hour: "2-digit",
            minute: "2-digit",
            hour12: false,
          })}{" "}
          <span>LOCAL TIME</span>
        </time>
      </footer>
      {help && (
        <div className="society-modal-backdrop" onClick={closeHelp}>
          <div
            className="society-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="society-help-title"
            onClick={(event) => event.stopPropagation()}
            onKeyDown={(event) => {
              if (event.key === "Escape") closeHelp();
              if (event.key === "Tab") {
                const controls =
                  event.currentTarget.querySelectorAll<HTMLButtonElement>(
                    "button",
                  );
                const first = controls[0];
                const last = controls[controls.length - 1];
                if (event.shiftKey && document.activeElement === first) {
                  event.preventDefault();
                  last?.focus();
                } else if (!event.shiftKey && document.activeElement === last) {
                  event.preventDefault();
                  first?.focus();
                }
              }
            }}
          >
            <button
              className="society-modal-close society-icon-button"
              ref={helpClose}
              aria-label="Close help"
              onClick={closeHelp}
            >
              <X size={20} />
            </button>
            <span className="society-eyebrow">
              WELCOME TO YOUR LITTLE WORLD
            </span>
            <h2 id="society-help-title">Work, with a sense of place.</h2>
            <p>
              Agents walk to the department that matches their real work. Select
              a resident to see its current activity, or a department to
              explore.
            </p>
            <ul>
              <li>
                Drag the campus to look around; scroll or use + / − to zoom.
              </li>
              <li>Pause freezes the animation. Your agents keep working.</li>
              <li>The sun switches the atmosphere. Labels can be hidden.</li>
            </ul>
            <p>
              Enable this view with <code>society.enabled: true</code> in{" "}
              <code>config.yaml</code>, then run <code>./start.sh</code>. Its
              dedicated browser profile is separate from the browser your agents
              control.
            </p>
            <button
              className="society-modal-action"
              onClick={() => {
                setDemo(!demo);
                closeHelp();
                reset();
              }}
            >
              {demo ? "Return to live campus" : "Take a demo tour"}{" "}
              <ArrowUpRight size={16} />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
