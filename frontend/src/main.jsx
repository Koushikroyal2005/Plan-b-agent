import React, { useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Activity,
  Archive,
  ArrowRight,
  Bell,
  Bot,
  CalendarDays,
  Check,
  ChevronLeft,
  ChevronRight,
  Clock3,
  Code2,
  Columns3,
  Command,
  History,
  FolderKanban,
  LayoutList,
  ListFilter,
  ListTodo,
  Loader2,
  Mic,
  Pencil,
  PieChart,
  Plus,
  RotateCcw,
  Search,
  Settings,
  ShieldCheck,
  Sparkles,
  Target,
  TrendingUp,
  X,
  Zap,
} from "lucide-react";
import { api } from "./core/api";
import { navigation } from "./core/navigation";
import { ProviderModelPicker } from "./features/settings/ProviderModelPicker";
import { AppHeader } from "./components/AppHeader";
import { VoiceAssistant } from "./components/VoiceAssistant";
import { StepTimeline, TurnDetails } from "./components/TurnDetails";
import { VoiceSessionProvider, useVoiceSession } from "./voice/VoiceSession";
import { BrowserSynthesis, selectVoiceProvider } from "./voice/providers";
import { CalendarWorkspace } from "./features/calendar/CalendarWorkspace";
import "./styles.css";
import "./features.css";

const READ_ONLY_CAPABILITIES = new Set([
  "tasks.search",
  "calendar.inspect",
  "calendar.task_session",
  "calendar.find_slot",
  "schedule.assess",
  "schedule.recover",
  "schedule.explain",
  "insights.explain",
  "actions.history",
  "app.navigate",
]);

function App() {
  const [view, setView] = useState("dashboard");
  const [data, setData] = useState({
    tasks: [],
    projects: [],
    day: null,
    history: [],
    preferences: null,
    provider: null,
    patterns: null,
    opportunities: [],
    activityFeed: [],
  });
  const [recovery, setRecovery] = useState(null);
  const [messages, setMessages] = useState([
    {
      role: "assistant",
      text: "Good morning. I can inspect your schedule, calculate risk, and prepare validated alternatives. What changed today?",
    },
  ]);
  const [activity, setActivity] = useState([]);
  const [loading, setLoading] = useState(true);
  const [taskModal, setTaskModal] = useState(null);
  const [projectModal, setProjectModal] = useState(null);
  const [showSetup, setShowSetup] = useState(false);
  const [toast, setToast] = useState(null);
  const [assistantTurn, setAssistantTurn] = useState(null);
  const [assistantBusy, setAssistantBusy] = useState(false);
  const [assistantQueueSize, setAssistantQueueSize] = useState(0);
  const [demo, setDemo] = useState({ active: false });
  const assistantBusyRef = useRef(false);
  const assistantQueueRef = useRef([]);
  const previousView = useRef("dashboard");
  const voiceProvider = useMemo(() => selectVoiceProvider(), []);
  const voiceSynthesis = useMemo(() => new BrowserSynthesis(), []);
  const sessionId = useMemo(() => {
    const existing = window.localStorage.getItem("planb-assistant-session");
    if (existing) return existing;
    const created = window.crypto?.randomUUID?.() || `session-${Date.now()}`;
    window.localStorage.setItem("planb-assistant-session", created);
    return created;
  }, []);

  const notify = (title, body, action = null) => {
    setToast({ title, body, action });
    window.setTimeout(() => setToast(null), action ? 8000 : 3500);
  };
  const refresh = async () => {
    setLoading(true);
    try {
      const [
        tasks,
        projects,
        day,
        history,
        preferences,
        provider,
        patterns,
        opportunityData,
        activityFeed,
      ] = await Promise.all([
        api("/tasks"),
        api("/projects"),
        api("/day"),
        api("/recovery/history"),
        api("/preferences"),
        api("/provider/status"),
        api("/patterns"),
        api("/opportunities"),
        api("/activity"),
      ]);
      setData({
        tasks,
        projects,
        day,
        history,
        preferences,
        provider,
        patterns,
        opportunities: opportunityData.items,
        activityFeed,
      });
      if (!preferences.onboarding_complete) setShowSetup(true);
    } catch (error) {
      notify("Backend unavailable", error.message);
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => {
    refresh();
    api("/demo").then(setDemo).catch(() => {});
  }, []);
  useEffect(() => {
    let active = true;
    api(`/assistant/history?session_id=${encodeURIComponent(sessionId)}&limit=80`)
      .then((result) => {
        if (active && result.messages?.length) setMessages(result.messages);
      })
      .catch(() => {});
    return () => { active = false; };
  }, [sessionId]);

  const createRecovery = async (
    minutes = 60,
    reason = "Team meeting overran by 60 minutes",
  ) => {
    try {
      setRecovery(
        await api("/recovery/options", {
          method: "POST",
          body: JSON.stringify({ disruption_minutes: minutes, reason }),
        }),
      );
      setView("recovery");
    } catch (error) {
      notify("Could not build recovery", error.message);
    }
  };
  const runUiCommands = (commands = []) => {
    commands.forEach((command) => {
      if (command.type === "navigate" && navigation.some((item) => item.id === command.target || (command.target === "day" && item.id === "dashboard"))) {
        previousView.current = view;
        setView(command.target === "day" ? "dashboard" : command.target);
      } else if (command.type === "back") {
        setView(previousView.current || "dashboard");
      } else if (command.type === "open_modal" && command.target === "task") {
        setTaskModal(command.payload || {});
      } else if (command.type === "open_modal" && command.target === "project") {
        setProjectModal(command.payload || {});
      } else if (command.type === "close_modal") {
        setTaskModal(null);
        setProjectModal(null);
      } else if (command.type === "show_help") {
        setView("assistant");
      }
    });
  };
  const sendMessage = async (text, channel = "text", queuedEntry = null) => {
    if (!text.trim()) return;
    const entry = queuedEntry || {
      id: window.crypto?.randomUUID?.() || `message-${Date.now()}`,
      text,
      channel,
    };
    if (!queuedEntry) {
      setMessages((items) => [...items, { id: entry.id, role: "user", text, status: assistantBusyRef.current ? "Queued" : "Sending" }]);
    }
    if (assistantBusyRef.current) {
      assistantQueueRef.current.push(entry);
      setAssistantQueueSize(assistantQueueRef.current.length);
      return;
    }
    assistantBusyRef.current = true;
    setMessages((items) => items.map((item) => item.id === entry.id ? { ...item, status: "Sent" } : item));
    setAssistantBusy(true);
    try {
      const result = await api("/assistant", {
        method: "POST",
        body: JSON.stringify({
          message: text,
          utterance: text,
          session_id: sessionId,
          channel,
          current_view: view,
          idempotency_key: window.crypto?.randomUUID?.() || `${sessionId}-${Date.now()}`,
          client_capabilities: ["navigate", "modal", "highlight", "speech-synthesis"],
        }),
      });
      const turn = { ...result, channel };
      setMessages((items) => [
        ...items,
        { id: result.turn_id, role: "assistant", text: result.message, understood: result.understood, turn },
      ]);
      setActivity(result.steps || []);
      if (result.recovery) setRecovery(result.recovery);
      setAssistantTurn(turn);
      runUiCommands(result.ui_commands);
      if (result.tools?.some((item) => !READ_ONLY_CAPABILITIES.has(item.tool))) {
        await refresh();
      }
      return turn;
    } catch (error) {
      const failed = { turn_id: entry.id, say: `Plan B couldn't finish that: ${error.message}`, state: "failed", channel };
      setMessages((items) => [...items, { id: `${entry.id}-error`, role: "assistant", text: failed.say }]);
      setAssistantTurn(failed);
      return failed;
    } finally {
      assistantBusyRef.current = false;
      setAssistantBusy(false);
      const next = assistantQueueRef.current.shift();
      setAssistantQueueSize(assistantQueueRef.current.length);
      if (next) window.setTimeout(() => sendMessage(next.text, next.channel, next), 0);
    }
  };
  const patchTask = async (taskId, changes) => {
    try {
      await api(`/tasks/${taskId}`, {
        method: "PATCH",
        body: JSON.stringify(changes),
      });
      await refresh();
    } catch (error) {
      notify("Task update failed", error.message);
    }
  };
  const forgetUndo = (actionId) => {
    const strip = (turn) => turn?.undo?.action_id === actionId ? { ...turn, undo: null } : turn;
    setMessages((items) => items.map((item) => item.turn ? { ...item, turn: strip(item.turn) } : item));
    setAssistantTurn(strip);
  };
  const undoAction = async (actionId) => {
    try {
      const result = await api(`/actions/${actionId}/undo`, { method: "POST" });
      forgetUndo(actionId);
      const turn = { ...result, channel: "text" };
      setMessages((items) => [...items, { id: result.turn_id, role: "assistant", text: result.say, understood: result.understood, turn }]);
      setAssistantTurn(turn);
      setActivity(result.steps || []);
      notify("Undone", result.say);
      await refresh();
    } catch (error) {
      notify("Undo failed", error.message);
    }
  };
  const toggleDemo = async () => {
    try {
      const next = await api("/demo", { method: demo.active ? "DELETE" : "POST" });
      setDemo(next);
      setRecovery(null);
      notify(
        next.active ? "Judge demo loaded" : "Demo closed",
        next.active
          ? "It's 1:30 PM and the team meeting just started. Try: “My meeting ran 45 minutes late and I still need to finish the pitch before 6.”"
          : "Your own tasks and settings are back.",
      );
      setView("dashboard");
      await refresh();
    } catch (error) {
      notify("Demo unavailable", error.message);
    }
  };
  const approve = async (proposalId) => {
    try {
      const result = await api(`/recovery/${proposalId}/approve`, { method: "POST" });
      notify(
        "Recovery plan applied",
        "The previous version remains in history.",
        result.action_id ? { label: "Undo", onClick: () => undoAction(result.action_id) } : null,
      );
      await refresh();
    } catch (error) {
      notify("Approval blocked", error.message);
    }
  };
  const restore = async (planId) => {
    try {
      await api(`/recovery/${planId}/restore`, { method: "POST" });
      notify("Plan restored", "A new recoverable version was created.");
      await refresh();
    } catch (error) {
      notify("Restore failed", error.message);
    }
  };
  const savePreferences = async (next) => {
    try {
      const saved = await api("/preferences", {
        method: "PUT",
        body: JSON.stringify(next),
      });
      setData((current) => ({ ...current, preferences: saved }));
      notify(
        "Settings saved",
        "The scheduler is using your updated constraints.",
      );
      await refresh();
    } catch (error) {
      notify("Settings failed", error.message);
    }
  };
  const respondOpportunity = async (item, accepted) => {
    try {
      await api(`/opportunities/${item.id}/respond`, {
        method: "POST",
        body: JSON.stringify({ accepted }),
      });
      setData((current) => ({
        ...current,
        opportunities: current.opportunities.filter(
          (entry) => entry.id !== item.id,
        ),
      }));
      if (accepted && item.id === "protect-deadline") createRecovery();
      else if (accepted && item.id === "focus-window") setView("calendar");
      else if (accepted && item.id === "buffer-rule") setView("settings");
      else if (accepted && item.id === "plan-healthy") setView("dashboard");
      notify(
        accepted ? "Suggestion accepted" : "Suggestion dismissed",
        accepted ? item.action : "Plan B will remember this response.",
      );
    } catch (error) {
      notify("Could not save response", error.message);
    }
  };

  const views = {
    dashboard: (
      <TodayView
        day={data.day}
        tasks={data.tasks}
        projects={data.projects}
        opportunities={data.opportunities}
        provider={data.provider}
        openChat={() => setView("assistant")}
        openCalendar={() => setView("calendar")}
        openTasks={() => setView("tasks")}
        onAdd={(draft = {}) => setTaskModal(draft)}
        onRecovery={createRecovery}
        onRefresh={refresh}
        onRespond={respondOpportunity}
        navigate={setView}
        displayName={data.preferences?.display_name || "there"}
        activityFeed={data.activityFeed}
        demo={demo}
        onToggleDemo={toggleDemo}
      />
    ),
    calendar: (
      <CalendarWorkspace
        day={data.day}
        tasks={data.tasks}
        onRecovery={createRecovery}
        sendMessage={sendMessage}
        onAdd={() => setTaskModal({})}
        onPatch={patchTask}
        notify={notify}
      />
    ),
    tasks: (
      <TasksView
        tasks={data.tasks}
        projects={data.projects}
        onAdd={() => setTaskModal({})}
        onAddProject={() => setProjectModal({})}
        onEdit={(task) => setTaskModal(task)}
        onPatch={patchTask}
        onEditProject={(project) => setProjectModal(project)}
        onPatchProject={async (projectId, changes) => {
          try {
            await api(`/projects/${projectId}`, {
              method: "PATCH",
              body: JSON.stringify(changes),
            });
            await refresh();
            notify(
              changes.status === "archived" ? "Project archived" : "Project updated",
              "Project changes are saved.",
            );
          } catch (error) {
            notify("Project update failed", error.message);
          }
        }}
      />
    ),
    assistant: (
      <AssistantView
        messages={messages}
        activity={activity}
        lastTurn={assistantTurn}
        sendMessage={sendMessage}
        onUndo={undoAction}
        preferences={data.preferences}
        currentView={previousView.current}
        busy={assistantBusy}
        queueSize={assistantQueueSize}
      />
    ),
    recovery: (
      <RecoveryView
        data={recovery}
        history={data.history}
        approve={approve}
        restore={restore}
        generate={createRecovery}
      />
    ),
    patterns: <PatternsView data={data.patterns} projects={data.projects} onDiscuss={(prompt) => { sendMessage(prompt); setView("assistant"); }} />,
    mcp: <McpView notify={notify} />,
    settings: (
      <>
        <SettingsView
          preferences={data.preferences}
          provider={data.provider}
          save={savePreferences}
          openSetup={() => setShowSetup(true)}
          notify={notify}
          onProviderChanged={refresh}
        />
        <ProviderModelPicker
          activeModel={data.provider?.model}
          configured={data.provider?.configured}
          notify={notify}
          onChanged={refresh}
        />
      </>
    ),
  };

  return (
    <VoiceSessionProvider
      provider={voiceProvider}
      synthesis={voiceSynthesis}
      language={data.preferences?.language || "en-IN"}
      voiceOutput={Boolean(data.preferences?.voice_output)}
      onUtterance={sendMessage}
    >
    <div className="app-shell">
      <Sidebar
        view={view}
        setView={setView}
        name={data.preferences?.display_name}
      />
      <main className="main">
        <AppHeader
          view={view}
          tasks={data.tasks}
          projects={data.projects}
          onNavigate={setView}
          name={data.preferences?.display_name}
        />
        <div className="page">
          {loading && !data.day ? <Loading /> : views[view]}
        </div>
      </main>
      {taskModal && (
        <TaskModal
          task={taskModal}
          projects={data.projects}
          close={() => setTaskModal(null)}
          onSaved={() => {
            setTaskModal(null);
            refresh();
            notify(
              "Task saved",
              "The schedule now uses your latest task details.",
            );
          }}
        />
      )}
      {projectModal && (
        <ProjectModal
          project={projectModal.id ? projectModal : null}
          close={() => setProjectModal(null)}
          onSaved={(edited) => {
            setProjectModal(null);
            refresh();
            notify(
              edited ? "Project updated" : "Project added",
              edited
                ? "The project details were saved."
                : "You can now assign tasks and track its progress.",
            );
          }}
        />
      )}
      {showSetup && data.preferences && (
        <Onboarding
          preferences={data.preferences}
          close={() => setShowSetup(false)}
          save={async (next) => {
            await savePreferences({ ...next, onboarding_complete: true });
            setShowSetup(false);
          }}
        />
      )}
      {toast && <Toast {...toast} />}
      {view !== "assistant" && <VoiceAssistant
        turn={assistantTurn}
        busy={assistantBusy}
        preferences={data.preferences}
        currentView={view}
        onUndo={undoAction}
        onOpenChat={() => setView("assistant")}
      />}
    </div>
    </VoiceSessionProvider>
  );
}

function Sidebar({ view, setView, name = "Koushik" }) {
  return (
    <aside className="sidebar">
      <div className="brand">
        <span>✦</span> plan <i>b</i>
      </div>
      <div className="workspace">
        <span className="avatar">{name.slice(0, 2).toUpperCase()}</span>
        <div>
          <b>{name}'s plan</b>
          <small>Personal workspace</small>
        </div>
        <ChevronRight size={14} />
      </div>
      <nav>
        {navigation.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            className={view === id ? "active" : ""}
            onClick={() => setView(id)}
            title={label}
          >
            <Icon size={17} />
            <span>{label}</span>
            {id === "recovery" && <em />}
          </button>
        ))}
      </nav>
      <div className="watch">
        <span className="pulse" />
        <div>
          <b>Plan B is watching</b>
          <small>Constraints checked just now</small>
        </div>
      </div>
    </aside>
  );
}
function Header({ view }) {
  return (
    <header className="topbar">
      <div className="mobile-brand">
        <span>✦</span> plan <i>b</i>
      </div>
      <div className="crumb">
        {navigation.find((item) => item.id === view)?.label}
        <span>/</span> Monday, October 19
      </div>
      <div className="top-actions">
        <Search size={19} />
        <Bell size={18} />
        <span className="avatar">KS</span>
      </div>
    </header>
  );
}
const View = ({ id, children }) => (
  <section className={`view view-${id}`}>{children}</section>
);
const Eyebrow = ({ children }) => <p className="eyebrow">{children}</p>;
const Button = ({
  children,
  primary = false,
  onClick,
  className = "",
  type = "button",
  disabled = false,
}) => (
  <button
    type={type}
    disabled={disabled}
    onClick={onClick}
    className={`btn ${primary ? "primary" : ""} ${className}`}
  >
    {children}
  </button>
);
const PanelHeading = ({ title, sub }) => (
  <div className="panel-heading">
    <div>
      <h2>{title}</h2>
      <p>{sub}</p>
    </div>
    <Sparkles size={18} className="accent" />
  </div>
);
const Loading = () => (
  <div className="loading">
    <Loader2 className="spin" />
    <span>Calculating a resilient plan…</span>
  </div>
);
const Toast = ({ title, body, action }) => (
  <div className="toast">
    <Check size={16} />
    <div>
      <b>{title}</b>
      <small>{body}</small>
    </div>
    {action && <button className="toast-action" onClick={action.onClick}>{action.label}</button>}
  </div>
);

