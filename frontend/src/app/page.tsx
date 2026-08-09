"use client";

import { useCallback, useRef, useState } from "react";
import Sidebar from "@/components/Sidebar";
import ChatInterface, {
  ChatInterfaceHandle,
  RecentTaskSummary,
} from "@/components/Chatinterface";

export default function Home() {
  const [recentTasks, setRecentTasks] = useState<RecentTaskSummary[]>([]);
  const [activeTaskId, setActiveTaskId] = useState<string | null>(null);
  const chatRef = useRef<ChatInterfaceHandle>(null);

  const handleNewTask = useCallback(() => {
    chatRef.current?.reset();
  }, []);

  return (
    <div className="flex h-screen bg-synthai-background">
      <Sidebar
        onNewTask={handleNewTask}
        recentTasks={recentTasks}
        activeTaskId={activeTaskId}
        onSelectTask={setActiveTaskId}
      />

      <div className="flex min-w-0 flex-1 flex-col">
        {/* Slim top bar — mirrors the reference layout's plan pill, without
            leaking internal build labels ("Phase 3") into the product UI. */}
        <header className="flex items-center justify-between border-b border-synthai-border px-6 py-3">
          <span className="text-sm font-medium text-text-secondary">synthAI Agent</span>
          <div className="flex items-center gap-3 text-xs">
            <span className="rounded-full bg-synthai-surface-light px-3 py-1 text-text-secondary">
              Free plan
            </span>
            <button className="font-medium text-brand-400 transition-colors hover:text-brand-300">
              Upgrade
            </button>
          </div>
        </header>

        <ChatInterface
          ref={chatRef}
          onTasksChange={setRecentTasks}
          onActiveTaskChange={setActiveTaskId}
        />
      </div>
    </div>
  );
}