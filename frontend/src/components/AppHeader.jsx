import { useMemo, useState } from "react";
import { Bell, CalendarClock, Check, Search, X } from "lucide-react";
import { navigation } from "../core/navigation";

export function AppHeader({
  view,
  tasks,
  projects,
  onNavigate,
  name = "Koushik",
}) {
  const [searchOpen, setSearchOpen] = useState(false);
  const [notificationsOpen, setNotificationsOpen] = useState(false);
  const [query, setQuery] = useState("");
  const results = useMemo(() => {
    if (!query.trim()) return [];
    const term = query.toLowerCase();
    return [
      ...tasks
        .filter((item) => item.title.toLowerCase().includes(term))
        .map((item) => ({
          id: item.id,
          title: item.title,
          type: "Task",
          target: "tasks",
        })),
      ...projects
        .filter((item) => item.name.toLowerCase().includes(term))
        .map((item) => ({
          id: item.id,
          title: item.name,
          type: "Project",
          target: "tasks",
        })),
      ...navigation
        .filter((item) => item.label.toLowerCase().includes(term))
        .map((item) => ({
          id: item.id,
          title: item.label,
          type: "Page",
          target: item.id,
        })),
    ].slice(0, 7);
  }, [projects, query, tasks]);
  const due = tasks
    .filter((task) => task.status === "open" && task.deadline)
    .slice(0, 3);

  const navigate = (target) => {
    onNavigate(target);
    setSearchOpen(false);
    setNotificationsOpen(false);
    setQuery("");
  };

  return (
    <header className="topbar app-header">
      <div className="mobile-brand">
        <span>✦</span> plan <i>b</i>
      </div>
      <div className="crumb">
        {navigation.find((item) => item.id === view)?.label}
        <span>/</span>
        {new Date().toLocaleDateString([], {
          weekday: "long",
          month: "long",
          day: "numeric",
        })}
      </div>
      <div className="top-actions">
        <button
          type="button"
          aria-label="Search"
          className={searchOpen ? "active" : ""}
          onClick={() => {
            setSearchOpen(!searchOpen);
            setNotificationsOpen(false);
          }}
        >
          {searchOpen ? <X size={18} /> : <Search size={19} />}
        </button>
        <button
          type="button"
          aria-label="Notifications"
          className={notificationsOpen ? "active" : ""}
          onClick={() => {
            setNotificationsOpen(!notificationsOpen);
            setSearchOpen(false);
          }}
        >
          <Bell size={18} />
          {due.length > 0 && <i className="notification-dot" />}
        </button>
        <span className="avatar">{name.slice(0, 2).toUpperCase()}</span>
      </div>
      {searchOpen && (
        <div className="header-popover global-search">
          <label>
            <Search size={16} />
            <input
              autoFocus
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search tasks, projects and pages"
            />
          </label>
          <div>
            {query && !results.length ? (
              <p>No results found.</p>
            ) : (
              results.map((item) => (
                <button
                  type="button"
                  onClick={() => navigate(item.target)}
                  key={`${item.type}-${item.id}`}
                >
                  <span>{item.title}</span>
                  <small>{item.type}</small>
                </button>
              ))
            )}
          </div>
        </div>
      )}
      {notificationsOpen && (
        <div className="header-popover notification-panel">
          <header>
            <b>Notifications</b>
            <small>{due.length} upcoming</small>
          </header>
          {due.length ? (
            due.map((task) => (
              <button
                type="button"
                onClick={() => navigate("tasks")}
                key={task.id}
              >
                <CalendarClock size={15} />
                <span>
                  <b>{task.title}</b>
                  <small>{new Date(task.deadline).toLocaleString()}</small>
                </span>
              </button>
            ))
          ) : (
            <p>
              <Check size={15} /> You are all caught up.
            </p>
          )}
        </div>
      )}
    </header>
  );
}
