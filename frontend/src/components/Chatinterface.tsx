// frontend/src/components/Chatinterface.tsx

"use client";

import React from "react";
import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
} from "react";
import {
  ArrowUp,
  Ban,
  Check,
  CheckCircle2,
  ChevronDown,
  Circle,
  Copy,
  Globe,
  Loader2,
  Paperclip,
  Presentation,
  Search,
  Sparkles,
  Wand2,
  XCircle,
  Pause,
  Play,
  Square,
  Edit,
  RefreshCw,
  X,
} from "lucide-react";

import { StateInspector } from './StateInspector';
import { SandboxWorkspace } from './SandboxWorkspace';
import { FolderOpen } from 'lucide-react';

// ─── Types ───────────────────────────────────────────────────────

interface PlanStep {
  step_id?: string | number;
  description: string;
  tool_name?: string | null;
  tool_args?: Record<string, any>;
}

interface StepResult {
  step: string;
  tool?: string | null;
  output: string;
  step_index: number;
}

interface Verification {
  status?: string;
  score?: number;
  feedback?: string;
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
  verification?: Verification;
  cost_metrics?: { total_cost_usd?: number };
  error?: string;
  error_code?: string;
  trace?: string[];
  tool_name?: string;
  tool_args?: Record<string, any>;
  step_description?: string;
  step_index?: number;
  state?: any;
  paused_at?: string;
  resumed_at?: string;
}

export interface RecentTaskSummary {
  id: string;
  title: string;
}

export interface ChatInterfaceHandle {
  /** Clears the current thread and returns to the empty-state composer. */
  reset: () => void;
}

interface ChatInterfaceProps {
  /** Lets the parent (page.tsx) feed the sidebar's recent-task list. */
  onTasksChange?: (tasks: RecentTaskSummary[]) => void;
  onActiveTaskChange?: (id: string | null) => void;
}

const THREAD_ID_KEY = "synthai_thread_id";

const QUICK_ACTIONS: { icon: React.ReactNode; label: string; prompt: string }[] = [
  {
    icon: <Presentation className="h-4 w-4" />,
    label: "Create slides",
    prompt: "Create a presentation about AI trends with 5 slides",
  },
  {
    icon: <Globe className="h-4 w-4" />,
    label: "Build website",
    prompt: "Build a simple landing page for my startup",
  },
  {
    icon: <Wand2 className="h-4 w-4" />,
    label: "Design",
    prompt: "Design a logo and brand guide for a tech company",
  },
  {
    icon: <Search className="h-4 w-4" />,
    label: "Research",
    prompt: "Research the latest AI trends and summarize them",
  },
];

function statusPillClasses(status: string) {
  switch (status) {
    case "completed":
      return "bg-green-100 text-green-700";
    case "failed":
    case "error":
      return "bg-red-100 text-red-700";
    case "paused":
      return "bg-yellow-100 text-yellow-700";
    default:
      return "bg-blue-100 text-blue-700";
  }
}

