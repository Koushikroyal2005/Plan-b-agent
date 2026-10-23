import { useMemo, useState } from "react";
import {
  ArrowRight,
  CalendarDays,
  Check,
  ChevronLeft,
  ChevronRight,
  Clock3,
  Link2,
  MessageSquareText,
  Pencil,
  Plus,
  RotateCcw,
  Sparkles,
  Users,
  X,
} from "lucide-react";
import {
  CALENDAR_DAY_START,
  CALENDAR_PX_PER_HOUR,
  eventHeightPercent,
  eventTopPercent,
  layoutDayEvents,
} from "./calendarLayout";
import "./calendar.css";

const DAY = 86400000;
const HOURS = Array.from({ length: 13 }, (_, i) => i + 8);
const NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const COLORS = ["blue", "green", "violet", "orange"];
const keyOf = (value) => {
  if (!value) return null;
  const d = value instanceof Date ? value : new Date(value);
  return Number.isNaN(d.getTime())
    ? null
    : `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};
const noon = (value) =>
  new Date(`${keyOf(value) || keyOf(new Date())}T12:00:00`);
const addDays = (date, amount) => new Date(date.getTime() + amount * DAY);
const monday = (date) => {
  const d = noon(date);
  d.setDate(d.getDate() - (d.getDay() || 7) + 1);
  return d;
};
const clock = (minutes) =>
  new Date(
    2026,
    0,
    1,
    Math.floor(minutes / 60),
    minutes % 60,
  ).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
const minutesOf = (value, fallback = 540) => {
  if (!value) return fallback;
  const date = new Date(value);
  if (!Number.isNaN(date.getTime()))
    return date.getHours() * 60 + date.getMinutes();
  const match = String(value).match(/(\d+):(\d+)\s*(AM|PM)?/i);
  if (!match) return fallback;
  let hour = Number(match[1]);
  if (match[3]?.toUpperCase() === "PM" && hour < 12) hour += 12;
  if (match[3]?.toUpperCase() === "AM" && hour === 12) hour = 0;
  return hour * 60 + Number(match[2]);
};

function makeEvents(tasks, day, anchor) {
  const planDate = day?.date || keyOf(anchor);
  const plannedIds = new Set(day?.blocks?.map((block) => block.task_id));
  const planned = (day?.blocks || []).map((block, index) => {
    const task = tasks.find((item) => item.id === block.task_id);
    return {
      ...block,
      id: block.task_id || `plan-${index}`,
      title: block.title || task?.title,
      description: task?.description || block.description || "",
      status: task?.status || block.status || "open",
      date: keyOf(block.start_iso) || planDate,
      startMinutes: minutesOf(block.start_iso || block.start, 540 + index * 60),
      duration: block.minutes || 60,
      tone: COLORS[index % 4],
      source: "plan",
    };
  });
  const remaining = tasks
    .filter((task) => task.status !== "archived" && !plannedIds.has(task.id))
    .map((task, index) => {
      const startMinutes = task.fixed_start
        ? minutesOf(task.fixed_start)
        : Math.min(1080, 540 + (index % 8) * 70);
      return {
        ...task,
        task_id: task.id,
        date: keyOf(task.fixed_start || task.deadline) || planDate,
        startMinutes,
        duration: task.duration_minutes,
        minutes: task.duration_minutes,
        start: clock(startMinutes),
        end: clock(startMinutes + task.duration_minutes),
        label: task.priority,
        kind: task.flexibility,
        description: task.description || "",
        tone: COLORS[(index + 1) % 4],
        source: "task",
      };
    });
  return [...planned, ...remaining];
}

export function CalendarWorkspace({
  day,
  tasks,
  onRecovery,
  sendMessage,
  onAdd,
  onPatch,
  notify,
}) {
  const initial =
    day?.date ||
    tasks.find((task) => task.fixed_start || task.deadline)?.fixed_start ||
    tasks.find((task) => task.deadline)?.deadline ||
    new Date();
  const [anchor, setAnchor] = useState(() => noon(initial));
  const [mode, setMode] = useState("Week");
  const [selectedDate, setSelectedDate] = useState(() => keyOf(initial));
  const [selectedEvent, setSelectedEvent] = useState(null);
  const [dayDetail, setDayDetail] = useState(null);
  const events = useMemo(
    () => makeEvents(tasks, day, anchor),
    [tasks, day, anchor],
  );
  const days = useMemo(
    () =>
      mode === "Day"
        ? [noon(anchor)]
        : Array.from({ length: 7 }, (_, i) => addDays(monday(anchor), i)),
    [anchor, mode],
  );
  const selectDate = (date) => {
    setAnchor(noon(date));
    setSelectedDate(keyOf(date));
  };
  const move = (direction) => {
    const next = new Date(anchor);
    mode === "Month"
      ? next.setMonth(next.getMonth() + direction)
      : next.setDate(next.getDate() + direction * (mode === "Week" ? 7 : 1));
    selectDate(next);
  };
  const openDay = (date) => {
    const dateKey = keyOf(date);
    setDayDetail({
      date: dateKey,
      events: events.filter((event) => event.date === dateKey),
    });
  };
  const saveEvent = async (event, changes) => {
    if (!event.task_id || event.kind === "break") {
      notify("Breaks follow your settings", "Change break length in Settings.");
      setSelectedEvent(null);
      return;
    }
    await onPatch(event.task_id, changes);
    setSelectedEvent(null);
    notify(
      "Calendar event saved",
      "The plan was recalculated with the updated constraint.",
    );
  };
  const title =
    mode === "Month"
      ? anchor.toLocaleDateString([], { month: "long", year: "numeric" })
      : mode === "Day"
        ? anchor.toLocaleDateString([], {
            weekday: "long",
            month: "long",
            day: "numeric",
          })
        : `${days[0].toLocaleDateString([], { month: "short", day: "numeric" })} – ${days.at(-1).toLocaleDateString([], { month: "short", day: "numeric", year: "numeric" })}`;
  return (
    <section className="cal-page">
      <header className="cal-titlebar">
        <div>
          <p>PLANNING CALENDAR</p>
          <h1>Calendar</h1>
          <span>
            Move through time, inspect commitments, and edit every scheduling
            constraint.
          </span>
        </div>
        <button className="cal-primary" onClick={onAdd}>
          <Plus size={16} /> New event
        </button>
      </header>
      <div className="cal-shell">
        <aside className="cal-left">
          <MiniCalendar
            anchor={anchor}
            selectedDate={selectedDate}
            events={events}
            onSelect={selectDate}
            onMonth={(amount) => {
              const next = new Date(anchor);
              next.setMonth(next.getMonth() + amount);
              setAnchor(next);
            }}
          />
          <Upcoming
            events={events}
            onSelect={setSelectedEvent}
            onPatch={onPatch}
            onViewAll={() => setMode("Day")}
          />
          <Breakdown events={events} />
        </aside>
        <main className="cal-main">
          <div className="cal-toolbar">
            <div className="cal-period">
              <button
                onClick={() => move(-1)}
                aria-label={`Previous ${mode.toLowerCase()}`}
              >
                <ChevronLeft size={17} />
              </button>
              <button
                onClick={() => move(1)}
                aria-label={`Next ${mode.toLowerCase()}`}
              >
                <ChevronRight size={17} />
              </button>
              <button
                className="cal-today"
                onClick={() => selectDate(new Date())}
              >
                Today
              </button>
              <h2>{title}</h2>
            </div>
            <div className="cal-modes">
              {["Month", "Week", "Day"].map((item) => (
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
          {mode === "Month" ? (
            <MonthBoard
              anchor={anchor}
              events={events}
              selectedDate={selectedDate}
              onSelect={selectDate}
              onOpenDay={openDay}
              onEvent={setSelectedEvent}
            />
          ) : (
            <TimelineBoard
              days={days}
              events={events}
              onOpenDay={openDay}
              onEvent={setSelectedEvent}
              onAdd={onAdd}
            />
          )}
        </main>
        <aside className="cal-right">
          <DaySummary
            date={selectedDate}
            events={events.filter((event) => event.date === selectedDate)}
            onEvent={setSelectedEvent}
              onCreate={onAdd}
          />
          <div className="cal-agent-card">
            <span>
              <Sparkles size={18} />
            </span>
            <p>PLAN B ASSISTANT</p>
            <h3>Keep your calendar resilient.</h3>
            <small>
              I can explain conflicts, preserve fixed events, or calculate
              recovery options before anything changes.
            </small>
            <button onClick={() => onRecovery(30, "Calendar schedule changed")}>
              <RotateCcw size={14} /> Preview recovery
            </button>
            <button
              onClick={() =>
                sendMessage(
                  "Explain my calendar risks and available focus time",
                )
              }
            >
              <MessageSquareText size={14} /> Explain this week
            </button>
          </div>
          <Unscheduled
            tasks={tasks}
            onEvent={(task) =>
              setSelectedEvent(makeEvents([task], null, anchor)[0])
            }
            onAdd={onAdd}
          />
        </aside>
      </div>
      <div className="cal-bottom">
        <BottomCard
          icon={<Clock3 size={18} />}
          tone="blue"
          eyebrow="FOCUS CAPACITY"
          title={`${Math.max(0, 40 - Math.round(events.reduce((sum, event) => sum + event.duration, 0) / 60))} hours still open this week`}
          text="Protected room remains between fixed commitments."
          action="Add focus block"
          onClick={onAdd}
        />
        <BottomCard
          icon={<Sparkles size={18} />}
          tone="green"
          eyebrow="CALENDAR HEALTH"
          title={`${day?.metrics?.confidence || 0}% scheduling confidence`}
          text={`${day?.metrics?.free_buffer_minutes || 0} minutes of free buffer remain after protected breaks.`}
          action="Rebalance week"
          onClick={() => onRecovery(45, "Calendar capacity review")}
        />
      </div>
      {selectedEvent && (
        <EventEditor
          event={selectedEvent}
          task={tasks.find(
            (task) => task.id === (selectedEvent.task_id || selectedEvent.id),
          )}
          onClose={() => setSelectedEvent(null)}
          onSave={saveEvent}
          onComplete={(event) =>
            saveEvent(event, {
              status: "done",
              actual_minutes: event.duration || 60,
            })
          }
        />
      )}
      {dayDetail && (
        <DayPopup
          detail={dayDetail}
          onClose={() => setDayDetail(null)}
          onEvent={(event) => {
            setDayDetail(null);
            setSelectedEvent(event);
          }}
          onRecovery={onRecovery}
        />
      )}
    </section>
  );
}

function MiniCalendar({ anchor, selectedDate, events, onSelect, onMonth }) {
  const first = new Date(anchor.getFullYear(), anchor.getMonth(), 1, 12);
  const offset = (first.getDay() + 6) % 7;
  const cells = Array.from({ length: 42 }, (_, i) =>
    addDays(first, i - offset),
  );
  return (
    <section className="cal-card mini-month">
      <header>
        <div>
          <b>{anchor.toLocaleDateString([], { month: "long" })}</b>
          <small>{anchor.getFullYear()}</small>
        </div>
        <nav>
          <button onClick={() => onMonth(-1)} aria-label="Previous month">
            <ChevronLeft size={15} />
          </button>
          <button onClick={() => onMonth(1)} aria-label="Next month">
            <ChevronRight size={15} />
          </button>
        </nav>
      </header>
      <div className="mini-labels">
        {NAMES.map((name) => (
          <span key={name}>{name[0]}</span>
        ))}
      </div>
      <div className="mini-grid">
        {cells.map((date) => {
          const key = keyOf(date);
          return (
            <button
              onClick={() => onSelect(date)}
              className={`${date.getMonth() !== anchor.getMonth() ? "muted" : ""} ${selectedDate === key ? "selected" : ""}`}
              key={key}
            >
              <span>{date.getDate()}</span>
              {events.some((event) => event.date === key) && <i />}
            </button>
          );
        })}
      </div>
    </section>
  );
}

function Upcoming({ events, onSelect, onPatch, onViewAll }) {
  const items = [...events]
    .sort((a, b) =>
      `${a.date}-${a.startMinutes}`.localeCompare(
        `${b.date}-${b.startMinutes}`,
      ),
    )
    .slice(0, 4);
  return (
    <section className="cal-card upcoming-card">
      <header>
        <div>
          <b>Upcoming events</b>
          <small>Next on your plan</small>
        </div>
        <button onClick={onViewAll}>View day</button>
      </header>
      <div>
        {items.map((event) => (
          <article key={`${event.id}-${event.date}`}>
            <button
              className={`cal-check ${event.status === "done" ? "done" : ""}`}
              onClick={() =>
                onPatch(event.task_id || event.id, {
                  status: event.status === "done" ? "open" : "done",
                  actual_minutes:
                    event.status === "done" ? null : event.duration,
                })
              }
            >
              {event.status === "done" && <Check size={11} />}
            </button>
            <button className="upcoming-name" onClick={() => onSelect(event)}>
              <b>{event.title}</b>
              <small>
                {new Date(`${event.date}T12:00`).toLocaleDateString([], {
                  weekday: "short",
                })}
              </small>
            </button>
            <time>{clock(event.startMinutes)}</time>
          </article>
        ))}
      </div>
    </section>
  );
}

function Breakdown({ events }) {
  const total = Math.max(
    1,
    events.reduce((sum, event) => sum + event.duration, 0),
  );
  const rows = [
    ["Focus", ["focus", "flexible"], "blue"],
    ["Fixed", ["fixed"], "violet"],
    ["Buffers", ["buffer"], "green"],
    ["At risk", ["risk"], "orange"],
  ];
  return (
    <section className="cal-card breakdown">
      <header>
        <div>
          <b>Time breakdown</b>
          <small>{Math.round(total / 6) / 10} scheduled hours</small>
        </div>
      </header>
      {rows.map(([name, kinds, tone]) => {
        const value = events
          .filter((event) => kinds.includes(event.kind))
          .reduce((sum, event) => sum + event.duration, 0);
        return (
          <div className="breakdown-item" key={name}>
            <span>{name}</span>
            <i>
              <em
                className={tone}
                style={{ width: `${(value / total) * 100}%` }}
              />
            </i>
            <b>{Math.round(value / 6) / 10}h</b>
          </div>
        );
      })}
    </section>
  );
}

function TimelineBoard({ days, events, onOpenDay, onEvent, onAdd }) {
  const createAt = (event, date) => {
    if (event.target.closest(".cal-event")) return;
    const rect = event.currentTarget.getBoundingClientRect();
    const offset = Math.max(0, Math.min(rect.height, event.clientY - rect.top));
    const rawMinutes =
      CALENDAR_DAY_START + (offset / CALENDAR_PX_PER_HOUR) * 60;
    const startMinutes = Math.max(480, Math.min(1260, Math.round(rawMinutes / 15) * 15));
    const endMinutes = Math.min(1435, startMinutes + 60);
    const time = (minutes) => `${String(Math.floor(minutes / 60)).padStart(2, "0")}:${String(minutes % 60).padStart(2, "0")}`;
    const dateKey = keyOf(date);
    onAdd({
      fixed_start: `${dateKey}T${time(startMinutes)}`,
      deadline: `${dateKey}T${time(endMinutes)}`,
      duration_minutes: 60,
      flexibility: "fixed",
      priority: "medium",
      splittable: false,
    });
  };
  return (
    <div className="timeline-board">
      <div className="timeline-head">
        <span>GMT +5:30</span>
        {days.map((date) => {
          const key = keyOf(date);
          return (
            <button
              className={key === keyOf(new Date()) ? "today" : ""}
              onClick={() => onOpenDay(date)}
              key={key}
            >
              <small>{date.toLocaleDateString([], { weekday: "short" })}</small>
              <b>{date.getDate()}</b>
              <i>{events.filter((event) => event.date === key).length} items</i>
            </button>
          );
        })}
      </div>
      <div className="timeline-scroll">
        <div className="time-labels">
          {HOURS.map((hour) => (
            <span key={hour}>{clock(hour * 60)}</span>
          ))}
        </div>
        <div className="timeline-days">
          {days.map((date) => {
            const key = keyOf(date);
            const dayEvents = layoutDayEvents(
              events.filter((event) => event.date === key),
            );
            return (
              <div
                className="timeline-day"
                key={key}
                onClick={(event) => createAt(event, date)}
                title="Click an empty time to create a task"
              >
                {HOURS.map((hour) => (
                  <i className="hour-line" key={hour} />
                ))}
                {dayEvents.map((event) => {
                  const columns = event.layoutColumns || 1;
                  const column = event.layoutColumn || 0;
                  const widthPct = 100 / columns;
                  const gutter = 3;
                  const description = (event.description || "").trim();
                  const compact = (event.duration || 0) < 25;
                  return (
                    <button
                      type="button"
                      className={`cal-event ${event.tone} ${event.status === "done" ? "completed" : ""} ${compact ? "compact" : ""}`}
                      style={{
                        "--top": `${eventTopPercent(event)}%`,
                        "--height": `${eventHeightPercent(event, dayEvents)}%`,
                        "--left": `calc(${column * widthPct}% + ${gutter}px)`,
                        "--width": `calc(${widthPct}% - ${gutter * 2}px)`,
                      }}
                      onClick={(click) => {
                        click.stopPropagation();
                        onEvent(event);
                      }}
                      key={`${event.id}-${event.startMinutes}-${column}`}
                      title={`${event.title} · ${clock(event.startMinutes)} – ${clock(event.startMinutes + event.duration)}`}
                      aria-label={`${event.title}, ${clock(event.startMinutes)} to ${clock(event.startMinutes + event.duration)}`}
                    >
                      <b>{event.title}</b>
                      {!compact && (
                        <>
                          <small>
                            {clock(event.startMinutes)} –{" "}
                            {clock(event.startMinutes + event.duration)}
                          </small>
                          {description ? (
                            <p className="cal-event-desc">{description}</p>
                          ) : (
                            <span>{event.label || event.kind}</span>
                          )}
                        </>
                      )}
                    </button>
                  );
                })}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

function MonthBoard({
  anchor,
  events,
  selectedDate,
  onSelect,
  onOpenDay,
  onEvent,
  onCreate,
}) {
  const first = new Date(anchor.getFullYear(), anchor.getMonth(), 1, 12);
  const offset = (first.getDay() + 6) % 7;
  const cells = Array.from({ length: 42 }, (_, i) =>
    addDays(first, i - offset),
  );
  return (
    <div className="month-board">
      <div className="month-labels">
        {NAMES.map((name) => (
          <b key={name}>{name}</b>
        ))}
      </div>
      <div className="month-grid">
        {cells.map((date) => {
          const key = keyOf(date);
          const items = events.filter((event) => event.date === key);
          return (
            <section
              className={`${date.getMonth() !== anchor.getMonth() ? "outside" : ""} ${selectedDate === key ? "selected" : ""}`}
              onClick={() => onCreate({ deadline: `${key}T18:00`, duration_minutes: 60, flexibility: "flexible", priority: "medium", splittable: true })}
              key={key}
            >
              <button
                className="month-number"
                onClick={(click) => {
                  click.stopPropagation();
                  onSelect(date);
                  onOpenDay(date);
                }}
              >
                {date.getDate()}
              </button>
              {items.slice(0, 3).map((event) => (
                <button
                  className={`month-event ${event.tone}`}
                  onClick={(click) => { click.stopPropagation(); onEvent(event); }}
                  key={event.id}
                >
                  {clock(event.startMinutes)} {event.title}
                </button>
              ))}
              {items.length > 3 && <small>+{items.length - 3} more</small>}
            </section>
          );
        })}
      </div>
    </div>
  );
}

function DaySummary({ date, events, onEvent }) {
  const total = events.reduce((sum, event) => sum + event.duration, 0);
  return (
    <section className="cal-card day-summary">
      <header>
        <div>
          <b>Day summary</b>
          <small>
            {date
              ? new Date(`${date}T12:00`).toLocaleDateString([], {
                  weekday: "long",
                  month: "short",
                  day: "numeric",
                })
              : "Select a day"}
          </small>
        </div>
        <CalendarDays size={17} />
      </header>
      <div className="day-score">
        <strong>{Math.round(total / 6) / 10}h</strong>
        <span>planned</span>
        <i>
          <em style={{ width: `${Math.min(100, total / 7.2)}%` }} />
        </i>
      </div>
      <div className="day-summary-list">
        {events.slice(0, 4).map((event) => (
          <button onClick={() => onEvent(event)} key={event.id}>
            <i className={event.tone} />
            <span>
              <b>{event.title}</b>
              <small>{clock(event.startMinutes)}</small>
            </span>
            <ArrowRight size={13} />
          </button>
        ))}
        {!events.length && <p>No commitments on this day.</p>}
      </div>
    </section>
  );
}

function Unscheduled({ tasks, onEvent, onAdd }) {
  const items = tasks
    .filter(
      (task) => task.status === "open" && !task.deadline && !task.fixed_start,
    )
    .slice(0, 3);
  return (
    <section className="cal-card unscheduled">
      <header>
        <div>
          <b>Unscheduled</b>
          <small>Flexible work waiting for time</small>
        </div>
        <button onClick={onAdd}>
          <Plus size={14} />
        </button>
      </header>
      {items.map((task) => (
        <button onClick={() => onEvent(task)} key={task.id}>
          <span>
            <b>{task.title}</b>
            <small>
              {task.duration_minutes} min · {task.priority}
            </small>
          </span>
          <ArrowRight size={13} />
        </button>
      ))}
      {!items.length && <p>Everything has a planning date.</p>}
    </section>
  );
}

function BottomCard({ icon, tone, eyebrow, title, text, action, onClick }) {
  return (
    <section className="cal-card bottom-card">
      <span className={`bottom-icon ${tone}`}>{icon}</span>
      <div>
        <p>{eyebrow}</p>
        <h3>{title}</h3>
        <small>{text}</small>
      </div>
      <button onClick={onClick}>
        {action} <ArrowRight size={14} />
      </button>
    </section>
  );
}

function EventEditor({ event, task, onClose, onSave, onComplete }) {
  const start = `${String(Math.floor(event.startMinutes / 60)).padStart(2, "0")}:${String(event.startMinutes % 60).padStart(2, "0")}`;
  const endMinutes = event.startMinutes + event.duration;
  const [form, setForm] = useState({
    title: task?.title || event.title,
    date: event.date || keyOf(new Date()),
    start,
    end: `${String(Math.floor(endMinutes / 60)).padStart(2, "0")}:${String(endMinutes % 60).padStart(2, "0")}`,
    description: task?.description || event.detail || "",
    priority: task?.priority || event.label || "medium",
    flexibility: task?.flexibility || event.kind || "flexible",
  });
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const field = (name, value) =>
    setForm((current) => ({ ...current, [name]: value }));
  const submit = async () => {
    setSaving(true);
    const startDate = new Date(`${form.date}T${form.start}:00`);
    const endDate = new Date(`${form.date}T${form.end}:00`);
    await onSave(event, {
      title: form.title,
      description: form.description,
      duration_minutes: Math.max(5, Math.round((endDate - startDate) / 60000)),
      fixed_start:
        form.flexibility === "fixed" ? `${form.date}T${form.start}` : null,
      deadline: `${form.date}T${form.end}`,
      priority: form.priority,
      flexibility: form.flexibility,
    });
    setSaving(false);
  };
  const link = form.description.match(/https?:\/\/\S+/)?.[0];
  return (
    <div
      className="cal-modal-backdrop"
      onMouseDown={(e) => e.target === e.currentTarget && onClose()}
    >
      <div className="event-popup">
        <header>
          <div>
            <span className={`event-mark ${event.tone}`}>
              <CalendarDays size={18} />
            </span>
            <div>
              <small>CALENDAR EVENT</small>
              <h2>{editing ? "Edit event" : form.title}</h2>
            </div>
          </div>
          <nav>
            <button
              onClick={() => setEditing(!editing)}
              aria-label="Edit event"
            >
              <Pencil size={17} />
            </button>
            <button onClick={onClose} aria-label="Close">
              <X size={18} />
            </button>
          </nav>
        </header>
        {editing ? (
          <div className="event-form">
            <label>
              Title
              <input
                value={form.title}
                onChange={(e) => field("title", e.target.value)}
              />
            </label>
            <label>
              Date
              <input
                type="date"
                value={form.date}
                onChange={(e) => field("date", e.target.value)}
              />
            </label>
            <div>
              <label>
                Starts
                <input
                  type="time"
                  value={form.start}
                  onChange={(e) => field("start", e.target.value)}
                />
              </label>
              <label>
                Ends
                <input
                  type="time"
                  value={form.end}
                  onChange={(e) => field("end", e.target.value)}
                />
              </label>
            </div>
            <div>
              <label>
                Priority
                <select
                  value={form.priority}
                  onChange={(e) => field("priority", e.target.value)}
                >
                  <option value="high">High</option>
                  <option value="medium">Medium</option>
                  <option value="low">Low</option>
                </select>
              </label>
              <label>
                Type
                <select
                  value={form.flexibility}
                  onChange={(e) => field("flexibility", e.target.value)}
                >
                  <option value="flexible">Flexible</option>
                  <option value="fixed">Fixed</option>
                  <option value="buffer">Buffer</option>
                </select>
              </label>
            </div>
            <label>
              Notes
              <textarea
                rows="4"
                value={form.description}
                onChange={(e) => field("description", e.target.value)}
                placeholder="Add context, a meeting URL, or preparation notes"
              />
            </label>
          </div>
        ) : (
          <>
            <div className="event-facts">
              <div>
                <CalendarDays size={16} />
                <span>
                  <small>Date</small>
                  <b>
                    {new Date(`${form.date}T12:00`).toLocaleDateString([], {
                      weekday: "long",
                      month: "long",
                      day: "numeric",
                    })}
                  </b>
                </span>
              </div>
              <div>
                <Clock3 size={16} />
                <span>
                  <small>Time</small>
                  <b>
                    {clock(minutesOf(form.start))} –{" "}
                    {clock(minutesOf(form.end))}
                  </b>
                </span>
              </div>
              {link && (
                <a href={link} target="_blank" rel="noreferrer">
                  <Link2 size={16} />
                  <span>
                    <small>Meeting link</small>
                    <b>{link}</b>
                  </span>
                </a>
              )}
            </div>
            <div className="event-tags">
              <span>{form.priority}</span>
              <span>{form.flexibility}</span>
              <span>planning</span>
            </div>
            <div className="event-notes">
              <MessageSquareText size={16} />
              <div>
                <b>Notes</b>
                <p>
                  {form.description ||
                    "No notes yet. Use edit to add preparation details or a meeting link."}
                </p>
              </div>
            </div>
            <div className="attendees">
              <Users size={16} />
              <div>
                <i>KS</i>
                <i>PB</i>
                <i>AI</i>
              </div>
              <small>Plan owner · planning agent</small>
            </div>
          </>
        )}
        <footer>
          <button onClick={() => onComplete(event)}>
            <Check size={14} /> Mark complete
          </button>
          {editing ? (
            <button className="primary" disabled={saving} onClick={submit}>
              {saving ? "Saving…" : "Save changes"}
            </button>
          ) : (
            <button className="primary" onClick={() => setEditing(true)}>
              Edit details
            </button>
          )}
        </footer>
      </div>
    </div>
  );
}

function DayPopup({ detail, onClose, onEvent, onRecovery }) {
  const total = detail.events.reduce((sum, event) => sum + event.duration, 0);
  const fixed = detail.events
    .filter((event) => event.kind === "fixed")
    .reduce((sum, event) => sum + event.duration, 0);
  return (
    <div className="cal-modal-backdrop">
      <div className="day-popup">
        <button className="popup-close" onClick={onClose}>
          <X size={18} />
        </button>
        <p>DAY BREAKDOWN</p>
        <h2>
          {new Date(`${detail.date}T12:00`).toLocaleDateString([], {
            weekday: "long",
            month: "long",
            day: "numeric",
          })}
        </h2>
        <div className="day-popup-metrics">
          <span>
            <strong>{detail.events.length}</strong>
            <small>events</small>
          </span>
          <span>
            <strong>{Math.round(total / 6) / 10}h</strong>
            <small>planned</small>
          </span>
          <span>
            <strong>{Math.round(fixed / 6) / 10}h</strong>
            <small>fixed</small>
          </span>
        </div>
        <div className="day-popup-list">
          {detail.events.map((event) => (
            <button onClick={() => onEvent(event)} key={event.id}>
              <i className={event.tone} />
              <time>{clock(event.startMinutes)}</time>
              <span>
                <b>{event.title}</b>
                <small>
                  {event.duration} minutes · {event.kind}
                </small>
              </span>
              <ChevronRight size={14} />
            </button>
          ))}
          {!detail.events.length && (
            <small>No events scheduled for this day.</small>
          )}
        </div>
        <footer>
          <button onClick={onClose}>Close</button>
          <button
            className="primary"
            onClick={() => {
              onClose();
              onRecovery(30, `${detail.date} schedule changed`);
            }}
          >
            Replan this day <ArrowRight size={14} />
          </button>
        </footer>
      </div>
    </div>
  );
}
