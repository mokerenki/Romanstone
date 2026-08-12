// frontend/src/components/Sidebar.tsx - Manus-style redesign

"use client";

import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import Link from "next/link";
import {
  Bot,
  Puzzle,
  Plug,
  Calendar,
  Library,
  Settings,
  Clock,
  BarChart3,
  Sparkles,
  SquarePen,
  FolderOpen,
  ChevronDown,
  ChevronRight,
} from "lucide-react";

interface NavItem {
  icon: React.ReactNode;
  label: string;
  href: string;
  badge?: string;
}

interface RecentTask {
  id: string;
  title: string;
}

interface SidebarProps {
  onNewTask?: () => void;
  recentTasks?: RecentTask[];
  activeTaskId?: string | null;
  onSelectTask?: (id: string) => void;
}

const NAV_ITEMS: NavItem[] = [
  { icon: <Bot className="w-4 h-4" />, label: "Agent", href: "/agent", badge: "New" },
  { icon: <Puzzle className="w-4 h-4" />, label: "Plugins", href: "/integrations" },
  { icon: <Calendar className="w-4 h-4" />, label: "Scheduled", href: "/scheduled" },
  { icon: <Plug className="w-4 h-4" />, label: "Connectors", href: "/connectors" },
  { icon: <Library className="w-4 h-4" />, label: "Library", href: "/library" },
];

const SECONDARY_ITEMS: NavItem[] = [
  { icon: <Clock className="w-4 h-4" />, label: "History", href: "/history" },
  { icon: <BarChart3 className="w-4 h-4" />, label: "Cost", href: "/cost" },
  { icon: <Settings className="w-4 h-4" />, label: "Settings", href: "/settings" },
];

export default function Sidebar({
  onNewTask,
  recentTasks = [],
  activeTaskId = null,
  onSelectTask,
}: SidebarProps) {
  const [mounted, setMounted] = useState(false);
  const pathname = usePathname();
  const [showRecentTasks, setShowRecentTasks] = useState(true);

  useEffect(() => setMounted(true), []);

  const isActive = (href: string) =>
    href === "/" ? pathname === "/" : pathname === href || pathname?.startsWith(`${href}/`);

  if (!mounted) {
    return <aside className="w-64 h-screen shrink-0 border-r border-gray-200 bg-white" />;
  }

  return (
    <aside className="sticky top-0 flex h-screen w-64 shrink-0 flex-col border-r border-gray-200 bg-white">
      {/* Brand */}
      <div className="flex items-center gap-2 px-4 py-4">
        <Sparkles className="h-5 w-5 text-blue-600" />
        <span className="text-gradient text-lg font-bold tracking-tight">synthAI</span>
        <span className="ml-auto text-xs text-gray-400">v2</span>
      </div>

      {/* New task - primary CTA */}
      <div className="px-3 pb-3">
        <button
          onClick={onNewTask}
          className="flex w-full items-center gap-2 rounded-lg bg-blue-600 px-3 py-2.5 text-sm font-medium text-white transition-colors hover:bg-blue-700"
        >
          <SquarePen className="h-4 w-4" />
          New task
        </button>
      </div>

      {/* Navigation */}
      <nav className="space-y-0.5 px-3">
        {NAV_ITEMS.map((item) => {
          const active = isActive(item.href);
          return (
            <Link
              key={item.href}
              href={item.href}
              className={`flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors ${
                active
                  ? "bg-blue-50 text-blue-700 font-medium"
                  : "text-gray-600 hover:bg-gray-100 hover:text-gray-900"
              }`}
            >
              <span className={active ? "text-blue-600" : "text-gray-400"}>{item.icon}</span>
              <span className="flex-1">{item.label}</span>
              {item.badge && (
                <span className="rounded-full bg-blue-100 px-1.5 py-0.5 text-[10px] font-medium text-blue-700">
                  {item.badge}
                </span>
              )}
            </Link>
          );
        })}
      </nav>

      <div className="mx-3 my-3 border-t border-gray-200" />

      {/* Recent Tasks - Like Manus sidebar */}
      <div className="flex-1 overflow-y-auto px-3">
        <button
          onClick={() => setShowRecentTasks(!showRecentTasks)}
          className="flex w-full items-center justify-between rounded-lg px-2 py-1.5 text-xs font-medium text-gray-500 hover:bg-gray-100"
        >
          <span>TASKS</span>
          {showRecentTasks ? (
            <ChevronDown className="h-3 w-3" />
          ) : (
            <ChevronRight className="h-3 w-3" />
          )}
        </button>

        {showRecentTasks && (
          <div className="mt-1 space-y-0.5">
            {recentTasks.length === 0 ? (
              <p className="px-2 py-3 text-xs text-gray-400">No tasks yet</p>
            ) : (
              recentTasks.map((task) => (
                <button
                  key={task.id}
                  onClick={() => onSelectTask?.(task.id)}
                  className={`block w-full rounded-lg px-3 py-2 text-left text-sm transition-colors ${
                    activeTaskId === task.id
                      ? "bg-blue-50 text-blue-700 font-medium"
                      : "text-gray-600 hover:bg-gray-100 hover:text-gray-900"
                  }`}
                >
                  <span className="line-clamp-1">{task.title}</span>
                </button>
              ))
            )}
          </div>
        )}
      </div>

      {/* Secondary nav at bottom */}
      <div className="border-t border-gray-200 px-3 py-3">
        <nav className="space-y-0.5">
          {SECONDARY_ITEMS.map((item) => {
            const active = isActive(item.href);
            return (
              <Link
                key={item.href}
                href={item.href}
                className={`flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors ${
                  active
                    ? "bg-blue-50 text-blue-700 font-medium"
                    : "text-gray-600 hover:bg-gray-100 hover:text-gray-900"
                }`}
              >
                <span className={active ? "text-blue-600" : "text-gray-400"}>{item.icon}</span>
                <span>{item.label}</span>
              </Link>
            );
          })}
        </nav>
      </div>
    </aside>
  );
}