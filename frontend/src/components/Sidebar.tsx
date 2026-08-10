"use client";

import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import Link from "next/link";
import {
  Bot,
  Puzzle,
  Calendar,
  Library,
  Settings,
  ChevronLeft,
  ChevronRight,
  Clock,
  BarChart3,
  Sparkles,
  SquarePen,
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
  /** Called when the user clicks "New task" — parent resets the composer/thread. */
  onNewTask?: () => void;
  /** Most recent tasks, newest first. Rendered the way Manus lists its task history. */
  recentTasks?: RecentTask[];
  /** Which recent task (if any) is currently open, for highlighting. */
  activeTaskId?: string | null;
  onSelectTask?: (id: string) => void;
}

const NAV_ITEMS: NavItem[] = [
  { icon: <Bot className="w-[18px] h-[18px]" />, label: "Agent", href: "/agent", badge: "New" },
  { icon: <Puzzle className="w-[18px] h-[18px]" />, label: "Plugins", href: "/integrations" },
  { icon: <Calendar className="w-[18px] h-[18px]" />, label: "Scheduled", href: "/scheduled" },
  { icon: <Clock className="w-[18px] h-[18px]" />, label: "History", href: "/history" },
  { icon: <Library className="w-[18px] h-[18px]" />, label: "Library", href: "/library" },
];

const SECONDARY_ITEMS: NavItem[] = [
  { icon: <BarChart3 className="w-[18px] h-[18px]" />, label: "Cost", href: "/cost" },
  { icon: <Settings className="w-[18px] h-[18px]" />, label: "Settings", href: "/settings" },
];

export default function Sidebar({
  onNewTask,
  recentTasks = [],
  activeTaskId = null,
  onSelectTask,
}: SidebarProps) {
  const [collapsed, setCollapsed] = useState(false);
  const [mounted, setMounted] = useState(false);
  const pathname = usePathname();

  useEffect(() => setMounted(true), []);

  useEffect(() => {
    const handleResize = () => {
      if (window.innerWidth < 768) setCollapsed(true);
    };
    handleResize();
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, []);

  const isActive = (href: string) =>
    href === "/" ? pathname === "/" : pathname === href || pathname?.startsWith(`${href}/`);

  // Avoid a hydration mismatch on the collapsed/expanded width.
  if (!mounted) {
    return <aside className="w-64 h-screen shrink-0 border-r border-synthai-border bg-synthai-surface/95" />;
  }

  const renderNavItem = (item: NavItem) => {
    const active = isActive(item.href);
    return (
      <Link
        key={item.href}
        href={item.href}
        title={collapsed ? item.label : undefined}
        className={`group flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors ${
          active
            ? "bg-brand-500/15 text-brand-300"
            : "text-text-secondary hover:bg-synthai-surface-hover hover:text-text-primary"
        } ${collapsed ? "justify-center" : ""}`}
      >
        <span className={active ? "text-brand-400" : "text-text-muted group-hover:text-text-secondary"}>
          {item.icon}
        </span>
        {!collapsed && (
          <>
            <span className="flex-1 font-medium">{item.label}</span>
            {item.badge && (
              <span className="rounded-full bg-brand-500/15 px-1.5 py-0.5 text-[10px] font-semibold text-brand-300">
                {item.badge}
              </span>
            )}
          </>
        )}
      </Link>
    );
  };

  return (
    <aside
      className={`sticky top-0 flex h-screen shrink-0 flex-col border-r border-synthai-border bg-synthai-surface/95 backdrop-blur-sm transition-[width] duration-200 ${
        collapsed ? "w-16" : "w-64"
      }`}
    >
      {/* Brand + collapse toggle */}
      <div className="flex items-center justify-between px-3 py-4">
        {!collapsed ? (
          <Link href="/" className="flex items-center gap-2 px-1">
            <Sparkles className="h-5 w-5 text-brand-400" />
            <span className="text-gradient text-lg font-bold tracking-tight">synthAI</span>
          </Link>
        ) : (
          <Sparkles className="mx-auto h-5 w-5 text-brand-400" />
        )}
        {!collapsed && (
          <button
            onClick={() => setCollapsed(true)}
            aria-label="Collapse sidebar"
            className="rounded-lg p-1.5 text-text-muted transition-colors hover:bg-synthai-surface-hover hover:text-text-secondary"
          >
            <ChevronLeft className="h-4 w-4" />
          </button>
        )}
      </div>

      {/* New task — the one prominent action, mirrors Manus's primary entry point */}
      <div className="px-3 pb-3">
        <button
          onClick={onNewTask}
          title={collapsed ? "New task" : undefined}
          className={`flex w-full items-center gap-2 rounded-lg border border-synthai-border bg-synthai-surface-light px-3 py-2.5 text-sm font-medium text-text-primary transition-colors hover:border-brand-500/40 hover:bg-synthai-surface-hover ${
            collapsed ? "justify-center" : ""
          }`}
        >
          <SquarePen className="h-4 w-4 text-brand-400" />
          {!collapsed && "New task"}
        </button>
      </div>

      {collapsed && (
        <button
          onClick={() => setCollapsed(false)}
          aria-label="Expand sidebar"
          className="mx-auto mb-2 rounded-lg p-1.5 text-text-muted transition-colors hover:bg-synthai-surface-hover hover:text-text-secondary"
        >
          <ChevronRight className="h-4 w-4" />
        </button>
      )}

      {/* Nav */}
      <nav className="space-y-0.5 px-3">
        {NAV_ITEMS.map(renderNavItem)}
      </nav>

      <div className="mx-3 my-3 border-t border-synthai-border" />

      <nav className="space-y-0.5 px-3">
        {SECONDARY_ITEMS.map(renderNavItem)}
      </nav>

      {/* Recent tasks — scrollable, fills remaining space */}
      {!collapsed && (
        <div className="mt-4 flex min-h-0 flex-1 flex-col px-3">
          <p className="px-1 pb-2 text-xs font-semibold uppercase tracking-wide text-text-muted">
            Tasks
          </p>
          <div className="min-h-0 flex-1 space-y-0.5 overflow-y-auto pb-2">
            {recentTasks.length === 0 ? (
              <p className="px-1 py-2 text-xs text-text-muted">No tasks yet</p>
            ) : (
              recentTasks.map((t) => (
                <button
                  key={t.id}
                  onClick={() => onSelectTask?.(t.id)}
                  title={t.title}
                  className={`block w-full truncate rounded-lg px-2 py-1.5 text-left text-xs transition-colors ${
                    activeTaskId === t.id
                      ? "bg-synthai-surface-hover text-text-primary"
                      : "text-text-secondary hover:bg-synthai-surface-hover hover:text-text-primary"
                  }`}
                >
                  {t.title}
                </button>
              ))
            )}
          </div>
        </div>
      )}
      {collapsed && <div className="flex-1" />}

      {/* Account footer */}
      <div className="border-t border-synthai-border p-3">
        <div className={`flex items-center gap-3 ${collapsed ? "justify-center" : ""}`}>
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-brand-gradient text-sm font-semibold text-white">
            VL
          </div>
          {!collapsed && (
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium text-text-primary">Victor Lefoka</p>
              <p className="text-xs text-text-muted">Beta</p>
            </div>
          )}
        </div>
      </div>
    </aside>
  );
}