function TodayView({
  day,
  tasks,
  projects,
  opportunities,
  provider,
  openChat,
  openCalendar,
  openTasks,
  onAdd,
  onRecovery,
  onRefresh,
  onRespond,
  navigate,
  displayName,
  activityFeed = [],
  demo = {},
  onToggleDemo,
}) {
  const [filter, setFilter] = useState("all");
  const [showAllActivity, setShowAllActivity] = useState(false);
  const [showAllSignals, setShowAllSignals] = useState(false);
  if (!day) return null;
  const metrics = day.metrics || {};
  const risk = day.risks?.[0];
  const open = tasks.filter((task) => task.status === "open");
  const focusMinutes =
    day.blocks
      ?.filter((block) => block.kind === "focus" || block.kind === "risk")
      .reduce((sum, block) => sum + block.minutes, 0) || 0;
  const headingDate = day.date
    ? new Date(`${day.date}T12:00:00`)
        .toLocaleDateString([], {
          weekday: "long",
          month: "long",
          day: "numeric",
          year: "numeric",
        })
        .toUpperCase()
    : "TODAY";
  const filtered = opportunities.filter(
    (item) => filter === "all" || item.kind === filter,
  );
  const visibleSignals = showAllSignals ? filtered : filtered.slice(0, 2);
  const visibleActivity = showAllActivity ? activityFeed : activityFeed.slice(0, 3);
  const signalFilters = [
    ["all", "All"],
    ["suggestion", "Suggestions"],
    ["alert", "Alerts"],
    ["automation", "Automations"],
  ];
  return (
    <View id="dashboard">
      <div className="hero">
        <div>
          <Eyebrow>{headingDate}</Eyebrow>
          <h1>
            Good morning, {displayName} <span>✦</span>
          </h1>
          <p>
            {day.plan_stale
              ? "Your tasks or settings changed after the last approved plan, so this timeline was rebuilt."
              : day.schedule_source === "approved_plan"
                ? "This timeline is the recovery plan you approved."
                : "Your tasks, risks and suggestions are calculated for today."}
          </p>
        </div>
        <div className="hero-buttons">
          <Button onClick={onRefresh}>
            <RotateCcw size={14} /> Refresh
          </Button>
          <Button onClick={() => navigate("recovery")}>
            <History size={14} /> History
          </Button>
          <Button onClick={openCalendar}>
            <CalendarDays size={14} /> Calendar
          </Button>
          <Button onClick={() => onRecovery()}>
            <Zap size={14} /> Something changed
          </Button>
          <Button onClick={onToggleDemo}>
            <Sparkles size={14} /> {demo.active ? "Exit judge demo" : "Load judge demo"}
          </Button>
          <Button primary onClick={onAdd}>
            <Plus size={15} /> Add task
          </Button>
        </div>
      </div>
      {demo.active && (
        <div className="demo-banner">
          <b>Judge demo · the clock is pinned at {demo.clock}</b>
          <span>Say or type: “My meeting ran 45 minutes late and I still need to finish the pitch before 6.” Then “Don't move lecture notes. Shorten the report review instead.”, “Apply it”, and “Undo that”.</span>
        </div>
      )}
      <div className={`risk-banner ${day.status === "on_track" ? "on-track" : ""}`}>
        <span>{day.status === "on_track" ? "✓" : "!"}</span>
        <div>
          <b>
            {day.status === "on_track"
              ? "Your plan is on track"
              : "Your plan needs attention"}
          </b>
          <small>
            {risk?.reason || "All scheduled work fits inside its constraints."}
          </small>
        </div>
        <button onClick={() => onRecovery()}>
          See recovery options <ArrowRight size={14} />
        </button>
      </div>
      <div className="dashboard-metrics screen4-metrics">
        <DashboardMetric
          icon={<ListTodo size={17} />}
          tone="violet"
          label="Tasks today"
          value={open.length}
          note={`${metrics.deadlines_today || 0} due today`}
        />
        <DashboardMetric
          icon={<Clock3 size={17} />}
          tone="amber"
          label="Focus time"
          value={`${Math.floor(focusMinutes / 60)}h ${focusMinutes % 60}m`}
          note={`${day.blocks?.length || 0} scheduled blocks`}
        />
        <DashboardMetric
          icon={<Target size={17} />}
          tone="blue"
          label="Free buffer"
          value={`${metrics.free_buffer_minutes || 0}m`}
          note={`${metrics.confidence || 0}% plan confidence`}
        />
        <DashboardMetric
          icon={<Check size={17} />}
          tone="green"
          label="Fixed events"
          value={day.blocks?.filter((block) => block.kind === "fixed").length || 0}
          note={provider?.configured ? `${provider.provider} connected` : "Deterministic planner"}
        />
      </div>
      <div className="day-grid">
        <div className="panel timeline-panel">
          <PanelHeading
            title="Today's timeline"
            sub={`Plan v${day.plan_version || 1} · fixed commitments stay protected`}
          />
          <Timeline blocks={day.blocks} />
        </div>
        <div className="panel prediction-panel">
          <PanelHeading
            title="Suggestions"
            sub={`${opportunities.length} current signals`}
          />
          <div className="prediction-tabs" role="tablist" aria-label="Suggestion categories">
            {signalFilters.map(([item, label]) => (
              <button
                type="button"
                className={filter === item ? "active" : ""}
                onClick={() => { setFilter(item); setShowAllSignals(false); }}
                key={item}
                role="tab"
                aria-selected={filter === item}
              >
                {label}<span>{item === "all" ? opportunities.length : opportunities.filter((signal) => signal.kind === item).length}</span>
              </button>
            ))}
          </div>
          <div className="prediction-list">
          {visibleSignals.map((item) => (
            <div className={`prediction ${item.kind}`} key={item.id}>
              <header>
                <b>{item.title}</b>
                <em>{item.confidence}%</em>
              </header>
              <p>{item.description}</p>
              <div className="confidence">
                <i style={{ width: `${item.confidence}%` }} />
              </div>
              <small>{item.evidence}</small>
              <footer>
                <button onClick={() => onRespond(item, false)}>Decline</button>
                <button onClick={() => onRespond(item, true)}>
                  {item.action}
                </button>
              </footer>
            </div>
          ))}
          </div>
          {filtered.length > 2 && (
            <button type="button" className="list-expander" onClick={() => setShowAllSignals((current) => !current)}>
              {showAllSignals ? "Show less" : `Show ${filtered.length - 2} more`}
            </button>
          )}
          {!filtered.length && <p className="muted">No signals in this category.</p>}
        </div>
      </div>
      <div className="today-lower">
        <div className="panel rail-card">
          <div className="rail-head">
            <b>
              <FolderKanban size={15} /> Project progress
            </b>
            <button type="button" onClick={openTasks}>
              View all
            </button>
          </div>
          {projects.slice(0, 3).map((project) => (
            <div className="rail-project" key={project.id}>
              <header>
                <b>{project.name}</b>
                <span>{project.progress}%</span>
              </header>
              <i>
                <em style={{ width: `${project.progress}%`, background: project.color }} />
              </i>
            </div>
          ))}
        </div>
        <div className="panel rail-card">
          <div className="rail-head">
            <b>
              <Activity size={15} /> Activity
            </b>
            <button type="button" onClick={() => setShowAllActivity((current) => !current)}>
              {showAllActivity ? "Show less" : "View all"}
            </button>
          </div>
          <div className={`activity-list ${showAllActivity ? "expanded" : ""}`}>
          {visibleActivity.length ? (
            visibleActivity.map((item) => (
              <Feed
                key={item.id}
                icon={<Activity size={13} />}
                title={item.type.replaceAll("_", " ")}
                detail={item.detail}
              />
            ))
          ) : (
            <Feed
              icon={<Activity size={13} />}
              title="No activity yet"
              detail="Task, project and recovery actions will appear here"
            />
          )}
          </div>
          <div className="rail-suggestion">
            <Sparkles size={18} />
            <div>
              <b>Assistant</b>
              <p>{opportunities[0]?.description || "Your current schedule is stable."}</p>
            </div>
            {opportunities[0] ? (
              <div className="suggestion-actions">
                <button onClick={() => onRespond(opportunities[0], false)}>Dismiss</button>
                <button onClick={() => onRespond(opportunities[0], true)}>{opportunities[0].action}</button>
              </div>
            ) : (
              <button onClick={openChat}>Discuss my plan</button>
            )}
          </div>
        </div>
      </div>
    </View>
  );
}
function DashboardMetric({ icon, tone, label, value, note }) {
  return (
    <div className={`dashboard-stat ${tone}`}>
      <header>
        <span>{icon}</span>
        <b>{label}</b>
      </header>
      <strong>{value}</strong>
      <small>{note}</small>
    </div>
  );
}
function Feed({ icon, title, detail }) {
  return (
    <div className="feed-row">
      <span>{icon}</span>
      <div>
        <b>{title}</b>
        <small>{detail}</small>
      </div>
    </div>
  );
}