const ChatInterface = forwardRef<ChatInterfaceHandle, ChatInterfaceProps>(function ChatInterface(
  { onTasksChange, onActiveTaskChange },
  ref
) {
  const [task, setTask] = useState("");
  const [loading, setLoading] = useState(false);
  const [isConnected, setIsConnected] = useState(false);
  const [currentStatus, setCurrentStatus] = useState<
    "idle" | "connecting" | "running" | "paused" | "completed" | "failed" | "disconnected" | "error"
  >("idle");

  const [userMessage, setUserMessage] = useState<string | null>(null);
  const [plan, setPlan] = useState<PlanStep[] | null>(null);
  const [stepResults, setStepResults] = useState<Record<number, StepResult>>({});
  const [verification, setVerification] = useState<Verification | null>(null);
  const [finalAnswer, setFinalAnswer] = useState<string | null>(null);
  const [costMetrics, setCostMetrics] = useState<{ total_cost_usd?: number } | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const [pendingConfirmation, setPendingConfirmation] = useState<{
    task_id: string;
    thread_id: string;
    tool_name: string;
    tool_args: Record<string, any>;
    step_description: string;
    step_index: number;
  } | null>(null);

  const [recentTasks, setRecentTasks] = useState<RecentTaskSummary[]>([]);
  const [showInspector, setShowInspector] = useState(false);
  const [showWorkspace, setShowWorkspace] = useState(false);

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectAttemptRef = useRef(0);
  const transcriptEndRef = useRef<HTMLDivElement>(null);
  const threadIdRef = useRef<string | null>(null);
  const isPausedRef = useRef(false);

  const hasStarted = currentStatus !== "idle";

  // ─── Reset Function ─────────────────────────────────────────────

  const reset = useCallback(() => {
    // Clear all state
    setTask("");
    setCurrentStatus("idle");
    setUserMessage(null);
    setPlan(null);
    setStepResults({});
    setVerification(null);
    setFinalAnswer(null);
    setCostMetrics(null);
    setErrorMessage(null);
    setPendingConfirmation(null);
    setLoading(false);
    setShowInspector(false);
    setShowWorkspace(false);
    threadIdRef.current = null;
    isPausedRef.current = false;
    onActiveTaskChange?.(null);
    
    // Close and reconnect WebSocket to clear any pending events
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
    // Reconnect will happen automatically via the effect
    
    console.log("ChatInterface reset - ready for new task");
  }, [onActiveTaskChange]);

  useImperativeHandle(ref, () => ({ reset }), [reset]);

  // ─── Connection ────────────────────────────────────────────────

  const connectWebSocket = useCallback(() => {
    // Don't reconnect if we're paused
    if (isPausedRef.current) {
      console.debug("Skipping WebSocket reconnect - task is paused");
      return;
    }

    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const ws = new WebSocket(`${protocol}//${window.location.host}/ws`);

    ws.onopen = () => {
      setIsConnected(true);
      reconnectAttemptRef.current = 0;
      console.log("WebSocket connected");
    };

    ws.onmessage = (event) => {
      const data: StreamedEvent = JSON.parse(event.data);

      // ─── IGNORE EVENTS WHEN PAUSED ─────────────────────────────
      if (isPausedRef.current) {
        // Only process pause/resume/error events
        if (data.type === "task_paused" || data.type === "task_resumed" || data.type === "error") {
          // Let these through
        } else {
          console.debug("Ignoring event while paused:", data.type);
          return;
        }
      }

      switch (data.type) {
        case "task_start": {
          setCurrentStatus("running");
          if (data.thread_id) {
            threadIdRef.current = data.thread_id;
            localStorage.setItem(THREAD_ID_KEY, data.thread_id);
            onActiveTaskChange?.(data.thread_id);
            setRecentTasks((prev) => {
              const next = [
                { id: data.thread_id as string, title: data.message || "Untitled task" },
                ...prev.filter((t) => t.id !== data.thread_id),
              ].slice(0, 20);
              onTasksChange?.(next);
              return next;
            });
          }
          break;
        }
        case "planner_output": {
          setPlan(Array.isArray(data.content) ? data.content : null);
          break;
        }
        case "executor_output": {
          const result: StepResult = data.content;
          if (result && typeof result.step_index === "number") {
            setStepResults((prev) => ({ ...prev, [result.step_index]: result }));
          }
          break;
        }
        case "verifier_output": {
          setVerification(data.content || null);
          break;
        }
        case "needs_confirmation": {
          setPendingConfirmation({
            task_id: data.task_id || "",
            thread_id: data.thread_id || threadIdRef.current || "",
            tool_name: data.tool_name || "",
            tool_args: data.tool_args || {},
            step_description: data.step_description || "",
            step_index: data.step_index ?? 0,
          });
          setLoading(false);
          break;
        }
        case "task_paused": {
          // Task was paused - update UI
          setCurrentStatus("paused");
          setLoading(false);
          setPendingConfirmation(null);
          // Update state if available
          if (data.state) {
            if (data.state.plan) setPlan(data.state.plan);
            if (data.state.results) {
              const resultsMap: Record<number, any> = {};
              (data.state.results || []).forEach((r: any) => {
                if (r.step_index !== undefined) {
                  resultsMap[r.step_index] = r;
                }
              });
              setStepResults(resultsMap);
            }
          }
          console.log("Task paused:", data.thread_id);
          break;
        }
        case "task_resumed": {
          // Task was resumed
          isPausedRef.current = false;
          setCurrentStatus("running");
          setLoading(true);
          setPendingConfirmation(null);
          console.log("Task resumed:", data.thread_id);
          break;
        }
        case "task_complete": {
          setCurrentStatus((data.status as any) || "completed");
          setFinalAnswer(data.final_answer || null);
          setCostMetrics(data.cost_metrics || null);
          if (Array.isArray(data.plan)) setPlan(data.plan);
          if (data.verification) setVerification(data.verification);
          setLoading(false);
          setPendingConfirmation(null);
          isPausedRef.current = false;
          break;
        }
        case "task_error": {
          setCurrentStatus("failed");
          setErrorMessage(data.error || "Something went wrong while running this task.");
          setLoading(false);
          setPendingConfirmation(null);
          isPausedRef.current = false;
          break;
        }
        case "error": {
          setCurrentStatus("failed");
          setErrorMessage(data.message || data.error || "Unknown error");
          setLoading(false);
          setPendingConfirmation(null);
          isPausedRef.current = false;
          break;
        }
        default:
          break;
      }
    };

    ws.onclose = () => {
      setIsConnected(false);
      // Don't auto-reconnect if paused
      if (!isPausedRef.current) {
        setCurrentStatus((prev) => (prev === "running" ? "disconnected" : prev));
        const delay = Math.min(1000 * 2 ** reconnectAttemptRef.current, 30000);
        setTimeout(connectWebSocket, delay);
        reconnectAttemptRef.current += 1;
      }
    };

    ws.onerror = () => {
      setIsConnected(false);
    };

    wsRef.current = ws;
  }, [onActiveTaskChange, onTasksChange]);

  useEffect(() => {
    connectWebSocket();
    return () => {
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    transcriptEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [plan, stepResults, finalAnswer, pendingConfirmation, errorMessage]);

  // ─── Actions ───────────────────────────────────────────────────

  const submitTask = useCallback(
    (overrideMessage?: string) => {
      const trimmedMessage = (overrideMessage ?? task).trim();
      if (!trimmedMessage) return;
      
      // If we're paused, reset first to clear the old thread
      if (isPausedRef.current || currentStatus === "paused") {
        reset();
      }
      
      if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
        // Try to reconnect
        connectWebSocket();
        // Wait a moment then retry
        setTimeout(() => {
          if (wsRef.current?.readyState === WebSocket.OPEN) {
            submitTask(overrideMessage);
          } else {
            setErrorMessage("WebSocket not connected. Please try again.");
          }
        }, 500);
        return;
      }

      const threadId = `thread-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
      threadIdRef.current = threadId;
      localStorage.setItem(THREAD_ID_KEY, threadId);
      isPausedRef.current = false;

      setLoading(true);
      setCurrentStatus("connecting");
      setUserMessage(trimmedMessage);
      setPlan(null);
      setStepResults({});
      setVerification(null);
      setFinalAnswer(null);
      setCostMetrics(null);
      setErrorMessage(null);
      setPendingConfirmation(null);
      setShowInspector(false);

      wsRef.current.send(
        JSON.stringify({
          action: "run_task",
          message: trimmedMessage,
          user_id: "dashboard",
          tenant_id: "default",
          thread_id: threadId,
        })
      );
      setTask("");
    },
    [task, currentStatus, reset, connectWebSocket]
  );

  const confirmTool = useCallback(() => {
    if (!pendingConfirmation || wsRef.current?.readyState !== WebSocket.OPEN) return;
    wsRef.current.send(
      JSON.stringify({
        action: "confirm_tool",
        task_id: pendingConfirmation.task_id,
        thread_id: pendingConfirmation.thread_id,
        tool_name: pendingConfirmation.tool_name,
        step_index: pendingConfirmation.step_index,
        message: "",
        user_id: "dashboard",
        tenant_id: "default",
      })
    );
    setPendingConfirmation(null);
    setLoading(true);
  }, [pendingConfirmation]);

  const rejectTool = useCallback(() => {
    if (!pendingConfirmation || wsRef.current?.readyState !== WebSocket.OPEN) return;
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

  // ─── Pause Handler ─────────────────────────────────────────────

  const handlePause = useCallback(async () => {
    const threadId = threadIdRef.current;
    if (!threadId) {
      console.warn("No thread ID to pause");
      return;
    }

    // Set pause flag FIRST to prevent WebSocket events
    isPausedRef.current = true;

    // Update UI immediately
    setCurrentStatus("paused");
    setLoading(false);
    setPendingConfirmation(null);

    try {
      const response = await fetch(`/api/tasks/${threadId}/pause`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reason: "User requested pause" }),
      });

      if (!response.ok) {
        const error = await response.json();
        // Revert if pause failed
        isPausedRef.current = false;
        setCurrentStatus("running");
        setLoading(true);
        throw new Error(error.detail || 'Failed to pause task');
      }

      // Close the WebSocket to stop receiving events
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }
      setIsConnected(false);

      console.log("Task paused successfully:", threadId);

    } catch (err) {
      setErrorMessage(err instanceof Error ? err.message : 'Failed to pause task');
      setCurrentStatus("running");
      setLoading(true);
    }
  }, []);

  // ─── Resume Handler ────────────────────────────────────────────

  const handleResume = useCallback(async () => {
    const threadId = threadIdRef.current;
    if (!threadId) {
      console.warn("No thread ID to resume");
      return;
    }

    // Clear pause flag BEFORE resuming
    isPausedRef.current = false;

    setCurrentStatus("connecting");
    setLoading(true);
    setErrorMessage(null);

    try {
      const response = await fetch(`/api/tasks/${threadId}/resume`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      });

      if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail || 'Failed to resume task');
      }

      // Reconnect WebSocket
      connectWebSocket();

      // Wait for connection then send resume action
      const waitForConnection = () => {
        return new Promise((resolve) => {
          if (wsRef.current?.readyState === WebSocket.OPEN) {
            resolve(true);
            return;
          }
          const checkInterval = setInterval(() => {
            if (wsRef.current?.readyState === WebSocket.OPEN) {
              clearInterval(checkInterval);
              resolve(true);
            }
          }, 100);
          // Timeout after 5 seconds
          setTimeout(() => {
            clearInterval(checkInterval);
            resolve(false);
          }, 5000);
        });
      };

      const connected = await waitForConnection();
      if (connected && wsRef.current) {
        wsRef.current.send(
          JSON.stringify({
            action: "resume_task",
            thread_id: threadId,
            user_id: "dashboard",
            tenant_id: "default",
          })
        );
        setCurrentStatus("running");
        setLoading(true);
      } else {
        throw new Error("WebSocket connection failed");
      }

      console.log("Task resumed successfully:", threadId);

    } catch (err) {
      setErrorMessage(err instanceof Error ? err.message : 'Failed to resume task');
      setLoading(false);
      setCurrentStatus("paused");
    }
  }, [connectWebSocket]);

  // ─── Stop Handler ──────────────────────────────────────────────

  const handleStop = useCallback(async () => {
    const threadId = threadIdRef.current;
    if (!threadId) return;

    setLoading(false);
    setCurrentStatus("failed");
    setErrorMessage("Task stopped by user");
    setPendingConfirmation(null);
    isPausedRef.current = false;

    // Close WebSocket
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
    setIsConnected(false);

    // Remove from paused state if any
    try {
      await fetch(`/api/tasks/${threadId}/pause`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reason: "Task stopped by user" }),
      });
    } catch (err) {
      // Ignore errors on stop
    }

    console.log("Task stopped:", threadId);
  }, []);

  // ─── Reset and New Task ────────────────────────────────────────

  const handleNewTask = useCallback(() => {
    reset();
    setTask("");
  }, [reset]);

  // ─── Copy Answer ───────────────────────────────────────────────

  const copyAnswer = useCallback(() => {
    if (!finalAnswer) return;
    navigator.clipboard.writeText(finalAnswer).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });
  }, [finalAnswer]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === "Enter" && !e.shiftKey && !loading && !pendingConfirmation) {
        e.preventDefault();
        submitTask();
      }
    },
    [loading, pendingConfirmation, submitTask]
  );

  // ─── Render helpers ──────────────────────────────────────────────

  const completedCount = Object.keys(stepResults).length;
  const totalSteps = plan?.length ?? 0;

  const composer = (
    <div className="relative">
      <div className="flex items-end gap-2 rounded-2xl border border-gray-200 bg-gray-50 p-2.5 pl-4 shadow-[0_0_0_1px_rgba(99,102,241,0)] transition-shadow focus-within:border-transparent focus-within:shadow-[0_0_0_1.5px_#3b82f6]">
        <button
          type="button"
          title="Attach a file"
          className="mb-1 shrink-0 rounded-lg p-1.5 text-gray-400 transition-colors hover:bg-synthai-surface-hover hover:text-gray-600"
        >
          <Paperclip className="h-4 w-4" />
        </button>
        <textarea
          rows={1}
          value={task}
          onChange={(e) => setTask(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={loading || !!pendingConfirmation}
          placeholder={isPausedRef.current ? "Task paused. Type a new message to reset." : "Assign a task or type / for more"}
          className="max-h-40 flex-1 resize-none bg-transparent py-2 text-[15px] text-gray-900 placeholder-gray-400 outline-none disabled:opacity-60"
        />
        <button
          onClick={() => submitTask()}
          disabled={loading || !task.trim() || !!pendingConfirmation || !isConnected}
          title="Send"
          className="mb-1 flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-brand-gradient text-white transition-opacity disabled:opacity-30"
        >
          {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <ArrowUp className="h-4 w-4" />}
        </button>
      </div>
      {!isConnected && !isPausedRef.current && (
        <p className="mt-2 text-center text-xs text-gray-400">Reconnecting…</p>
      )}
      {isPausedRef.current && (
        <p className="mt-2 text-center text-xs text-yellow-400">
          Task paused. Type a new message or click Resume to continue.
        </p>
      )}
    </div>
  );

  // ─── Empty state ───────────────────────────────────────────────

  if (!hasStarted) {
    return (
      <div className="mx-auto flex w-full max-w-2xl flex-1 flex-col items-center justify-center px-6 bg-white">
        <h1 className="font-serif text-[2.75rem] leading-tight text-gray-900">
          What can I do for you?
        </h1>
        <p className="mb-8 mt-2 text-sm text-gray-500">
          Give synthAI a goal — it plans, runs tools, and checks its own work.
        </p>

        <div className="w-full">{composer}</div>

        <div className="mt-4 flex flex-wrap justify-center gap-2">
          {QUICK_ACTIONS.map((qa) => (
            <button
              key={qa.label}
              onClick={() => submitTask(qa.prompt)}
              className="flex items-center gap-2 rounded-lg border border-synthai-border bg-synthai-surface px-3.5 py-2 text-sm text-gray-600 transition-colors hover:border-brand-500/30 hover:bg-synthai-surface-hover hover:text-gray-900"
            >
              <span className="text-brand-400">{qa.icon}</span>
              {qa.label}
            </button>
          ))}
        </div>
      </div>
    );
  }

  // ─── Active / completed thread ───────────────────────────────────

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-1 flex-col px-6 pb-6 bg-white">
      <div className="flex-1 space-y-4 py-6">
        {/* User message */}
        {userMessage && (
          <div className="flex justify-end">
            <div className="max-w-[85%] rounded-2xl rounded-tr-sm bg-brand-600/90 px-4 py-2.5 text-[15px] text-white">
              {userMessage}
            </div>
          </div>
        )}

        {/* Plan checklist */}
        {plan && plan.length > 0 && (
          <div className="rounded-xl border border-gray-200 bg-gray-50 p-4">
            <div className="mb-3 flex items-center justify-between">
              <p className="text-xs font-semibold uppercase tracking-wide text-gray-400">Plan</p>
              <span className="text-xs text-gray-400">
                {completedCount}/{totalSteps} steps
              </span>
            </div>
            <ol className="space-y-2">
              {plan.map((step, i) => {
                const result = stepResults[i];
                const isNext = !result && i === completedCount && loading;
                return (
                  <li key={i} className="flex items-start gap-2.5 text-sm">
                    {result ? (
                      <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-400" />
                    ) : isNext ? (
                      <Loader2 className="mt-0.5 h-4 w-4 shrink-0 animate-spin text-brand-400" />
                    ) : (
                      <Circle className="mt-0.5 h-4 w-4 shrink-0 text-gray-400" />
                    )}
                    <div className="min-w-0 flex-1">
                      <p className={result ? "text-gray-900" : "text-gray-600"}>
                        {step.description}
                        {step.tool_name && (
                          <span className="ml-2 rounded bg-synthai-surface-hover px-1.5 py-0.5 font-mono text-[11px] text-gray-400">
                            {step.tool_name}
                          </span>
                        )}
                      </p>
                      {result && (
                        <details className="mt-1 group">
                          <summary className="flex cursor-pointer list-none items-center gap-1 text-xs text-gray-400 hover:text-gray-600">
                            <ChevronDown className="h-3 w-3 transition-transform group-open:rotate-180" />
                            Output
                          </summary>
                          <p className="mt-1 whitespace-pre-wrap rounded-lg bg-synthai-surface-light p-2.5 text-xs text-gray-600">
                            {result.output}
                          </p>
                        </details>
                      )}
                    </div>
                  </li>
                );
              })}
            </ol>
          </div>
        )}

        {/* Verification chip */}
        {verification && (
          <div className="flex items-center gap-2 text-xs">
            {verification.status === "PASS" ? (
              <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400" />
            ) : (
              <XCircle className="h-3.5 w-3.5 text-amber-400" />
            )}
            <span className="text-gray-400">
              Verification: {verification.status || "unknown"}
              {typeof verification.score === "number" && ` · ${verification.score}/100`}
            </span>
          </div>
        )}

        {/* Confirmation banner */}
        {pendingConfirmation && (
          <div className="rounded-xl border border-amber-500/25 bg-amber-500/10 p-4">
            <p className="text-sm text-gray-900">
              synthAI wants to run{" "}
              <span className="rounded bg-amber-500/15 px-1.5 py-0.5 font-mono text-xs font-semibold text-amber-300">
                {pendingConfirmation.tool_name}
              </span>
            </p>
            <p className="mt-1 text-xs text-gray-600">{pendingConfirmation.step_description}</p>
            <div className="mt-3 flex gap-2">
              <button
                onClick={confirmTool}
                className="flex items-center gap-1.5 rounded-lg bg-emerald-600 px-3 py-1.5 text-sm font-medium text-white transition-colors hover:bg-emerald-700"
              >
                <Check className="h-3.5 w-3.5" /> Confirm
              </button>
              <button
                onClick={rejectTool}
                className="flex items-center gap-1.5 rounded-lg border border-synthai-border px-3 py-1.5 text-sm font-medium text-gray-600 transition-colors hover:bg-synthai-surface-hover"
              >
                <Ban className="h-3.5 w-3.5" /> Reject
              </button>
            </div>
          </div>
        )}

        {/* Error banner */}
        {errorMessage && (
          <div className="rounded-xl border border-red-500/25 bg-red-500/10 p-4">
            <p className="text-sm font-medium text-red-300">Something went wrong</p>
            <p className="mt-1 whitespace-pre-wrap text-sm text-red-200/80">{errorMessage}</p>
          </div>
        )}

        {/* Final answer */}
        {finalAnswer && (
          <div className="rounded-xl border border-blue-200 bg-blue-50/50 p-4">
            <div className="mb-2 flex items-center justify-between">
              <span className="flex items-center gap-1.5 text-xs font-semibold text-blue-300">
                <Sparkles className="h-3.5 w-3.5" /> Answer
              </span>
              <button
                onClick={copyAnswer}
                className="flex items-center gap-1 text-xs text-gray-400 transition-colors hover:text-gray-600"
              >
                <Copy className="h-3 w-3" /> {copied ? "Copied" : "Copy"}
              </button>
            </div>
            <p className="whitespace-pre-wrap leading-relaxed text-gray-900">{finalAnswer}</p>
            {typeof costMetrics?.total_cost_usd === "number" && (
              <p className="mt-2 text-xs text-gray-400">
                Cost: ${costMetrics.total_cost_usd.toFixed(6)}
              </p>
            )}
          </div>
        )}

        {/* Task Controls - Show when running, paused, or completed */}
        {(currentStatus === "running" || currentStatus === "paused" || currentStatus === "completed") && (
          <div className="flex items-center justify-between bg-synthai-surface-light rounded-lg px-4 py-2 border border-synthai-border">
            <div className="flex items-center gap-3">
              <div className="flex items-center gap-1">
                <span className={`w-2 h-2 rounded-full ${
                  currentStatus === "running" ? "bg-green-400 animate-pulse" :
                  currentStatus === "paused" ? "bg-yellow-400" :
                  "bg-blue-400"
                }`} />
                <span className="text-sm text-gray-600 capitalize">
                  {currentStatus === "running" ? "Running" :
                   currentStatus === "paused" ? "Paused" :
                   "Completed"}
                </span>
              </div>

              <div className="flex gap-1 ml-2">
                {/* Pause - Only show when running */}
                {currentStatus === "running" && (
                  <button
                    onClick={handlePause}
                    className="p-1.5 rounded-lg hover:bg-synthai-surface-hover text-gray-600 hover:text-gray-900 transition-colors"
                    title="Pause task"
                  >
                    <Pause className="w-4 h-4" />
                  </button>
                )}

                {/* Resume - Only show when paused */}
                {currentStatus === "paused" && (
                  <button
                    onClick={handleResume}
                    className="p-1.5 rounded-lg hover:bg-synthai-surface-hover text-gray-600 hover:text-gray-900 transition-colors"
                    title="Resume task"
                  >
                    <Play className="w-4 h-4" />
                  </button>
                )}

                {/* Stop - Only show when running or paused */}
                {(currentStatus === "running" || currentStatus === "paused") && (
                  <button
                    onClick={handleStop}
                    className="p-1.5 rounded-lg hover:bg-red-500/15 text-gray-600 hover:text-red-400 transition-colors"
                    title="Stop task"
                  >
                    <Square className="w-4 h-4" />
                  </button>
                )}

                {/* Modify - Only show when paused */}
                {currentStatus === "paused" && (
                  <button
                    onClick={() => setShowInspector(!showInspector)}
                    className="p-1.5 rounded-lg hover:bg-synthai-surface-hover text-gray-600 hover:text-gray-900 transition-colors"
                    title="Modify plan"
                  >
                    <Edit className="w-4 h-4" />
                  </button>
                )}

                {/* New Task - Always show in task controls */}
                <button
                    onClick={handleNewTask}
                    className="p-1.5 rounded-lg hover:bg-synthai-surface-hover text-gray-600 hover:text-gray-900 transition-colors"
                    title="New task (reset)"
                  >
                  <RefreshCw className="w-4 h-4" />
                </button>

                {/* Workspace */}
                <button
                  onClick={() => setShowWorkspace(!showWorkspace)}
                  className="p-1.5 rounded-lg hover:bg-synthai-surface-hover text-gray-600 hover:text-gray-900 transition-colors"
                  title="Open Workspace"
                >
                  <FolderOpen className="w-4 h-4" />
                </button>
              </div>
            </div>

            <button
              onClick={() => setShowInspector(!showInspector)}
              className="text-xs text-gray-400 hover:text-gray-900 transition-colors"
            >
              {showInspector ? "Hide Details" : "Show Details"}
            </button>
          </div>
        )}

        {/* Loading indicator */}
        {loading && !pendingConfirmation && currentStatus !== "paused" && (
          <div className="flex items-center gap-2 text-xs text-gray-400">
            <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 ${statusPillClasses(currentStatus)}`}>
              <Loader2 className="h-3 w-3 animate-spin" />
              {currentStatus === "connecting" ? "Starting…" : "Working…"}
            </span>
          </div>
        )}

        <div ref={transcriptEndRef} />
      </div>

      {/* State Inspector Modal */}
      {showInspector && threadIdRef.current && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-synthai-background rounded-xl border border-synthai-border max-w-2xl w-full max-h-[80vh] overflow-y-auto p-6">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-lg font-semibold text-gray-900">Task Inspector</h2>
              <button
                onClick={() => setShowInspector(false)}
                className="p-1.5 rounded-lg hover:bg-synthai-surface-hover text-gray-400 hover:text-gray-900"
              >
                <X className="w-5 h-5" />
              </button>
            </div>
            <StateInspector
              threadId={threadIdRef.current}
              onModifyStep={async (id, stepIndex, newStep) => {
                const response = await fetch(`/api/tasks/${id}/modify-step`, {
                  method: 'POST',
                  headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify({ step_index: stepIndex, new_step: newStep }),
                });
                if (!response.ok) throw new Error('Failed to modify step');
                // Refresh inspector
              }}
            />
          </div>
        </div>
      )}

      {/* Workspace Modal */}
      {showWorkspace && (
        <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50 p-4">
          <div className="w-full max-w-6xl h-[80vh] bg-synthai-background rounded-xl border border-synthai-border overflow-hidden">
            <div className="p-3 border-b border-synthai-border bg-synthai-surface-light flex items-center justify-between">
              <h2 className="text-sm font-semibold text-gray-900">Agent Workspace</h2>
              <button
                onClick={() => setShowWorkspace(false)}
                className="p-1.5 rounded-lg hover:bg-synthai-surface-hover text-gray-400 hover:text-gray-900"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
            <SandboxWorkspace userId="default" />
          </div>
        </div>
      )}

      {/* Sticky composer once a thread has started */}
      <div className="sticky bottom-0 bg-white pb-2 pt-4">
        {composer}
      </div>
    </div>
  );
});

export default ChatInterface;