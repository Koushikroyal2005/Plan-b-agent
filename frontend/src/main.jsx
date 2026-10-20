import React, { useEffect, useMemo, useState } from "react";
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
  Circle,
  Clock3,
  Code2,
  Columns3,
  Command,
  History,
  Home,
  FolderKanban,
  LayoutDashboard,
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
import { useSpeechRecognition } from "./hooks/useSpeechRecognition";
import { ProviderModelPicker } from "./features/settings/ProviderModelPicker";
import { AppHeader } from "./components/AppHeader";
import { CalendarWorkspace } from "./features/calendar/CalendarWorkspace";
import "./styles.css";
import "./features.css";

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
  const [projectModal, setProjectModal] = useState(false);
  const [showSetup, setShowSetup] = useState(false);
  const [toast, setToast] = useState(null);

  const notify = (title, body) => {
    setToast({ title, body });
    window.setTimeout(() => setToast(null), 3500);
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
      ] = await Promise.all([
        api("/tasks"),
        api("/projects"),
        api("/day"),
        api("/recovery/history"),
        api("/preferences"),
        api("/provider/status"),
        api("/patterns"),
        api("/opportunities"),
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
  }, []);

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
  const sendMessage = async (text) => {
    if (!text.trim()) return;
    setMessages((items) => [...items, { role: "user", text }]);
    try {
      const result = await api("/assistant", {
        method: "POST",
        body: JSON.stringify({ message: text }),
      });
      setMessages((items) => [
        ...items,
        { role: "assistant", text: result.message },
      ]);
      setActivity(result.tools || []);
      if (result.recovery) setRecovery(result.recovery);
    } catch (error) {
      setMessages((items) => [
        ...items,
        { role: "assistant", text: `Planning service error: ${error.message}` },
      ]);
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
  const approve = async (proposalId) => {
    try {
      await api(`/recovery/${proposalId}/approve`, { method: "POST" });
      notify(
        "Recovery plan applied",
        "The previous version remains in history.",
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
      <DashboardView
        day={data.day}
        tasks={data.tasks}
        projects={data.projects}
        opportunities={data.opportunities}
        messages={messages}
        sendMessage={sendMessage}
        provider={data.provider}
        openChat={() => setView("assistant")}
        openCalendar={() => setView("calendar")}
      />
    ),
    day: (
      <DayView
        day={data.day}
        opportunities={data.opportunities}
        onRespond={respondOpportunity}
        onAdd={() => setTaskModal({})}
        onRecovery={createRecovery}
        onRefresh={refresh}
        navigate={setView}
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
        onAddProject={() => setProjectModal(true)}
        onEdit={(task) => setTaskModal(task)}
        onPatch={patchTask}
      />
    ),
    assistant: (
      <AssistantView
        messages={messages}
        activity={activity}
        sendMessage={sendMessage}
        preferences={data.preferences}
        notify={notify}
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
    patterns: <PatternsView data={data.patterns} projects={data.projects} />,
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
          task={taskModal.id ? taskModal : null}
          projects={data.projects}
          close={() => setTaskModal(null)}
          onSaved={() => {
            setTaskModal(null);
            refresh();
            notify(
              "Task saved",
              "The plan was recalculated from the updated constraint.",
            );
          }}
        />
      )}
      {projectModal && (
        <ProjectModal
          close={() => setProjectModal(false)}
          onSaved={() => {
            setProjectModal(false);
            refresh();
            notify(
              "Project added",
              "You can now assign tasks and track its progress.",
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
    </div>
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
const Toast = ({ title, body }) => (
  <div className="toast">
    <Check size={16} />
    <div>
      <b>{title}</b>
      <small>{body}</small>
    </div>
  </div>
);

function LegacyDashboardView({
  day,
  tasks,
  projects,
  opportunities,
  openChat,
  openCalendar,
}) {
  const open = tasks.filter((task) => task.status === "open");
  const done = tasks.filter((task) => task.status === "done");
  const focusMinutes =
    day?.blocks
      ?.filter((block) => block.kind === "focus" || block.kind === "risk")
      .reduce((sum, block) => sum + block.minutes, 0) || 0;
  const today = new Date(2026, 9, 19);
  const monthStart = new Date(2026, 9, 1);
  const startOffset = monthStart.getDay();
  return (
    <View id="dashboard">
      <div className="dashboard-welcome">
        <div>
          <Eyebrow>MONDAY · OCTOBER 19</Eyebrow>
          <h1>Welcome back, Koushik</h1>
          <p>Here is what your day and projects look like right now.</p>
        </div>
        <Button primary onClick={openChat}>
          <Sparkles size={14} /> Ask Plan B
        </Button>
      </div>
      <div className="dashboard-metrics">
        <Metric
          label="Tasks today"
          value={open.length}
          note={`${day?.metrics?.deadlines_today || 0} deadlines`}
        />
        <Metric
          label="In progress"
          value={day?.blocks?.length || 0}
          note="scheduled blocks"
        />
        <Metric
          label="Completed"
          value={done.length}
          note={`${tasks.length ? Math.round((done.length / tasks.length) * 100) : 0}% completion rate`}
          good
        />
        <Metric
          label="Focus time"
          value={(focusMinutes / 60).toFixed(1)}
          unit="hrs"
          note="protected deep work"
        />
      </div>
      <div className="dashboard-layout">
        <div className="dashboard-main">
          <div className="panel project-progress">
            <PanelHeading
              title="Project progress"
              sub={`${projects.length} active workspaces`}
            />
            {projects.map((project) => (
              <div className="project-progress-row" key={project.id}>
                <span style={{ background: project.color }}>
                  <FolderKanban size={14} />
                </span>
                <div>
                  <b>{project.name}</b>
                  <small>
                    {project.completed_count}/{project.task_count} tasks ·{" "}
                    {project.target_date
                      ? `due ${new Date(project.target_date).toLocaleDateString([], { month: "short", day: "numeric" })}`
                      : "ongoing"}
                  </small>
                  <i>
                    <em
                      style={{
                        width: `${project.progress}%`,
                        background: project.color,
                      }}
                    />
                  </i>
                </div>
                <strong>{project.progress}%</strong>
              </div>
            ))}
          </div>
          <div className="panel activity-feed">
            <PanelHeading
              title="Activity feed"
              sub="What changed across your plan"
            />
            <Feed
              icon={<Check size={13} />}
              title={`${done.length} tasks completed`}
              detail="Completion data now informs duration estimates"
            />
            <Feed
              icon={<RotateCcw size={13} />}
              title={`${day?.plan_version || 1} plan versions`}
              detail="Every applied recovery remains restorable"
            />
            <Feed
              icon={<ShieldCheck size={13} />}
              title="Constraints checked"
              detail={`${day?.metrics?.confidence || 0}% schedule confidence`}
            />
          </div>
          <div className="panel dashboard-suggestion">
            <span>
              <Sparkles size={18} />
            </span>
            <div>
              <Eyebrow>AI SUGGESTION</Eyebrow>
              <h2>{opportunities[0]?.title || "Your plan is stable"}</h2>
              <p>
                {opportunities[0]?.description ||
                  "There are no urgent changes to review."}
              </p>
            </div>
            <Button onClick={openChat}>
              Discuss <ArrowRight size={14} />
            </Button>
          </div>
        </div>
        <aside className="dashboard-side">
          <div className="panel mini-calendar">
            <header>
              <div>
                <b>October 2026</b>
                <small>Today and deadlines</small>
              </div>
              <button onClick={openCalendar}>
                <CalendarDays size={15} />
              </button>
            </header>
            <div className="mini-week">
              {["S", "M", "T", "W", "T", "F", "S"].map((d, i) => (
                <b key={`${d}-${i}`}>{d}</b>
              ))}
            </div>
            <div className="mini-days">
              {Array.from({ length: 35 }, (_, index) => {
                const number = index - startOffset + 1;
                const valid = number > 0 && number <= 31;
                return (
                  <button
                    className={
                      number === today.getDate()
                        ? "today"
                        : tasks.some((task) =>
                              task.deadline?.startsWith(
                                `2026-10-${String(number).padStart(2, "0")}`,
                              ),
                            )
                          ? "has-task"
                          : ""
                    }
                    key={index}
                  >
                    {valid ? number : ""}
                  </button>
                );
              })}
            </div>
            <Button className="wide" onClick={openCalendar}>
              Open full calendar <ArrowRight size={14} />
            </Button>
          </div>
          <div className="panel upcoming">
            <PanelHeading title="Upcoming" sub="Next scheduled blocks" />
            {day?.blocks?.slice(0, 4).map((block) => (
              <div key={block.task_id}>
                <span>{block.start}</span>
                <b>{block.title}</b>
                <small>{block.label}</small>
              </div>
            ))}
          </div>
        </aside>
      </div>
    </View>
  );
}
function DashboardView({
  day,
  tasks,
  projects,
  opportunities,
  messages,
  sendMessage,
  provider,
  openChat,
  openCalendar,
}) {
  const [input, setInput] = useState("");
  const open = tasks.filter((task) => task.status === "open");
  const done = tasks.filter((task) => task.status === "done");
  const focusMinutes =
    day?.blocks
      ?.filter((block) => block.kind === "focus" || block.kind === "risk")
      .reduce((sum, block) => sum + block.minutes, 0) || 0;
  const submit = () => {
    if (!input.trim()) return;
    sendMessage(input);
    setInput("");
  };
  const quick = [
    "Summarize today",
    "Create a recovery plan",
    "What is at risk?",
    "Plan my next focus block",
  ];
  return (
    <View id="dashboard">
      <div className="screen4-head">
        <div>
          <h1>Good morning, Koushik</h1>
          <p>Your day, projects and planning assistant in one place.</p>
        </div>
        <div className="provider-live">
          <span />
          {provider?.configured
            ? `${provider.provider} connected`
            : "Deterministic mode"}
        </div>
      </div>
      <div className="dashboard-metrics screen4-metrics">
        <DashboardMetric
          icon={<ListTodo size={17} />}
          tone="violet"
          label="Tasks today"
          value={open.length}
          note={`${day?.metrics?.deadlines_today || 0} due today`}
        />
        <DashboardMetric
          icon={<Clock3 size={17} />}
          tone="amber"
          label="In progress"
          value={day?.blocks?.length || 0}
          note="scheduled blocks"
        />
        <DashboardMetric
          icon={<Check size={17} />}
          tone="green"
          label="Completed"
          value={done.length}
          note={`${tasks.length ? Math.round((done.length / tasks.length) * 100) : 0}% completion`}
        />
        <DashboardMetric
          icon={<Target size={17} />}
          tone="blue"
          label="Focus time"
          value={`${Math.floor(focusMinutes / 60)}h ${focusMinutes % 60}m`}
          note={`${day?.metrics?.confidence || 0}% plan confidence`}
        />
      </div>
      <div className="screen4-layout">
        <div className="panel dashboard-chat-card">
          <div className="dashboard-chat-top">
            <div>
              <span className="assistant-badge">
                <Sparkles size={16} />
              </span>
              <b>Plan B Assistant</b>
              <small>NVIDIA-powered · tool grounded</small>
            </div>
            <button onClick={openChat} title="Open full chat">
              <ArrowRight size={16} />
            </button>
          </div>
          <div className="dashboard-chat-body">
            <div className="assistant-profile">
              <span>
                <Sparkles size={24} />
              </span>
              <h2>Let’s make today work.</h2>
              <p>
                I can inspect your plan, explain risks and prepare changes for
                your approval.
              </p>
            </div>
            <div className="dashboard-message-list">
              {messages.slice(-5).map((message, index) => (
                <div className={`dash-message ${message.role}`} key={index}>
                  <span>{message.role === "assistant" ? "P" : "KS"}</span>
                  <p>{message.text}</p>
                </div>
              ))}
            </div>
          </div>
          <div className="dashboard-quick">
            {quick.map((item) => (
              <button onClick={() => sendMessage(item)} key={item}>
                <Sparkles size={12} />
                {item}
              </button>
            ))}
          </div>
          <div className="dashboard-composer">
            <button>
              <Plus size={18} />
            </button>
            <input
              value={input}
              onChange={(event) => setInput(event.target.value)}
              onKeyDown={(event) => event.key === "Enter" && submit()}
              placeholder="Ask Plan B anything about your schedule…"
            />
            <button className="composer-mic">
              <Mic size={17} />
            </button>
            <button className="composer-send" onClick={submit}>
              <ArrowRight size={17} />
            </button>
          </div>
        </div>
        <aside className="screen4-rail">
          <div className="panel rail-card rail-calendar">
            <div className="rail-head">
              <div>
                <b>
                  <CalendarDays size={15} /> Calendar
                </b>
                <small>Today · October 19</small>
              </div>
              <button onClick={openCalendar}>
                View calendar <ChevronRight size={13} />
              </button>
            </div>
            {day?.blocks?.slice(0, 3).map((block, index) => (
              <div className="rail-event" key={`${block.task_id}-${index}`}>
                <i className={`tone-${index}`} />
                <div>
                  <b>{block.title}</b>
                  <small>{block.start}</small>
                </div>
                <span>{block.minutes}m</span>
              </div>
            ))}
            <button className="rail-action" onClick={openCalendar}>
              Open schedule
            </button>
          </div>
          <div className="panel rail-card">
            <div className="rail-head">
              <b>
                <FolderKanban size={15} /> Project progress
              </b>
              <button>View all</button>
            </div>
            {projects.slice(0, 3).map((project) => (
              <div className="rail-project" key={project.id}>
                <header>
                  <b>{project.name}</b>
                  <span>{project.progress}%</span>
                </header>
                <i>
                  <em
                    style={{
                      width: `${project.progress}%`,
                      background: project.color,
                    }}
                  />
                </i>
              </div>
            ))}
          </div>
          <div className="panel rail-card">
            <div className="rail-head">
              <b>
                <Activity size={15} /> Activity feed
              </b>
              <button>View all</button>
            </div>
            <Feed
              icon={<Check size={13} />}
              title={`${done.length} tasks completed`}
              detail="Completion history updated"
            />
            <Feed
              icon={<ShieldCheck size={13} />}
              title="Plan validated"
              detail={`${day?.metrics?.free_buffer_minutes || 0} minutes free buffer`}
            />
          </div>
          <div className="panel rail-suggestion">
            <Sparkles size={18} />
            <div>
              <b>AI suggestion</b>
              <p>
                {opportunities[0]?.description ||
                  "Your current schedule is stable."}
              </p>
            </div>
            <button onClick={openChat}>Discuss now</button>
          </div>
        </aside>
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

function DayView({
  day,
  opportunities,
  onRespond,
  onAdd,
  onRecovery,
  onRefresh,
  navigate,
}) {
  const [filter, setFilter] = useState("all");
  if (!day) return null;
  const metrics = day.metrics || {};
  const risk = day.risks?.[0];
  const filtered = opportunities.filter(
    (item) => filter === "all" || item.kind === filter,
  );
  return (
    <View id="day">
      <div className="hero">
        <div>
          <Eyebrow>MONDAY · OCTOBER 19, 2026</Eyebrow>
          <h1>
            Good morning, Koushik <span>✦</span>
          </h1>
          <p>
            Your plan is calculated from real durations, deadlines, fixed events
            and buffers.
          </p>
        </div>
        <div className="hero-buttons">
          <Button onClick={onRefresh}>
            <RotateCcw size={14} /> Refresh
          </Button>
          <Button onClick={() => navigate("recovery")}>
            <History size={14} /> History
          </Button>
          <Button onClick={() => onRecovery()}>
            <Zap size={14} /> Something changed
          </Button>
          <Button primary onClick={onAdd}>
            <Plus size={15} /> Add task
          </Button>
        </div>
      </div>
      <div
        className={`risk-banner ${day.status === "on_track" ? "on-track" : ""}`}
      >
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
      <div className="metrics">
        <Metric
          label="Active predictions"
          value={opportunities.length}
          note="live schedule signals"
        />
        <Metric
          label="Suggested actions"
          value={
            opportunities.filter((item) => item.kind !== "prediction").length
          }
          note="awaiting your choice"
        />
        <Metric
          label="Goals on track"
          value={Math.max(0, 3 - metrics.risky_tasks)}
          unit="/3"
          note="based on current slack"
          good
        />
        <Metric
          label="Upcoming events"
          value={
            day.blocks?.filter((block) => block.kind === "fixed").length || 0
          }
          note={`${metrics.free_buffer_minutes || 0} min free buffer`}
          warning={day.status !== "on_track"}
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
            title="Proactive predictions"
            sub={`${opportunities.length} current signals`}
          />
          <div className="prediction-tabs">
            {["all", "suggestion", "alert", "automation"].map((item) => (
              <button
                className={filter === item ? "active" : ""}
                onClick={() => setFilter(item)}
                key={item}
              >
                {item === "all" ? "All" : item}
              </button>
            ))}
          </div>
          {filtered.map((item) => (
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
          {!filtered.length && (
            <p className="muted">No signals in this category.</p>
          )}
        </div>
      </div>
    </View>
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

function TasksView({ tasks, projects, onAdd, onAddProject, onEdit, onPatch }) {
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
              <strong>{project.progress}%</strong>
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
  sendMessage,
  preferences,
  notify,
}) {
  const [input, setInput] = useState("");
  const { listening, supported, toggle } = useSpeechRecognition({
    language: preferences?.language || "en-IN",
    onTranscript: setInput,
  });
  const submit = () => {
    if (!input.trim()) return;
    sendMessage(input);
    setInput("");
  };
  const voice = () =>
    supported
      ? toggle()
      : notify(
          "Voice input unavailable",
          "Use a supported browser or connect Wispr Flow later.",
        );
  const tools = activity.length
    ? activity
    : [
        { tool: "get_day_schedule", status: "complete" },
        { tool: "check_deadline_risks", status: "complete" },
        { tool: "generate_recovery_options", status: "waiting" },
        { tool: "validate_schedule", status: "waiting" },
      ];
  return (
    <View id="assistant">
      <div className="section-head">
        <div>
          <Eyebrow>YOUR PLANNING COMPANION</Eyebrow>
          <h1>AI Assistant</h1>
          <p>The same controlled tools power text, voice and MCP.</p>
        </div>
        <span className="provider">● Server controlled · approval gated</span>
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
          <div className="messages">
            {messages.map((message, index) => (
              <div className={`message ${message.role}`} key={index}>
                {message.role === "assistant" && (
                  <span className="message-icon">✦</span>
                )}
                <div>
                  <p>{message.text}</p>
                  <small>
                    {message.role === "assistant"
                      ? "Tool-backed response"
                      : "You · now"}
                  </small>
                </div>
              </div>
            ))}
          </div>
          <div className="suggestions">
            {[
              "My meeting is running 45 minutes late",
              "Can I still finish everything today?",
              "Give me the shortest realistic plan",
            ].map((text) => (
              <button onClick={() => sendMessage(text)} key={text}>
                {text}
              </button>
            ))}
          </div>
          <div className="composer">
            <button className={listening ? "listening" : ""} onClick={voice}>
              <Mic size={17} />
            </button>
            <input
              value={input}
              onChange={(event) => setInput(event.target.value)}
              onKeyDown={(event) => event.key === "Enter" && submit()}
              placeholder={
                listening ? "Listening…" : "Tell Plan B what changed…"
              }
            />
            <button className="send" onClick={submit}>
              <ArrowRight size={15} />
            </button>
          </div>
          <small className="note">
            Nothing changes until you explicitly confirm it.
          </small>
        </div>
        <div className="panel activity-panel">
          <PanelHeading
            title="Agent activity"
            sub="Real operations from the latest turn"
          />
          <div className="activities">
            {tools.map((item) => (
              <ActivityItem
                key={item.tool}
                done={item.status === "complete"}
                title={item.tool.replaceAll("_", " ")}
                detail={item.status}
              />
            ))}
          </div>
          <code>
            bounded orchestrator <span>max 6 steps</span>
          </code>
          <code>
            approval gate <span>required</span>
          </code>
          <code>
            write tools <span>allowlisted</span>
          </code>
        </div>
      </div>
    </View>
  );
}
function ActivityItem({ done, title, detail }) {
  return (
    <div className="activity-item">
      <span className={done ? "done" : ""}>
        {done ? <Check size={11} /> : <Circle size={10} />}
      </span>
      <div>
        <b>{title}</b>
        <small>{detail}</small>
      </div>
    </div>
  );
}

function RecoveryView({ data, history, approve, restore, generate }) {
  const [selected, setSelected] = useState(null);
  const [compare, setCompare] = useState("proposed");
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
          <Eyebrow>DECISION WORKSPACE</Eyebrow>
          <h1>
            Recovery plan{" "}
            <em>{data ? "Needs your decision" : "Ready when needed"}</em>
          </h1>
          <p>
            Compare trade-offs, inspect validation and approve one exact
            version.
          </p>
        </div>
        <Button onClick={() => generate()}>
          <RotateCcw size={14} /> New recovery
        </Button>
      </div>
      {!data ? (
        <div className="empty-recovery">
          <RotateCcw size={28} />
          <h2>No pending proposal</h2>
          <p>Report a disruption to calculate its downstream impact.</p>
          <Button primary onClick={() => generate()}>
            Generate recovery options
          </Button>
        </div>
      ) : (
        <>
          <div className="recovery-alert">
            <RotateCcw size={21} />
            <div>
              <b>
                {data.disruption_minutes}-minute disruption ·{" "}
                {data.options.filter((item) => item.feasible).length} feasible
                options
              </b>
              <p>Affected: {data.affected_tasks.join(", ")}</p>
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

function PatternsView({ data }) {
  const activity = data?.activity || [];
  const labels = data?.week_labels || [];
  const timeTrend = data?.time_trend || [];
  const focusTrend = data?.focus_trend || [];
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
          <h1>Patterns</h1>
          <p>
            Time trends, task and goal progress, activity, focus, balance and
            work breakdown.
          </p>
        </div>
        <Button>
          <TrendingUp size={14} /> Last 7 days
        </Button>
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
            sub="Planned hours across the last seven days"
          />
          <svg
            className="line-chart"
            viewBox="0 0 100 100"
            preserveAspectRatio="none"
          >
            <polyline points={points(timeTrend, 7)} />
          </svg>
          <div className="chart-labels">
            {labels.map((label) => (
              <span key={label}>{label}</span>
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
              <div key={labels[index]}>
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
            {labels.map((label) => (
              <span key={label}>{label}</span>
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
          {data?.categories?.map((item) => (
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
          ))}
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
              detail="Read approved summaries aloud"
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
              detail="Local planning calendar"
              state="Connected"
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
  const [form, setForm] = useState(
    task || {
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
    await api(task ? `/tasks/${task.id}` : "/tasks", {
      method: task ? "PATCH" : "POST",
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
        <Eyebrow>{task ? "EDIT COMMITMENT" : "NEW COMMITMENT"}</Eyebrow>
        <h2>{task ? "Edit task" : "Add a task"}</h2>
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
          {task ? "Save task" : "Add to my plan"} <ArrowRight size={14} />
        </Button>
      </form>
    </div>
  );
}

function ProjectModal({ close, onSaved }) {
  const [form, setForm] = useState({
    name: "",
    description: "",
    color: "#e4794c",
    target_date: "",
  });
  const submit = async (event) => {
    event.preventDefault();
    await api("/projects", {
      method: "POST",
      body: JSON.stringify({ ...form, target_date: form.target_date || null }),
    });
    onSaved();
  };
  return (
    <div className="modal-backdrop">
      <form className="modal project-modal" onSubmit={submit}>
        <button type="button" className="close" onClick={close}>
          <X size={18} />
        </button>
        <Eyebrow>NEW WORKSPACE</Eyebrow>
        <h2>Add a project</h2>
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
          Create project <ArrowRight size={14} />
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