function Metric({ label, value, unit, note, good, warning }) {
  return (
    <div className="metric">
      <span>{label}</span>
      <strong>
        {value}
        <i>{unit ? ` ${unit}` : ""}</i>
      </strong>
      <small className={good ? "good" : warning ? "warning" : ""}>{note}</small>
    </div>
  );
}
function Timeline({ blocks = [] }) {
  return (
    <div className="timeline">
      {blocks.map((block) => (
        <div
          className="timeline-row"
          key={`${block.task_id}-${block.start_iso}`}
        >
          <span>{block.start}</span>
          <div className={`block ${block.kind}`}>
            <b>{block.title}</b>
            <small>
              {block.detail} · ends {block.end}
            </small>
            <em>{block.label}</em>
          </div>
        </div>
      ))}
    </div>
  );
}

function CalendarView({ day, tasks, onRecovery, sendMessage }) {
  const [mode, setMode] = useState("Week");
  const [selectedDay, setSelectedDay] = useState(null);
  const [selectedBlock, setSelectedBlock] = useState(null);
  const days = ["Mon 19", "Tue 20", "Wed 21", "Thu 22", "Fri 23"];
  const dayTasks = (index) =>
    index === 0
      ? day?.blocks || []
      : tasks
          .filter((task) => task.status === "open")
          .slice(index - 1, index + 1)
          .map((task) => ({
            ...task,
            minutes: task.duration_minutes,
            start: "Flexible",
            end: "",
            kind: "ghost",
            label: task.priority,
          }));
  return (
    <View id="calendar">
      <div className="section-head">
        <div>
          <Eyebrow>SCHEDULE PREVIEW</Eyebrow>
          <h1>Calendar</h1>
          <p>
            Click any day or time block for details and a complete time
            breakdown.
          </p>
        </div>
        <div className="segmented">
          {["Day", "Week"].map((item) => (
            <button
              className={mode === item ? "active" : ""}
              onClick={() => setMode(item)}
              key={item}
            >
              {item}
            </button>
          ))}
        </div>
      </div>
      <div className="calendar-layout">
        <div className="panel week-calendar">
          <div className="calendar-toolbar">
            <button>
              <ChevronLeft size={15} />
            </button>
            <b>October 19–23, 2026</b>
            <button>
              <ChevronRight size={15} />
            </button>
            <span />
            <Button onClick={() => onRecovery(30, "Calendar disruption")}>
              Recalculate
            </Button>
          </div>
          <div className={`week-grid ${mode.toLowerCase()}`}>
            <div className="time-axis">
              {["9 AM", "11 AM", "1 PM", "3 PM", "5 PM", "7 PM"].map((time) => (
                <span key={time}>{time}</span>
              ))}
            </div>
            {days.slice(0, mode === "Day" ? 1 : 5).map((label, index) => (
              <div
                className={`day-column ${index === 0 ? "today" : ""}`}
                key={label}
              >
                <button
                  className="day-header"
                  onClick={() =>
                    setSelectedDay({ label, index, blocks: dayTasks(index) })
                  }
                >
                  {label}
                  <small>{dayTasks(index).length} items</small>
                </button>
                {dayTasks(index).map((block, blockIndex) => (
                  <button
                    className={`calendar-block ${block.kind}`}
                    onClick={() => setSelectedBlock(block)}
                    style={{
                      top: `${57 + blockIndex * 76}px`,
                      height: `${Math.max(58, block.minutes * 0.7)}px`,
                    }}
                    key={`${block.task_id || block.id}-${blockIndex}`}
                  >
                    <b>{block.title}</b>
                    <small>
                      {block.start}
                      {block.end ? `–${block.end}` : ""}
                    </small>
                  </button>
                ))}
              </div>
            ))}
          </div>
        </div>
        <div className="panel calendar-assistant">
          <span className="assistant-orb">
            <Sparkles size={18} />
          </span>
          <Eyebrow>PLAN B ASSISTANT</Eyebrow>
          <h2>Your schedule is tight after the team meeting.</h2>
          <p>
            I can preserve deadlines by moving one flexible block and leaving
            fixed events untouched.
          </p>
          <div className="impact-list">
            <b>Proposed impact</b>
            <span>
              <Check size={13} /> Deadlines revalidated
            </span>
            <span>
              <Check size={13} /> Fixed events protected
            </span>
            <span>
              <Check size={13} /> No change before approval
            </span>
          </div>
          <Button primary className="wide" onClick={() => onRecovery()}>
            Preview proposed moves <ArrowRight size={14} />
          </Button>
          <button
            className="text-action"
            onClick={() => sendMessage("Explain the calendar risks for today")}
          >
            Ask the assistant to explain
          </button>
        </div>
      </div>
      {selectedDay && (
        <CalendarDetail
          title={selectedDay.label}
          blocks={selectedDay.blocks}
          close={() => setSelectedDay(null)}
          onRecovery={onRecovery}
        />
      )}
      {selectedBlock && (
        <EventDetail
          block={selectedBlock}
          close={() => setSelectedBlock(null)}
        />
      )}
    </View>
  );
}

