import {
  Activity,
  CalendarDays,
  Code2,
  Home,
  LayoutDashboard,
  ListTodo,
  RotateCcw,
  Settings,
  Sparkles,
} from "lucide-react";

export const navigation = [
  { id: "dashboard", label: "Dashboard", icon: LayoutDashboard },
  { id: "day", label: "My Day", icon: Home },
  { id: "calendar", label: "Calendar", icon: CalendarDays },
  { id: "tasks", label: "Tasks & Projects", icon: ListTodo },
  { id: "assistant", label: "AI Assistant", icon: Sparkles },
  { id: "recovery", label: "Recovery", icon: RotateCcw },
  { id: "patterns", label: "Patterns", icon: Activity },
  { id: "mcp", label: "MCP Tools", icon: Code2 },
  { id: "settings", label: "Settings", icon: Settings },
];
