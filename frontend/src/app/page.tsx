"use client";

import { useState, useCallback, useEffect, useRef } from "react";
import Sidebar from "@/components/Sidebar";
import StatsCards from "@/components/StatsCards";
import QuickActions from "@/components/QuickActions";
import TaskCard from "@/components/TaskCard";
import { Sparkles, Loader2, Bot } from "lucide-react";

interface PlanStep {
  action: string;
  tool?: string;
  args?: Record<string, any>;
  description: string;
}

interface StreamedEvent {
  type: string;
  task_id?: string;
  thread_id?: string;
  message?: string;
  timestamp: string;
  content?: any;
  status?: string;
  final_answer?: string;
  plan?: PlanStep[];
  verification?: any;
  cost_metrics?: { total_cost_usd: number };
  error?: string;
  trace?: string[];
  tool_name?: string;
  tool_args?: Record<string, any>;
  step_description?: string;
  step_index?: number;
}

const THREAD_ID_KEY = "synthai_thread_id";

export default function Home() {
  const [task, setTask] = useState("");
  const [loading, setLoading] = useState(false);
  const [events, setEvents] = useState<StreamedEvent[]>([]);
  const [currentStatus, setCurrentStatus] = useState("idle");
  const [finalAnswer, setFinalAnswer] = useState<string | null>(null);
  const [costMetrics, setCostMetrics] = useState<{ total_cost_usd: number } | null>(null);
  const [pendingConfirmation, setPendingConfirmation] = useState<{
    task_id: string;
    thread_id: string;
    tool_name: string;
    tool_args: Record<string, any>;
    step_description: string;
    step_index: number;
  } | null>(null);
  const [isConnected, setIsConnected] = useState(false);
  
  const wsRef = useRef<WebSocket | null>(null);
  const eventLogRef = useRef<HTMLDivElement>(null);
  const reconnectAttemptRef = useRef(0);
  const inputRef = useRef<HTMLInputElement>(null);

  const connectWebSocket = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      console.log("WebSocket already open");
      return;
    }

    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const ws = new WebSocket(`${protocol}//${window.location.host}/ws`);

    ws.onopen = () => {
      console.log("WebSocket connected successfully");
      setIsConnected(true);
      reconnectAttemptRef.current = 0;

      const savedThreadId = localStorage.getItem(THREAD_ID_KEY);
      if (savedThreadId && currentStatus !== "idle") {
        console.log("Resuming task with thread:", savedThreadId);
        ws.send(
          JSON.stringify({
            action: "resume_task",
            thread_id: savedThreadId,
          })
        );
      }
    };

    ws.onmessage = (event) => {
      console.log("Received WebSocket message:", event.data);
      const data: StreamedEvent = JSON.parse(event.data);
      console.log("Parsed event:", data);
      setEvents((prev) => [...prev, data]);

      if (data.type === "task_start") {
        setCurrentStatus("running");
        setFinalAnswer(null);
        setCostMetrics(null);
        if (data.thread_id) {
          localStorage.setItem(THREAD_ID_KEY, data.thread_id);
        }
      } else if (data.type === "task_complete") {
        setCurrentStatus(data.status || "completed");
        setFinalAnswer(data.final_answer || null);
        setCostMetrics(data.cost_metrics || null);
        setLoading(false);
        setPendingConfirmation(null);
      } else if (data.type === "task_error") {
        setCurrentStatus("failed");
        setFinalAnswer(`Error: ${data.error}\n${data.trace?.join("\n") || ""}`);
        setLoading(false);
        setPendingConfirmation(null);
      } else if (data.type === "error") {
        setCurrentStatus("failed");
        setFinalAnswer(`Error: ${data.message || data.error || "Unknown error"}`);
        setLoading(false);
        setPendingConfirmation(null);
      } else if (data.type === "needs_confirmation") {
        setPendingConfirmation({
          task_id: data.task_id || "",
          thread_id: data.thread_id || localStorage.getItem(THREAD_ID_KEY) || "",
          tool_name: data.tool_name || "",
          tool_args: data.tool_args || {},
          step_description: data.step_description || "",
          step_index: data.step_index ?? 0,
        });
      }
    };

    ws.onclose = (event) => {
      console.log("WebSocket disconnected", {
        code: event.code,
        reason: event.reason,
        wasClean: event.wasClean,
      });
      setIsConnected(false);
      if (loading) {
        setCurrentStatus("disconnected");
      }
      const delay = Math.min(1000 * 2 ** reconnectAttemptRef.current, 30000);
      setTimeout(connectWebSocket, delay);
      reconnectAttemptRef.current += 1;
    };

    ws.onerror = (event) => {
      console.error("WebSocket error:", event);
      setIsConnected(false);
      setCurrentStatus("error");
      setLoading(false);
    };

    wsRef.current = ws;
  }, [loading, currentStatus]);

  useEffect(() => {
    connectWebSocket();
    return () => {
      wsRef.current?.close();
    };
  }, [connectWebSocket]);

  useEffect(() => {
    if (eventLogRef.current) {
      eventLogRef.current.scrollTop = eventLogRef.current.scrollHeight;
    }
  }, [events]);

  // CRITICAL FIX: Read message from state directly, not from ref
  const submitTask = useCallback(() => {
    // Use the state value directly - this is the most reliable approach
    const trimmedMessage = task.trim();
    
    console.log("DEBUG - submitTask called");
    console.log("DEBUG - task state value:", task);
    console.log("DEBUG - trimmed message:", trimmedMessage);
    
    if (!trimmedMessage) {
      console.warn("Message is empty!");
      alert("Please type a message before running the agent.");
      return;
    }
    
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
      console.warn("WebSocket not open. ReadyState:", wsRef.current?.readyState);
      alert("WebSocket is not connected. Please refresh the page.");
      return;
    }
    
    const threadId = `thread-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    localStorage.setItem(THREAD_ID_KEY, threadId);
    setLoading(true);
    setEvents([]);
    setFinalAnswer(null);
    setCostMetrics(null);
    setPendingConfirmation(null);
    setCurrentStatus("connecting");

    const payload = {
      action: "run_task",
      message: trimmedMessage,
      user_id: "dashboard",
      tenant_id: "default",
      thread_id: threadId,
    };
    
    console.log("Sending WebSocket payload:", payload);
    wsRef.current.send(JSON.stringify(payload));
    
    // Clear the input field
    if (inputRef.current) {
      inputRef.current.value = "";
    }
    setTask("");
  }, [task]);

  const confirmTool = useCallback(() => {
    if (!pendingConfirmation || !wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
      console.warn("Cannot confirm - no pending confirmation or WebSocket not open");
      return;
    }
    
    wsRef.current.send(
      JSON.stringify({
        action: "confirm_tool",
        task_id: pendingConfirmation.task_id,
        thread_id: pendingConfirmation.thread_id,
        tool_name: pendingConfirmation.tool_name,
        step_index: pendingConfirmation.step_index,
        message: task,
        user_id: "dashboard",
        tenant_id: "default",
      })
    );
    setPendingConfirmation(null);
    setLoading(true);
  }, [pendingConfirmation, task]);

  const rejectTool = useCallback(() => {
    if (!pendingConfirmation || !wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
      console.warn("Cannot reject - no pending confirmation or WebSocket not open");
      return;
    }
    
    wsRef.current.send(
      JSON.stringify({
        action: "reject_tool",
        task_id: pendingConfirmation.task_id,
        thread_id: pendingConfirmation.thread_id,
        step_index: pendingConfirmation.step_index,
        message: "",
        user_id: "dashboard",
        tenant_id: "default",
      })
    );
    setPendingConfirmation(null);
    setLoading(true);
  }, [pendingConfirmation]);

  const handleQuickAction = useCallback((action: string) => {
    const prompts: Record<string, string> = {
      create_slides: "Create a presentation about AI trends with 5 slides",
      build_website: "Build a simple landing page for my startup",
      design: "Design a logo and brand guide for a tech company",
      create_games: "Create a simple game in Python",
      research: "Research the latest AI trends and summarize them",
      analyze: "Analyze the current market for autonomous agents",
      document: "Create a document about our product roadmap",
      draft_email: "Draft a professional email to a potential client",
      sales_outreach: "Write a sales outreach message for a new product",
      financial_analysis: "Analyze the financial performance of a company",
      market_trends: "What are the current trends in the AI market?",
      compliance_check: "What compliance requirements apply to AI companies?",
    };
    const prompt = prompts[action] || action;
    setTask(prompt);
    if (inputRef.current) {
      inputRef.current.value = prompt;
    }
    // Auto-submit after a moment
    setTimeout(() => {
      if (prompt) submitTask();
    }, 300);
  }, [submitTask]);

  const handleKeyDown = useCallback((e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" && !loading && !pendingConfirmation) {
      e.preventDefault();
      submitTask();
    }
  }, [loading, pendingConfirmation, submitTask]);

  // Get recent tasks from events
  const recentTasks = events
    .filter(e => e.type === "task_start" || e.type === "task_complete")
    .slice(-5)
    .reverse();

  return (
    <div className="flex min-h-screen bg-[#0a0a16]">
      <Sidebar />
      
      <div className="flex-1 flex flex-col min-h-screen">
        {/* Header */}
        <header className="flex items-center justify-between p-4 border-b border-[#2a2a42] bg-[#12121f]/50 backdrop-blur-sm sticky top-0 z-10">
          <div className="flex items-center gap-3">
            <h1 className="text-xl font-bold text-[#f0f0ff]">Dashboard</h1>
            <span className="text-xs px-2 py-0.5 bg-indigo-500/20 text-indigo-400 rounded-full border border-indigo-500/20">
              Phase 3
            </span>
          </div>
          <div className="flex items-center gap-4">
            <div className="flex items-center gap-2">
              <span className={`inline-block w-2 h-2 rounded-full ${isConnected ? 'bg-green-500' : 'bg-red-500'}`}></span>
              <span className="text-xs text-[#9090b0]">{isConnected ? 'Connected' : 'Disconnected'}</span>
            </div>
            <div className="flex items-center gap-2 px-3 py-1.5 bg-[#1a1a2e] rounded-lg border border-[#2a2a42]">
              <span className="text-xs text-[#9090b0]">Free plan</span>
              <button className="text-xs text-indigo-400 hover:text-indigo-300 transition-colors">
                Upgrade
              </button>
            </div>
          </div>
        </header>

        {/* Main Content */}
        <main className="flex-1 p-6 space-y-6 max-w-7xl mx-auto w-full">
          {/* Stats Cards */}
          <StatsCards />

          {/* Task Input Area */}
          <div className="bg-[#12121f]/30 rounded-2xl p-6 border border-[#2a2a42]/50 backdrop-blur-sm">
            <div className="flex items-center gap-2 mb-4">
              <Bot className="w-5 h-5 text-indigo-400" />
              <span className="text-sm font-medium text-[#9090b0]">What can I do for you?</span>
            </div>
            
            <div className="flex gap-3">
              <div className="flex-1 relative">
                <input
                  ref={inputRef}
                  className="w-full p-4 pr-12 bg-[#1a1a2e] border border-[#2a2a42] rounded-xl focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent text-[#f0f0ff] placeholder-[#606080] transition-all"
                  placeholder="Assign a task or type / for more..."
                  value={task}
                  onChange={(e) => {
                    console.log("Input changed to:", e.target.value);
                    setTask(e.target.value);
                  }}
                  onKeyDown={handleKeyDown}
                  disabled={loading || !!pendingConfirmation}
                />
                <kbd className="absolute right-3 top-1/2 -translate-y-1/2 px-2 py-1 text-xs text-[#606080] bg-[#2a2a42] rounded border border-[#3a3a52] font-mono">
                  ⌘K
                </kbd>
              </div>
              <button
                onClick={submitTask}
                disabled={loading || !task.trim() || !!pendingConfirmation || !isConnected}
                className="px-6 py-4 bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed rounded-xl font-semibold text-white transition-colors flex items-center gap-2"
              >
                {loading ? <Loader2 className="w-5 h-5 animate-spin" /> : <Sparkles className="w-5 h-5" />}
                Run
              </button>
            </div>

            {/* Quick Actions */}
            <div className="mt-4">
              <QuickActions onAction={handleQuickAction} />
            </div>
          </div>

          {/* Recent Tasks */}
          <div>
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-lg font-semibold text-[#f0f0ff]">Recent Tasks</h2>
              <button className="text-sm text-indigo-400 hover:text-indigo-300 transition-colors">
                View all →
              </button>
            </div>
            <div className="space-y-2">
              {recentTasks.length === 0 ? (
                <div className="text-center py-12 text-[#606080] bg-[#12121f]/20 rounded-2xl border border-[#2a2a42]/30">
                  <Bot className="w-12 h-12 mx-auto mb-3 text-[#2a2a42]" />
                  <p>No tasks yet. Start by asking something!</p>
                </div>
              ) : (
                recentTasks.map((event, index) => (
                  <TaskCard
                    key={event.task_id || index}
                    id={event.task_id || `task-${index}`}
                    title={event.message || "Untitled task"}
                    status={event.type === "task_complete" ? "completed" : "running"}
                    time={new Date(event.timestamp).toLocaleTimeString()}
                    cost={event.cost_metrics?.total_cost_usd}
                    onSelect={() => {
                      if (event.task_id) {
                        console.log("Selected task:", event.task_id);
                      }
                    }}
                  />
                ))
              )}
            </div>
          </div>

          {/* Task Output (when running) */}
          {currentStatus !== "idle" && (
            <div className="bg-[#12121f]/30 rounded-2xl p-6 border border-[#2a2a42]/50 backdrop-blur-sm">
              <div className="flex items-center gap-3 mb-4">
                <span className="text-sm font-medium text-[#f0f0ff]">Output</span>
                <span className={`text-xs px-2 py-0.5 rounded-full ${
                  currentStatus === "completed" ? "bg-green-500/20 text-green-400" :
                  currentStatus === "failed" ? "bg-red-500/20 text-red-400" :
                  "bg-indigo-500/20 text-indigo-400"
                }`}>
                  {currentStatus}
                </span>
                {loading && (
                  <span className="flex items-center gap-1 text-xs text-[#9090b0]">
                    <Loader2 className="w-3 h-3 animate-spin" />
                    Processing...
                  </span>
                )}
              </div>
              <div className="space-y-4 max-h-96 overflow-y-auto" ref={eventLogRef}>
                {events.map((event, index) => (
                  <div key={index} className="text-sm">
                    {event.type === "planner_output" && (
                      <div className="bg-[#1a1a2e] rounded-lg p-3 border border-[#2a2a42]/50">
                        <p className="text-[#9090b0] text-xs mb-1 flex items-center gap-2">
                          <span>📋</span> Plan
                        </p>
                        <pre className="text-xs text-[#c0c0d0] whitespace-pre-wrap overflow-auto max-h-32">
                          {JSON.stringify(event.content, null, 2)}
                        </pre>
                      </div>
                    )}
                    {event.type === "executor_output" && (
                      <div className="bg-[#1a1a2e] rounded-lg p-3 border border-[#2a2a42]/50">
                        <p className="text-[#9090b0] text-xs mb-1 flex items-center gap-2">
                          <span>🔧</span> Step: {event.content?.step}
                        </p>
                        {event.content?.tool && (
                          <p className="text-xs text-[#606080]">Tool: {event.content.tool}</p>
                        )}
                        <p className="text-[#c0c0d0] whitespace-pre-wrap text-sm mt-1">
                          {event.content?.output}
                        </p>
                      </div>
                    )}
                    {event.type === "verifier_output" && (
                      <div className="bg-[#1a1a2e] rounded-lg p-3 border border-[#2a2a42]/50">
                        <p className="text-[#9090b0] text-xs mb-1 flex items-center gap-2">
                          <span>✅</span> Verification
                        </p>
                        <p className="text-[#c0c0d0] text-xs whitespace-pre-wrap">
                          {JSON.stringify(event.content, null, 2)}
                        </p>
                      </div>
                    )}
                    {event.type === "task_complete" && event.final_answer && (
                      <div className="bg-indigo-600/10 border border-indigo-500/20 rounded-xl p-4">
                        <p className="text-indigo-400 text-xs mb-2 flex items-center gap-2">
                          <span>✨</span> Final Answer
                        </p>
                        <p className="text-[#f0f0ff] whitespace-pre-wrap leading-relaxed">
                          {event.final_answer}
                        </p>
                        {event.cost_metrics && (
                          <p className="text-xs text-[#606080] mt-2">
                            Cost: ${event.cost_metrics.total_cost_usd.toFixed(6)}
                          </p>
                        )}
                      </div>
                    )}
                    {event.type === "task_error" && (
                      <div className="bg-red-600/10 border border-red-500/20 rounded-xl p-4">
                        <p className="text-red-400 text-xs mb-1 flex items-center gap-2">
                          <span>❌</span> Error
                        </p>
                        <p className="text-red-300 whitespace-pre-wrap text-sm">
                          {event.error || event.message}
                        </p>
                      </div>
                    )}
                    {event.type === "needs_confirmation" && (
                      <div className="bg-yellow-600/10 border border-yellow-500/20 rounded-xl p-4">
                        <p className="text-yellow-400 text-xs mb-2 flex items-center gap-2">
                          <span>⚠️</span> Confirmation Required
                        </p>
                        <p className="text-[#c0c0d0] text-sm">
                          The agent wants to run <span className="font-mono font-bold text-yellow-300">{event.tool_name}</span>
                        </p>
                        <p className="text-[#9090b0] text-xs mt-1">{event.step_description}</p>
                        {pendingConfirmation && (
                          <div className="flex gap-3 mt-3">
                            <button
                              onClick={confirmTool}
                              className="px-4 py-2 bg-green-600 hover:bg-green-700 rounded-lg font-semibold text-sm text-white transition-colors"
                            >
                              Confirm
                            </button>
                            <button
                              onClick={rejectTool}
                              className="px-4 py-2 bg-red-600 hover:bg-red-700 rounded-lg font-semibold text-sm text-white transition-colors"
                            >
                              Reject
                            </button>
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}
        </main>
      </div>
    </div>
  );
}