function CalendarDetail({ title, blocks, close, onRecovery }) {
  const total = blocks.reduce(
    (sum, block) => sum + (block.minutes || block.duration_minutes || 0),
    0,
  );
  const focus = blocks
    .filter((block) => block.kind === "focus" || block.kind === "risk")
    .reduce((sum, block) => sum + block.minutes, 0);
  const fixed = blocks
    .filter((block) => block.kind === "fixed")
    .reduce((sum, block) => sum + block.minutes, 0);
  const free = Math.max(0, 720 - total);
  return (
    <div className="modal-backdrop">
      <div className="calendar-detail-modal">
        <button className="close" onClick={close}>
          <X size={18} />
        </button>
        <Eyebrow>DAY DETAILS</Eyebrow>
        <h2>{title}, October 2026</h2>
        <p>
          {blocks.length} scheduled items · {(total / 60).toFixed(1)} planned
          hours
        </p>
        <div className="day-breakdown">
          <div
            className="breakdown-ring"
            style={{ "--used": `${Math.min(100, total / 7.2)}%` }}
          >
            <span>
              <strong>{Math.round((total / 60) * 10) / 10}h</strong>
              <small>planned</small>
            </span>
          </div>
          <div>
            <BreakdownRow
              name="Focus work"
              value={focus}
              total={720}
              color="#e4794c"
            />
            <BreakdownRow
              name="Fixed events"
              value={fixed}
              total={720}
              color="#657c9a"
            />
            <BreakdownRow
              name="Free capacity"
              value={free}
              total={720}
              color="#71886b"
            />
          </div>
        </div>
        <div className="day-agenda">
          {blocks.map((block, index) => (
            <div key={`${block.task_id || block.id}-${index}`}>
              <span>{block.start || "Flexible"}</span>
              <i
                style={{
                  background:
                    block.kind === "fixed"
                      ? "#657c9a"
                      : block.kind === "risk"
                        ? "#e4794c"
                        : "#71886b",
                }}
              />
              <div>
                <b>{block.title}</b>
                <small>
                  {block.minutes || block.duration_minutes} minutes ·{" "}
                  {block.label || block.priority}
                </small>
              </div>
            </div>
          ))}
        </div>
        <footer>
          <Button onClick={close}>Close</Button>
          <Button
            primary
            onClick={() => {
              close();
              onRecovery(30, `${title} schedule changed`);
            }}
          >
            Replan this day <ArrowRight size={14} />
          </Button>
        </footer>
      </div>
    </div>
  );
}
function BreakdownRow({ name, value, total, color }) {
  return (
    <div className="breakdown-row">
      <header>
        <b>{name}</b>
        <span>{value} min</span>
      </header>
      <i>
        <em
          style={{
            width: `${Math.min(100, (value / total) * 100)}%`,
            background: color,
          }}
        />
      </i>
    </div>
  );
}
function EventDetail({ block, close }) {
  return (
    <div className="modal-backdrop">
      <div className="event-detail">
        <button className="close" onClick={close}>
          <X size={18} />
        </button>
        <span className={`event-icon ${block.kind}`}>
          <Clock3 size={19} />
        </span>
        <Eyebrow>{block.label || block.priority}</Eyebrow>
        <h2>{block.title}</h2>
        <p>{block.detail || "Flexible task in this planning window."}</p>
        <dl>
          <div>
            <dt>Time</dt>
            <dd>
              {block.start || "Flexible"}
              {block.end ? `–${block.end}` : ""}
            </dd>
          </div>
          <div>
            <dt>Duration</dt>
            <dd>{block.minutes || block.duration_minutes} minutes</dd>
          </div>
          <div>
            <dt>Deadline</dt>
            <dd>
              {block.deadline
                ? new Date(block.deadline).toLocaleString()
                : "No hard deadline"}
            </dd>
          </div>
        </dl>
        <Button primary className="wide" onClick={close}>
          Done <Check size={14} />
        </Button>
      </div>
    </div>
  );
}

function TasksView({
  tasks,
  projects,
  onAdd,
  onAddProject,
  onEdit,
  onPatch,
  onEditProject,
  onPatchProject,
}) {
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("open");
  const [sort, setSort] = useState("deadline");
  const [layout, setLayout] = useState("list");
  const [content, setContent] = useState("tasks");
  const [numbering, setNumbering] = useState(true);
  const [projectFilter, setProjectFilter] = useState("all");
  const visible = useMemo(
    () =>
      tasks
        .filter((task) => status === "all" || task.status === status)
        .filter((task) =>
          task.title.toLowerCase().includes(query.toLowerCase()),
        )
        .sort((a, b) =>
          sort === "priority"
            ? { high: 0, medium: 1, low: 2 }[a.priority] -
              { high: 0, medium: 1, low: 2 }[b.priority]
            : sort === "project"
              ? String(a.project_id || "").localeCompare(
                  String(b.project_id || ""),
                )
              : String(a.deadline || "9999").localeCompare(
                  String(b.deadline || "9999"),
                ),
        ),
    [tasks, query, status, sort],
  );
  const filtered =
    projectFilter === "all"
      ? visible
      : visible.filter((task) => task.project_id === projectFilter);
  return (
    <View id="tasks">
      <div className="section-head">
        <div>
          <Eyebrow>YOUR COMMITMENTS</Eyebrow>
          <h1>Projects & tasks</h1>
          <p>
            Organize workspaces, switch views and manage every scheduling
            constraint.
          </p>
        </div>
        <div className="hero-buttons">
          <Button onClick={onAddProject}>
            <FolderKanban size={15} /> Add project
          </Button>
          <Button primary onClick={onAdd}>
            <Plus size={15} /> Add task
          </Button>
        </div>
      </div>
      <div className="content-switch">
        <button
          className={content === "tasks" ? "active" : ""}
          onClick={() => setContent("tasks")}
        >
          <ListTodo size={15} /> Tasks <b>{tasks.length}</b>
        </button>
        <button
          className={content === "projects" ? "active" : ""}
          onClick={() => setContent("projects")}
        >
          <FolderKanban size={15} /> Projects <b>{projects.length}</b>
        </button>
      </div>
      {content === "projects" ? (
        <div className={`projects-view ${layout}`}>
          <div className="project-controls">
            <span>{projects.length} active projects</span>
            <div className="layout-toggle">
              <button
                className={layout === "list" ? "active" : ""}
                onClick={() => setLayout("list")}
              >
                <LayoutList size={15} />
              </button>
              <button
                className={layout === "board" ? "active" : ""}
                onClick={() => setLayout("board")}
              >
                <Columns3 size={15} />
              </button>
            </div>
          </div>
          {projects.map((project, index) => (
            <div className="panel project-card" key={project.id}>
              <span
                className="project-number"
                style={{ background: project.color }}
              >
                {String(index + 1).padStart(2, "0")}
              </span>
              <div>
                <h3>{project.name}</h3>
                <p>{project.description}</p>
                <div className="project-bar">
                  <i
                    style={{
                      width: `${project.progress}%`,
                      background: project.color,
                    }}
                  />
                </div>
                <small>
                  {project.completed_count}/{project.task_count} tasks complete
                  · {project.planned_minutes} planned minutes
                </small>
              </div>
              <div className="hero-buttons">
                <button
                  type="button"
                  onClick={() => onEditProject(project)}
                  title="Edit project"
                >
                  <Pencil size={14} />
                </button>
                <button
                  type="button"
                  onClick={() =>
                    onPatchProject(project.id, { status: "archived" })
                  }
                  title="Archive project"
                >
                  <Archive size={14} />
                </button>
                <strong>{project.progress}%</strong>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <>
          <div className="task-toolbar">
            <label>
              <Search size={15} />
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Search tasks"
              />
            </label>
            <select
              value={projectFilter}
              onChange={(event) => setProjectFilter(event.target.value)}
            >
              <option value="all">All projects</option>
              {projects.map((project) => (
                <option value={project.id} key={project.id}>
                  {project.name}
                </option>
              ))}
            </select>
            <select
              value={status}
              onChange={(event) => setStatus(event.target.value)}
            >
              <option value="open">Open</option>
              <option value="done">Completed</option>
              <option value="all">All statuses</option>
            </select>
            <select
              value={sort}
              onChange={(event) => setSort(event.target.value)}
            >
              <option value="deadline">Sort by deadline</option>
              <option value="priority">Sort by priority</option>
              <option value="project">Group by project</option>
            </select>
            <label className="number-toggle">
              <input
                type="checkbox"
                checked={numbering}
                onChange={(event) => setNumbering(event.target.checked)}
              />{" "}
              Numbering
            </label>
            <div className="layout-toggle">
              <button
                className={layout === "list" ? "active" : ""}
                onClick={() => setLayout("list")}
              >
                <LayoutList size={15} />
              </button>
              <button
                className={layout === "board" ? "active" : ""}
                onClick={() => setLayout("board")}
              >
                <Columns3 size={15} />
              </button>
            </div>
          </div>
          <div className={`panel task-table ${layout}`}>
            <div className="task-table-head">
              <span>Task</span>
              <span>Project</span>
              <span>Deadline</span>
              <span>Status</span>
              <span>Priority</span>
              <span>Duration</span>
              <span />
            </div>
            {filtered.map((task, index) => {
              const project = projects.find(
                (item) => item.id === task.project_id,
              );
              return (
                <div className="task-table-row" key={task.id}>
                  {numbering && (
                    <span className="row-number">
                      {String(index + 1).padStart(2, "0")}
                    </span>
                  )}
                  <div>
                    <button
                      className={`task-check ${task.status === "done" ? "done" : ""}`}
                      onClick={() =>
                        onPatch(task.id, {
                          status: task.status === "done" ? "open" : "done",
                          actual_minutes:
                            task.status === "done"
                              ? null
                              : task.duration_minutes,
                        })
                      }
                    >
                      {task.status === "done" && <Check size={12} />}
                    </button>
                    <span>
                      <b>{task.title}</b>
                      <small>
                        {task.tags?.join(" · ") || task.flexibility}
                      </small>
                    </span>
                  </div>
                  <span className="project-cell">
                    <i style={{ background: project?.color }} />
                    {project?.name || "Inbox"}
                  </span>
                  <span>
                    {task.deadline
                      ? new Date(task.deadline).toLocaleString([], {
                          month: "short",
                          day: "numeric",
                          hour: "numeric",
                          minute: "2-digit",
                        })
                      : "No deadline"}
                  </span>
                  <em className={`status-pill ${task.status}`}>
                    {task.status}
                  </em>
                  <em className={`priority-pill ${task.priority}`}>
                    {task.priority}
                  </em>
                  <b>{task.duration_minutes} min</b>
                  <aside>
                    <button onClick={() => onEdit(task)} title="Edit">
                      <Pencil size={14} />
                    </button>
                    <button
                      onClick={() => onPatch(task.id, { status: "archived" })}
                      title="Archive"
                    >
                      <Archive size={14} />
                    </button>
                  </aside>
                </div>
              );
            })}
            {!filtered.length && (
              <div className="empty-row">
                <ListFilter size={22} /> No tasks match these filters.
              </div>
            )}
          </div>
        </>
      )}
    </View>
  );
}

function AssistantView({
  messages,
  activity,
  lastTurn,
  sendMessage,
  onUndo,
  preferences,
  busy,
  queueSize,
}) {
  const [input, setInput] = useState("");
  const [assistantMode, setAssistantMode] = useState("command");
  const messagesRef = useRef(null);
  const voice = useVoiceSession();
  const lastAssistantId = [...messages].reverse().find((message) => message.role === "assistant")?.id;
  const submit = () => {
    if (!input.trim()) return;
    voice.submit(input, "text");
    setInput("");
  };
  const send = (text) => voice.submit(text, "text");
  useEffect(() => {
    const pane = messagesRef.current;
    if (!pane) return;
    pane.scrollTo({ top: pane.scrollHeight, behavior: "smooth" });
  }, [messages, busy, voice.phase]);
  return (
    <View id="assistant">
      <div className="section-head">
        <div>
          <Eyebrow>YOUR PLANNING COMPANION</Eyebrow>
          <h1>Plan B command centre</h1>
          <p>Talk naturally, preview real actions, and control every planning workflow.</p>
        </div>
        <span className="provider">● Every change can be undone</span>
      </div>
      <div className="assistant-modebar">
        {[
          ["command", "Command", "Create, move, open or complete"],
          ["conversation", "Plan together", "Reason through priorities and trade-offs"],
          ["dictation", "Dictate", "Capture a complete thought before sending"],
        ].map(([id, label, description]) => (
          <button
            className={assistantMode === id ? "active" : ""}
            onClick={() => setAssistantMode(id)}
            aria-pressed={assistantMode === id}
            key={id}
          >
            <b>{label}</b><small>{description}</small>
          </button>
        ))}
      </div>
      <div className="assistant-layout">
        <div className="panel chat">
          <div className="chat-head">
            <span className="bot">
              <Sparkles size={16} />
            </span>
            <div>
              <b>Plan B</b>
              <small>Schedule-aware recovery agent</small>
            </div>
            <span className="private">◈ private by design</span>
          </div>
          <div className="messages" ref={messagesRef}>
            {messages.map((message, index) => (
              <div className={`message ${message.role}`} key={message.id || index}>
                {message.role === "assistant" && (
                  <span className="message-icon">✦</span>
                )}
                <div>
                  <p>{message.text}</p>
                  {message.turn && (
                    <TurnDetails
                      turn={message.id === lastAssistantId ? message.turn : { ...message.turn, choices: [] }}
                      metrics={message.id === lastAssistantId ? voice.metrics : null}
                      onSend={send}
                      onUndo={onUndo}
                      disabled={busy}
                      showSteps={message.turn.steps?.length > 1}
                    />
                  )}
                  <small>
                    {message.role === "assistant"
                      ? ["Plan B", message.understood || message.meta?.understood].filter(Boolean).join(" · ")
                      : message.status || "You · now"}
                  </small>
                </div>
              </div>
            ))}
            {(busy || voice.busy) && (
              <div className="message assistant pending-message">
                <span className="message-icon">✦</span>
                <div><span className="thinking-dots"><i /><i /><i /></span><p>{voice.ack || "One moment…"}</p><small>{queueSize ? `${queueSize} more message${queueSize === 1 ? "" : "s"} queued` : "Working now"}</small></div>
              </div>
            )}
            {voice.error && (
              <div className="message assistant voice-error" role="alert">
                <span className="message-icon">!</span>
                <div>
                  <p>{voice.error.message}</p>
                  {voice.error.recoverable && <button onClick={voice.retry}><RotateCcw size={13} /> Retry</button>}
                </div>
              </div>
            )}
            <div className="messages-end" />
          </div>
          <div className="suggestions">
            {[
              assistantMode === "command" ? "Create a 45 minute task tomorrow at 10 AM" : "My meeting is running 45 minutes late",
              assistantMode === "dictation" ? "Capture a detailed task description" : "Can I still finish everything today?",
              assistantMode === "command" ? "Open my calendar and show conflicts" : "Give me the shortest realistic plan",
            ].map((text) => (
              <button onClick={() => send(text)} key={text}>
                {text}
              </button>
            ))}
          </div>
          <div className="composer">
            <button
              className={voice.active ? "listening" : ""}
              onClick={voice.toggle}
              disabled={busy || preferences?.voice_input === false}
              aria-label={voice.active ? "Stop listening" : "Speak to Plan B"}
              title={voice.supported ? voice.label : "Voice input isn't available in this browser"}
            >
              <Mic size={17} />
            </button>
            <input
              value={voice.active ? voice.interim : input}
              readOnly={voice.active}
              onChange={(event) => setInput(event.target.value)}
              onKeyDown={(event) => event.key === "Enter" && submit()}
              placeholder={
                voice.active ? "Listening… pause when you're done" : "Tell Plan B what changed…"
              }
            />
            <button className="send" onClick={submit} disabled={!input.trim()}>
              <ArrowRight size={15} />
            </button>
          </div>
          <small className="note">
            Changes are previewed first, and anything applied can be undone.
          </small>
        </div>
        <div className="panel activity-panel">
          <PanelHeading
            title="What Plan B did"
            sub={lastTurn?.understood || "Your latest request, step by step"}
          />
          {activity.length ? (
            <StepTimeline steps={activity} />
          ) : (
            <p className="no-tool-activity">Nothing has run yet. Ask a question or tell Plan B what changed.</p>
          )}
          {lastTurn?.undo && (
            <button className="ghost undo-latest" onClick={() => onUndo(lastTurn.undo.action_id)} disabled={busy}>
              <RotateCcw size={13} /> Undo “{lastTurn.undo.label}”
            </button>
          )}
          <div className="assistant-context-card">
            <small>WHAT PLAN B CAN CONTROL</small>
            <div><span>Tasks</span><span>Calendar</span><span>Projects</span><span>Navigation</span><span>Recovery</span><span>Insights</span></div>
            <p>Questions are answered right away. Changes wait for your OK, and you can say “undo that” afterwards.</p>
          </div>
        </div>
      </div>
    </View>
  );
}

function RecoveryView({ data, history, approve, restore, generate }) {
  const [selected, setSelected] = useState(null);
  const [compare, setCompare] = useState("proposed");
  const [disruption, setDisruption] = useState({ minutes: 30, reason: "My schedule changed" });
  useEffect(() => {
    setSelected(data?.recommended_option_id || null);
  }, [data]);
  const option =
    data?.options.find((item) => item.id === selected) || data?.options[0];
  const shownBlocks =
    compare === "original" ? data?.original_blocks : option?.revised_blocks;
  return (
    <View id="recovery">
      <div className="section-head">
        <div>
          <Eyebrow>SAFE REPLANNING WORKSPACE</Eyebrow>
          <h1>
            Rescue my day{" "}
            <em>{data ? "Needs your decision" : "Ready when needed"}</em>
          </h1>
          <p>
            Tell Plan B what changed, compare the impact, and approve an exact recovery plan.
          </p>
        </div>
        <Button onClick={() => generate(disruption.minutes, disruption.reason)}>
          <RotateCcw size={14} /> New recovery
        </Button>
      </div>
      {!data ? (
        <div className="empty-recovery">
          <RotateCcw size={28} />
          <h2>What changed?</h2>
          <p>Plan B will protect fixed commitments and deadlines before moving flexible work.</p>
          <div className="recovery-capture">
            <label>Describe the disruption<input value={disruption.reason} onChange={(event) => setDisruption({ ...disruption, reason: event.target.value })} placeholder="My meeting ran late" /></label>
            <label>Time lost<input type="number" min="5" max="480" step="5" value={disruption.minutes} onChange={(event) => setDisruption({ ...disruption, minutes: Number(event.target.value) })} /><span>minutes</span></label>
          </div>
          <Button primary onClick={() => generate(disruption.minutes, disruption.reason)}>
            Calculate safe options
          </Button>
        </div>
      ) : (
        <>
          <div className="recovery-alert">
            <RotateCcw size={21} />
            <div>
              <b>
                Impact detected · {data.disruption_minutes} minutes lost ·{" "}
                {data.options.filter((item) => item.feasible).length} feasible
                options
              </b>
              <p>{data.affected_tasks.length ? `Affected work: ${data.affected_tasks.join(", ")}` : "No task needs to move."}</p>
            </div>
          </div>
          <div className="recovery-layout">
            <div>
              <h2 className="sub-title">Compare your options</h2>
              {data.options.map((item, index) => (
                <div
                  className={`option ${selected === item.id ? "selected" : ""}`}
                  key={item.id}
                  onClick={() => setSelected(item.id)}
                >
                  <header>
                    <span>{String.fromCharCode(65 + index)}</span>
                    <div>
                      <h3>{item.title}</h3>
                      <small className={item.feasible ? "feasible" : "needs"}>
                        {item.feasible
                          ? `${item.id === data.recommended_option_id ? "Recommended · " : ""}Feasible`
                          : "Constraint change required"}
                      </small>
                    </div>
                    <b>{selected === item.id ? "✓" : "○"}</b>
                  </header>
                  <p>{item.description}</p>
                  <div className="tradeoff">
                    <b>Trade-off</b>
                    {item.tradeoff}
                  </div>
                </div>
              ))}
            </div>
            <div className="panel revised">
              <PanelHeading
                title="Schedule comparison"
                sub={`${option?.validation.checked.length || 0} deterministic checks`}
              />
              <div className="compare-switch">
                <button
                  className={compare === "original" ? "active" : ""}
                  onClick={() => setCompare("original")}
                >
                  Before
                </button>
                <button
                  className={compare === "proposed" ? "active" : ""}
                  onClick={() => setCompare("proposed")}
                >
                  Proposed
                </button>
              </div>
              <span className="validated">
                <Check size={12} />{" "}
                {option?.feasible ? "Validated feasible" : "Not feasible yet"}
              </span>
              <div className="revised-block-list">
              {shownBlocks?.map((block) => (
                <div
                  className="revised-block"
                  key={`${block.task_id}-${block.start_iso}`}
                >
                  <small>
                    {block.start}–{block.end}
                  </small>
                  <b>{block.title}</b>
                  <span>{block.detail}</span>
                </div>
              ))}
              </div>
              <div className="approval">
                <b>
                  {option?.feasible
                    ? "Ready to apply?"
                    : "This option cannot be applied"}
                </b>
                <small>
                  The selected proposal is rechecked and saved as a new version.
                </small>
                <Button
                  primary
                  disabled={!option?.feasible}
                  onClick={() => approve(option.id)}
                  className="wide"
                >
                  Approve selected plan <ArrowRight size={14} />
                </Button>
              </div>
            </div>
          </div>
        </>
      )}
      <HistoryList history={history} restore={restore} />
    </View>
  );
}
function HistoryList({ history, restore }) {
  return (
    <div className="history-section">
      <div className="section-head compact-head">
        <div>
          <Eyebrow>AUDIT TRAIL</Eyebrow>
          <h2>Plan history</h2>
        </div>
      </div>
      <div className="history-list">
        {history.length ? (
          history.map((item) => (
            <div className="history-card" key={item.id}>
              <span className={`history-state ${item.status}`}>
                {item.status}
              </span>
              <div>
                <b>
                  Plan v{item.version} · {item.reason}
                </b>
                <small>{new Date(item.created_at).toLocaleString()}</small>
              </div>
              <button onClick={() => restore(item.id)}>
                <History size={14} /> Restore
              </button>
            </div>
          ))
        ) : (
          <p className="muted">No plan versions yet.</p>
        )}
      </div>
    </div>
  );
}

function PatternsView({ data: initialData, onDiscuss }) {
  const [data, setData] = useState(initialData);
  const [days, setDays] = useState(initialData?.range_days || 7);
  useEffect(() => {
    setData(initialData);
    setDays(initialData?.range_days || 7);
  }, [initialData]);
  const activity = data?.activity || [];
  const labels = data?.week_labels || [];
  const timeTrend = data?.time_trend || [];
  const focusTrend = data?.focus_trend || [];
  const insights = useMemo(() => {
    if (!data) return [];
    const items = [];
    const completion = Number(data.completion_rate || 0);
    const focus = Number(data.focus_score || 0);
    const balance = Number(data.balance_score || 0);
    items.push({
      tone: completion >= 70 ? "good" : "attention",
      label: "Delivery",
      title: completion >= 70 ? "Your commitments are landing consistently" : "Your plan is carrying more than you finish",
      evidence: `${completion}% of tracked commitments were completed in this period.`,
      action: completion >= 70 ? "Protect this completion rhythm" : "Reduce my daily workload using this completion rate",
    });
    items.push({
      tone: focus >= 65 ? "good" : "attention",
      label: "Focus",
      title: focus >= 65 ? "Protected focus is working" : "Focus time is too fragmented",
      evidence: `Your focus quality score is ${focus}/100 across the selected range.`,
      action: focus >= 65 ? "Find my strongest focus window" : "Create longer protected focus blocks",
    });
    items.push({
      tone: balance >= 65 ? "good" : "attention",
      label: "Balance",
      title: balance >= 65 ? "Your work mix is sustainable" : "Your schedule needs a healthier mix",
      evidence: `Your balance score is ${balance}/100 based on focus, fixed work and buffers.`,
      action: balance >= 65 ? "Keep this balance in next week’s plan" : "Rebalance my next seven days",
    });
    const inaccurate = data.categories?.find((item) => Math.abs(item.delta) >= 15);
    if (inaccurate) items.push({ tone: "attention", label: "Estimates", title: `${inaccurate.name} estimates need calibration`, evidence: `Actual time differs from estimates by ${inaccurate.delta > 0 ? "+" : ""}${inaccurate.delta} minutes on average.`, action: `Adjust future ${inaccurate.name} estimates using this pattern` });
    return items.slice(0, 4);
  }, [data]);
  const points = (values, max = 100) =>
    values
      .map(
        (value, index) =>
          `${index * (100 / Math.max(1, values.length - 1))},${100 - (value / max) * 85}`,
      )
      .join(" ");
  return (
    <View id="patterns">
      <div className="section-head">
        <div>
          <Eyebrow>LEARN FROM REALITY</Eyebrow>
          <h1>Insights</h1>
          <p>
            Understand what Plan B learned, why it matters, and what you can improve next.
          </p>
        </div>
        <Button
          onClick={async () => {
            const next = days === 7 ? 30 : 7;
            setDays(next);
            setData(await api(`/patterns?days=${next}`));
          }}
        >
          <TrendingUp size={14} /> Last {days} days
        </Button>
      </div>
      <div className="insight-explainer">
        <div><Sparkles size={17} /><span><b>Your planning intelligence</b><small>Every insight below is calculated from your tasks, scheduled time and completed work—not generic advice.</small></span></div>
        <button onClick={() => onDiscuss("Explain my productivity insights in simple language")}>Ask Plan B to explain</button>
      </div>
      <div className="actionable-insights">
        {insights.map((item) => (
          <article className={item.tone} key={`${item.label}-${item.title}`}>
            <small>{item.label}</small><h3>{item.title}</h3><p>{item.evidence}</p>
            <button onClick={() => onDiscuss(`${item.action}. Explain the evidence and preview any changes before applying them.`)}>{item.action} <ArrowRight size={13} /></button>
          </article>
        ))}
      </div>
      <div className="analytics-metrics">
        <Metric
          label="Task progress"
          value={data?.completion_rate || 0}
          unit="%"
          note="completed commitments"
        />
        <Metric
          label="Focus score"
          value={data?.focus_score || 0}
          unit="/100"
          note="quality of protected work"
          good
        />
        <Metric
          label="Balance"
          value={data?.balance_score || 0}
          unit="/100"
          note="focus vs fixed work"
        />
        <Metric
          label="Tracked time"
          value={data?.scheduled_hours || 0}
          unit="hrs"
          note="scheduled workload"
        />
      </div>
      <div className="analytics-board">
        <div className="panel trend-card wide-card">
          <PanelHeading
            title="Time trends"
            sub={
              data?.history_note ||
              "Recorded completion hours across the selected range"
            }
          />
          <svg
            className="line-chart"
            viewBox="0 0 100 100"
            preserveAspectRatio="none"
          >
            <polyline points={points(timeTrend, 7)} />
          </svg>
          <div className="chart-labels">
            {labels.map((label, index) => (
              <span key={`${label}-${index}`}>{label}</span>
            ))}
          </div>
        </div>
        <div
          className="panel compact-ring"
          style={{ "--score": `${data?.completion_rate || 0}%` }}
        >
          <PanelHeading title="Task progress" sub="Completion" />
          <span>
            <strong>{data?.completion_rate || 0}%</strong>
          </span>
          <small>{data?.sample_size || 0} timed completions recorded</small>
        </div>
        <div className="panel goals-card">
          <PanelHeading
            title="Goals progress"
            sub="Projects as measurable outcomes"
          />
          {data?.goals?.map((goal) => (
            <div className="goal-row" key={goal.name}>
              <header>
                <b>{goal.name}</b>
                <span>{goal.progress}%</span>
              </header>
              <i>
                <em style={{ width: `${goal.progress}%` }} />
              </i>
              <small>
                {goal.target_date
                  ? `Target ${new Date(goal.target_date).toLocaleDateString([], { month: "short", day: "numeric" })}`
                  : "Ongoing goal"}
              </small>
            </div>
          ))}
        </div>
        <div className="panel activity-chart">
          <PanelHeading title="Activity" sub="Relative productive load" />
          <div className="chart-bars compact">
            {activity.map((value, index) => (
              <div key={`${labels[index]}-${index}`}>
                <i style={{ height: `${value}%` }} />
                <small>{labels[index]}</small>
              </div>
            ))}
          </div>
        </div>
        <div className="panel trend-card">
          <PanelHeading
            title="Progress & focus score"
            sub="Focus quality trend"
          />
          <svg
            className="line-chart focus"
            viewBox="0 0 100 100"
            preserveAspectRatio="none"
          >
            <polyline points={points(focusTrend)} />
          </svg>
          <div className="chart-labels">
            {labels.map((label, index) => (
              <span key={`focus-${label}-${index}`}>{label}</span>
            ))}
          </div>
        </div>
        <div
          className="panel compact-ring balance"
          style={{ "--score": `${data?.balance_score || 0}%` }}
        >
          <PanelHeading title="Balance" sub="Work mix" />
          <span>
            <strong>{data?.balance_score || 0}</strong>
          </span>
          <small>Healthy variety across focus, meetings and admin.</small>
        </div>
        <div className="panel breakdown-card">
          <PanelHeading
            title="Time & focus breakdown"
            sub="Where scheduled minutes go"
          />
          {data?.time_breakdown?.map((item) => (
            <BreakdownRow
              name={item.name}
              value={item.minutes}
              total={Math.max(
                1,
                data.time_breakdown.reduce(
                  (sum, entry) => sum + entry.minutes,
                  0,
                ),
              )}
              color={item.color}
              key={item.name}
            />
          ))}
        </div>
        <div className="panel pattern-chart">
          <PanelHeading
            title="Estimate accuracy"
            sub={
              data?.sample_size
                ? `${data.sample_size} completed tasks`
                : "Early benchmark"
            }
          />
          {data?.categories?.length ? (
            data.categories.map((item) => (
              <div className="bar" key={item.name}>
                <span>{item.name}</span>
                <i
                  style={{
                    width: `${Math.min(90, 35 + Math.abs(item.delta) * 2)}%`,
                  }}
                />
                <b>
                  {item.delta > 0 ? "+" : ""}
                  {item.delta}m
                </b>
              </div>
            ))
          ) : (
            <p className="muted">
              Complete tasks with actual minutes to see estimate accuracy.
            </p>
          )}
        </div>
      </div>
    </View>
  );
}

function McpView({ notify }) {
  const [tools, setTools] = useState([]);
  const [selected, setSelected] = useState("check_deadline_risks");
  const [args, setArgs] = useState("{}");
  const [result, setResult] = useState(null);
  const [running, setRunning] = useState(false);
  useEffect(() => {
    api("/mcp/tools")
      .then((data) => setTools(data.tools))
      .catch((error) => notify("MCP unavailable", error.message));
  }, []);
  const run = async () => {
    setRunning(true);
    try {
      const output = await api("/mcp/call", {
        method: "POST",
        body: JSON.stringify({
          name: selected,
          arguments: JSON.parse(args || "{}"),
        }),
      });
      setResult(JSON.parse(output.content[0].text));
    } catch (error) {
      notify("Tool call failed", error.message);
    } finally {
      setRunning(false);
    }
  };
  return (
    <View id="mcp">
      <div className="section-head">
        <div>
          <Eyebrow>DEVELOPER WORKBENCH</Eyebrow>
          <h1>MCP tools</h1>
          <p>
            Inspect and invoke the same allowlisted tools used by the agent.
          </p>
        </div>
        <span className="provider">● Streamable HTTP ready</span>
      </div>
      <div className="mcp-layout">
        <div className="panel tool-list">
          <h2>
            Tool registry <em>{tools.length}</em>
          </h2>
          {tools.map((tool) => (
            <button
              className={selected === tool.name ? "active" : ""}
              onClick={() => {
                setSelected(tool.name);
                setArgs(
                  tool.name.includes("recovery") ||
                    tool.name === "find_affected_tasks"
                    ? '{\n  "disruption_minutes": 45,\n  "reason": "Meeting overrun"\n}'
                    : "{}",
                );
              }}
              key={tool.name}
            >
              <Code2 size={14} />
              <span>
                <b>{tool.name}</b>
                <small>{tool.description}</small>
              </span>
              <ChevronRight size={14} />
            </button>
          ))}
        </div>
        <div className="panel tool-runner">
          <PanelHeading
            title="Tool inspector"
            sub="Calls local API/MCP adapter"
          />
          <label>
            Selected tool
            <input value={selected} readOnly />
          </label>
          <label>
            JSON arguments
            <textarea
              value={args}
              onChange={(event) => setArgs(event.target.value)}
              rows="8"
            />
          </label>
          <Button primary onClick={run} disabled={running}>
            {running ? (
              <Loader2 className="spin" size={14} />
            ) : (
              <Zap size={14} />
            )}{" "}
            Run tool
          </Button>
          <div className="tool-output">
            <b>Result</b>
            <pre>
              {result
                ? JSON.stringify(result, null, 2)
                : "Run a tool to inspect its structured response."}
            </pre>
          </div>
        </div>
      </div>
    </View>
  );
}

function SettingsView({
  preferences,
  provider,
  save,
  openSetup,
  notify,
  onProviderChanged,
}) {
  const [form, setForm] = useState(preferences);
  const [tab, setTab] = useState("General");
  const [testing, setTesting] = useState(false);
  const [switching, setSwitching] = useState("");
  useEffect(() => {
    setForm(preferences);
  }, [preferences]);
  if (!form) return null;
  const field = (name, value) =>
    setForm((current) => ({ ...current, [name]: value }));
  const testProvider = async () => {
    setTesting(true);
    try {
      const result = await api("/provider/test", { method: "POST" });
      notify("NVIDIA model connected", `${result.model}: ${result.reply}`);
    } catch (error) {
      notify("Provider test failed", error.message);
    } finally {
      setTesting(false);
    }
  };
  const switchModel = async (model) => {
    if (model === provider?.model || switching) return;
    setSwitching(model);
    try {
      const result = await api("/provider/model", {
        method: "PUT",
        body: JSON.stringify({ model }),
      });
      notify(
        "Active model changed",
        `${result.model} passed a live compatibility test.`,
      );
      await onProviderChanged();
    } catch (error) {
      notify("Model switch failed", error.message);
    } finally {
      setSwitching("");
    }
  };
  return (
    <View id="settings">
      <div className="section-head">
        <div>
          <Eyebrow>YOUR RULES, YOUR CONTROL</Eyebrow>
          <h1>Settings</h1>
          <p>
            Constraints persist on the backend; provider secrets stay
            server-side.
          </p>
        </div>
        <div className="hero-buttons">
          <Button onClick={openSetup}>Run setup</Button>
          <Button primary onClick={() => save(form)}>
            Save changes
          </Button>
        </div>
      </div>
      <div className="settings-tabs">
        {["General", "AI & Models", "Voice", "Connections"].map((item) => (
          <button
            className={tab === item ? "active" : ""}
            onClick={() => setTab(item)}
            key={item}
          >
            {item}
          </button>
        ))}
      </div>
      <div className="settings-grid">
        {tab === "General" && (
          <div className="panel settings span-two">
            <h2>Planning preferences</h2>
            <label>
              Display name
              <input
                value={form.display_name}
                onChange={(event) => field("display_name", event.target.value)}
              />
            </label>
            <label>
              Planning style
              <select
                value={form.planning_style}
                onChange={(event) =>
                  field("planning_style", event.target.value)
                }
              >
                <option value="realistic">
                  Realistic — leave room to breathe
                </option>
                <option value="balanced">Balanced</option>
                <option value="ambitious">Ambitious</option>
              </select>
            </label>
            <div className="inline">
              <label>
                Day starts
                <input
                  type="time"
                  value={form.day_start}
                  onChange={(event) => field("day_start", event.target.value)}
                />
              </label>
              <label>
                Day ends
                <input
                  type="time"
                  value={form.day_end}
                  onChange={(event) => field("day_end", event.target.value)}
                />
              </label>
            </div>
            <div className="inline">
              <label>
                Default buffer
                <input
                  type="number"
                  min="0"
                  value={form.default_buffer_minutes}
                  onChange={(event) =>
                    field("default_buffer_minutes", Number(event.target.value))
                  }
                />
              </label>
              <label>
                Language
                <input
                  value={form.language}
                  onChange={(event) => field("language", event.target.value)}
                />
              </label>
            </div>
          </div>
        )}
        {tab === "AI & Models" && (
          <>
            <div className="panel settings">
              <h2>Active NVIDIA provider</h2>
              <Connection
                icon={<Sparkles size={15} />}
                title={provider?.provider || "Deterministic engine"}
                detail={provider?.model || "No external model configured"}
                state={provider?.configured ? "Connected" : "Fallback active"}
              />
              <Button
                primary
                className="wide provider-test"
                disabled={testing || !provider?.configured}
                onClick={testProvider}
              >
                {testing ? (
                  <Loader2 className="spin" size={14} />
                ) : (
                  <Zap size={14} />
                )}{" "}
                Test live model
              </Button>
              <p className="security">
                <ShieldCheck size={14} /> Your NVIDIA key stays in backend/.env
                and is never returned to the browser.
              </p>
            </div>
            <div className="panel settings">
              <h2>NVIDIA model catalog</h2>
              <div className="provider-catalog">
                {provider?.catalog?.map((name) => (
                  <span
                    className={name === provider?.model ? "selected" : ""}
                    key={name}
                  >
                    {name}
                  </span>
                ))}
              </div>
            </div>
          </>
        )}
        {tab === "Voice" && (
          <div className="panel settings span-two">
            <h2>Voice experience</h2>
            <Toggle
              text="Voice input"
              detail="Browser speech today; Wispr Flow adapter can be connected later"
              active={form.voice_input}
              onChange={(value) => field("voice_input", value)}
            />
            <Toggle
              text="Voice replies"
              detail="Saved for later. Spoken replies are not available yet."
              active={form.voice_output}
              onChange={(value) => field("voice_output", value)}
            />
            <Connection
              icon={<Mic size={15} />}
              title="Speech recognition"
              detail={provider?.voice.asr || "browser"}
              state="Ready"
            />
          </div>
        )}
        {tab === "Connections" && (
          <div className="panel settings span-two">
            <h2>Connections</h2>
            <Connection
              icon={<Command size={15} />}
              title="MCP server"
              detail={`${provider?.mcp.tools || 10} allowlisted tools · Streamable HTTP`}
              state={provider?.mcp.status || "Ready"}
            />
            <Connection
              icon={<CalendarDays size={15} />}
              title="Calendar adapter"
              detail="Local planning calendar. Google and Outlook are not connected."
              state="Local only"
            />
            <Connection
              icon={<Bot size={15} />}
              title="Wispr Flow"
              detail="External MCP credentials not added yet"
              state="Awaiting key"
            />
          </div>
        )}
      </div>
    </View>
  );
}
function Toggle({ text, detail, active, onChange }) {
  return (
    <div className="toggle-row">
      <div>
        <b>{text}</b>
        <small>{detail}</small>
      </div>
      <button
        type="button"
        className={active ? "on" : ""}
        onClick={() => onChange(!active)}
      >
        <span />
      </button>
    </div>
  );
}
function Connection({ icon, title, detail, state }) {
  return (
    <div className="connection">
      <span>{icon}</span>
      <div>
        <b>{title}</b>
        <small>{detail}</small>
      </div>
      <em>{state}</em>
    </div>
  );
}

function TaskModal({ task, projects, close, onSaved }) {
  const editing = Boolean(task?.id);
  const [form, setForm] = useState(
    {
      title: "",
      description: "",
      duration_minutes: 60,
      priority: "medium",
      flexibility: "flexible",
      deadline: "",
      fixed_start: "",
      splittable: true,
      tags: [],
      project_id: projects[0]?.id || null,
      ...(task || {}),
    },
  );
  const submit = async (event) => {
    event.preventDefault();
    const payload = {
      title: form.title,
      description: form.description || "",
      duration_minutes: Number(form.duration_minutes),
      priority: form.priority,
      flexibility: form.flexibility,
      deadline: form.deadline || null,
      fixed_start:
        form.flexibility === "fixed" ? form.fixed_start || null : null,
      splittable: form.splittable,
      tags: form.tags || [],
      project_id: form.project_id || null,
    };
    await api(editing ? `/tasks/${task.id}` : "/tasks", {
      method: editing ? "PATCH" : "POST",
      body: JSON.stringify(payload),
    });
    onSaved();
  };
  return (
    <div className="modal-backdrop">
      <form className="modal" onSubmit={submit}>
        <button type="button" className="close" onClick={close}>
          <X size={18} />
        </button>
        <Eyebrow>{editing ? "EDIT COMMITMENT" : task?.fixed_start ? "QUICK CALENDAR TASK" : "NEW COMMITMENT"}</Eyebrow>
        <h2>{editing ? "Edit task" : task?.fixed_start ? "Schedule this time" : "Add a task"}</h2>
        <p>
          Duration, deadline and scheduled time remain separate constraints.
        </p>
        <label>
          Task title
          <input
            autoFocus
            required
            value={form.title}
            onChange={(event) =>
              setForm({ ...form, title: event.target.value })
            }
          />
        </label>
        <label>
          Description
          <input
            value={form.description || ""}
            onChange={(event) =>
              setForm({ ...form, description: event.target.value })
            }
          />
        </label>
        <label>
          Project
          <select
            value={form.project_id || ""}
            onChange={(event) =>
              setForm({ ...form, project_id: event.target.value || null })
            }
          >
            <option value="">Inbox</option>
            {projects.map((project) => (
              <option value={project.id} key={project.id}>
                {project.name}
              </option>
            ))}
          </select>
        </label>
        <div className="inline">
          <label>
            Duration
            <input
              type="number"
              min="5"
              max="720"
              value={form.duration_minutes}
              onChange={(event) =>
                setForm({
                  ...form,
                  duration_minutes: Number(event.target.value),
                })
              }
            />
          </label>
          <label>
            Priority
            <select
              value={form.priority}
              onChange={(event) =>
                setForm({ ...form, priority: event.target.value })
              }
            >
              <option value="high">High</option>
              <option value="medium">Medium</option>
              <option value="low">Low</option>
            </select>
          </label>
        </div>
        <div className="inline">
          <label>
            Deadline
            <input
              type="datetime-local"
              value={form.deadline || ""}
              onChange={(event) =>
                setForm({ ...form, deadline: event.target.value })
              }
            />
          </label>
          <label>
            Flexibility
            <select
              value={form.flexibility}
              onChange={(event) =>
                setForm({ ...form, flexibility: event.target.value })
              }
            >
              <option value="flexible">Flexible</option>
              <option value="fixed">Fixed</option>
              <option value="buffer">Protected buffer</option>
            </select>
          </label>
        </div>
        {form.flexibility === "fixed" && (
          <label>
            Fixed start
            <input
              required
              type="datetime-local"
              value={form.fixed_start || ""}
              onChange={(event) =>
                setForm({ ...form, fixed_start: event.target.value })
              }
            />
          </label>
        )}
        <Toggle
          text="This task can be split"
          detail="Use smaller recovery blocks when needed"
          active={form.splittable}
          onChange={(value) => setForm({ ...form, splittable: value })}
        />
        <Button primary type="submit" className="wide">
          {editing ? "Save task" : "Add to my plan"} <ArrowRight size={14} />
        </Button>
      </form>
    </div>
  );
}

function ProjectModal({ project, close, onSaved }) {
  const editing = Boolean(project?.id);
  const [form, setForm] = useState({
    name: project?.name || "",
    description: project?.description || "",
    color: project?.color || "#e4794c",
    target_date: project?.target_date || "",
  });
  const submit = async (event) => {
    event.preventDefault();
    await api(editing ? `/projects/${project.id}` : "/projects", {
      method: editing ? "PATCH" : "POST",
      body: JSON.stringify({ ...form, target_date: form.target_date || null }),
    });
    onSaved(editing);
  };
  return (
    <div className="modal-backdrop">
      <form className="modal project-modal" onSubmit={submit}>
        <button type="button" className="close" onClick={close}>
          <X size={18} />
        </button>
        <Eyebrow>{editing ? "EDIT WORKSPACE" : "NEW WORKSPACE"}</Eyebrow>
        <h2>{editing ? "Edit project" : "Add a project"}</h2>
        <p>Projects group related tasks and power progress tracking.</p>
        <label>
          Project name
          <input
            autoFocus
            required
            value={form.name}
            onChange={(event) => setForm({ ...form, name: event.target.value })}
            placeholder="e.g. Product launch"
          />
        </label>
        <label>
          Description
          <input
            value={form.description}
            onChange={(event) =>
              setForm({ ...form, description: event.target.value })
            }
            placeholder="What outcome does this project produce?"
          />
        </label>
        <div className="inline">
          <label>
            Target date
            <input
              type="date"
              value={form.target_date}
              onChange={(event) =>
                setForm({ ...form, target_date: event.target.value })
              }
            />
          </label>
          <label>
            Project color
            <input
              type="color"
              value={form.color}
              onChange={(event) =>
                setForm({ ...form, color: event.target.value })
              }
            />
          </label>
        </div>
        <Button primary type="submit" className="wide">
          {editing ? "Save project" : "Create project"} <ArrowRight size={14} />
        </Button>
      </form>
    </div>
  );
}

function Onboarding({ preferences, close, save }) {
  const [step, setStep] = useState(0);
  const [form, setForm] = useState(preferences);
  const steps = ["Your day", "Sources", "Planning style", "Preview", "Ready"];
  const field = (name, value) =>
    setForm((current) => ({ ...current, [name]: value }));
  return (
    <div className="modal-backdrop setup-backdrop">
      <div className="setup-modal">
        <button className="close" onClick={close}>
          <X size={18} />
        </button>
        <div className="setup-progress">
          {steps.map((name, index) => (
            <span className={index <= step ? "active" : ""} key={name}>
              <i>{index < step ? "✓" : index + 1}</i>
              {name}
            </span>
          ))}
        </div>
        <div className="setup-body">
          {step === 0 && (
            <>
              <Eyebrow>LET'S BUILD YOUR BASELINE</Eyebrow>
              <h2>When does your working day begin and end?</h2>
              <p>Plan B uses this hard boundary before considering overtime.</p>
              <div className="inline">
                <label>
                  Starts
                  <input
                    type="time"
                    value={form.day_start}
                    onChange={(event) => field("day_start", event.target.value)}
                  />
                </label>
                <label>
                  Ends
                  <input
                    type="time"
                    value={form.day_end}
                    onChange={(event) => field("day_end", event.target.value)}
                  />
                </label>
              </div>
            </>
          )}
          {step === 1 && (
            <>
              <Eyebrow>CONNECT YOUR SOURCES</Eyebrow>
              <h2>Bring commitments into one planning layer.</h2>
              <p>
                Local tasks are ready now. Calendar and Wispr Flow adapters can
                be connected when you provide keys.
              </p>
              <div className="source-cards">
                <Connection
                  icon={<ListTodo size={15} />}
                  title="Plan B tasks"
                  detail="Local SQLite workspace"
                  state="Connected"
                />
                <Connection
                  icon={<CalendarDays size={15} />}
                  title="External calendar"
                  detail="Provider adapter"
                  state="Optional"
                />
                <Connection
                  icon={<Mic size={15} />}
                  title="Wispr Flow"
                  detail="MCP voice adapter"
                  state="Later"
                />
              </div>
            </>
          )}
          {step === 2 && (
            <>
              <Eyebrow>CHOOSE YOUR STYLE</Eyebrow>
              <h2>How tightly should Plan B pack your day?</h2>
              <div className="choice-grid">
                {["realistic", "balanced", "ambitious"].map((style) => (
                  <button
                    className={form.planning_style === style ? "active" : ""}
                    onClick={() => field("planning_style", style)}
                    key={style}
                  >
                    <b>{style}</b>
                    <small>
                      {style === "realistic"
                        ? "More recovery room"
                        : style === "balanced"
                          ? "Steady pace"
                          : "Maximum capacity"}
                    </small>
                  </button>
                ))}
              </div>
              <label>
                Protected buffer between blocks
                <input
                  type="number"
                  min="0"
                  value={form.default_buffer_minutes}
                  onChange={(event) =>
                    field("default_buffer_minutes", Number(event.target.value))
                  }
                />
              </label>
            </>
          )}
          {step === 3 && (
            <>
              <Eyebrow>PREVIEW YOUR RULES</Eyebrow>
              <h2>Plan B will protect these boundaries.</h2>
              <div className="setup-summary">
                <span>
                  <Clock3 size={16} />
                  <b>
                    {form.day_start}–{form.day_end}
                  </b>
                  <small>Working day</small>
                </span>
                <span>
                  <ShieldCheck size={16} />
                  <b>{form.default_buffer_minutes} minutes</b>
                  <small>Protected buffer</small>
                </span>
                <span>
                  <Sparkles size={16} />
                  <b>{form.planning_style}</b>
                  <small>Planning style</small>
                </span>
              </div>
            </>
          )}
          {step === 4 && (
            <>
              <span className="setup-done">
                <Check size={30} />
              </span>
              <Eyebrow>SETUP COMPLETE</Eyebrow>
              <h2>Your resilient planning workspace is ready.</h2>
              <p>
                Every suggestion stays explainable, every write requires
                approval, and every plan version can be restored.
              </p>
            </>
          )}
        </div>
        <footer>
          <Button onClick={() => (step ? setStep(step - 1) : close())}>
            {step ? "Back" : "Close"}
          </Button>
          <Button
            primary
            onClick={() =>
              step === steps.length - 1 ? save(form) : setStep(step + 1)
            }
          >
            {step === steps.length - 1 ? "Enter Plan B" : "Continue"}{" "}
            <ArrowRight size={14} />
          </Button>
        </footer>
      </div>
    </div>
  );
}

createRoot(document.getElementById("root")).render(<App />);
