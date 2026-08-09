"use client";

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
} from "lucide-react";

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
      return "bg-emerald-500/15 text-emerald-300";
    case "failed":
    case "error":
      return "bg-red-500/15 text-red-300";
    default:
      return "bg-brand-500/15 text-brand-300";
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
    "idle" | "connecting" | "running" | "completed" | "failed" | "disconnected" | "error"
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

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectAttemptRef = useRef(0);
  const transcriptEndRef = useRef<HTMLDivElement>(null);
  const threadIdRef = useRef<string | null>(null);

  const hasStarted = currentStatus !== "idle";

  // ─── Connection ────────────────────────────────────────────────

  const connectWebSocket = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const ws = new WebSocket(`${protocol}//${window.location.host}/ws`);

    ws.onopen = () => {
      setIsConnected(true);
      reconnectAttemptRef.current = 0;
    };

    ws.onmessage = (event) => {
      const data: StreamedEvent = JSON.parse(event.data);

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
        case "task_complete": {
          setCurrentStatus((data.status as any) || "completed");
          setFinalAnswer(data.final_answer || null);
          setCostMetrics(data.cost_metrics || null);
          if (Array.isArray(data.plan)) setPlan(data.plan);
          if (data.verification) setVerification(data.verification);
          setLoading(false);
          setPendingConfirmation(null);
          break;
        }
        case "task_error": {
          setCurrentStatus("failed");
          setErrorMessage(data.error || "Something went wrong while running this task.");
          setLoading(false);
          setPendingConfirmation(null);
          break;
        }
        case "error": {
          setCurrentStatus("failed");
          setErrorMessage(data.message || data.error || "Unknown error");
          setLoading(false);
          setPendingConfirmation(null);
          break;
        }
        default:
          break;
      }
    };

    ws.onclose = () => {
      setIsConnected(false);
      setCurrentStatus((prev) => (prev === "running" ? "disconnected" : prev));
      const delay = Math.min(1000 * 2 ** reconnectAttemptRef.current, 30000);
      setTimeout(connectWebSocket, delay);
      reconnectAttemptRef.current += 1;
    };

    ws.onerror = () => {
      setIsConnected(false);
    };

    wsRef.current = ws;
  }, [onActiveTaskChange, onTasksChange]);

  useEffect(() => {
    connectWebSocket();
    return () => wsRef.current?.close();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    transcriptEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [plan, stepResults, finalAnswer, pendingConfirmation, errorMessage]);

  // ─── Actions ───────────────────────────────────────────────────

  // ─── BUGFIX ──────────────────────────────────────────────────────
  // The previous version read `task` from component state inside a
  // useCallback closure, then quick-actions called `setTask(prompt)`
  // followed by `setTimeout(() => submitTask(), 300)`. Because state
  // updates are async and `submitTask` was memoized on `[task]`, the
  // `submitTask` reference captured by the *button's own* onClick
  // handler was the one built with the OLD `task` value -- so the
  // 300ms timer fired a submit with an empty message and users saw
  // "Please type a message" after clicking a quick action.
  // Accepting an explicit override avoids depending on that timing
  // entirely.
  const submitTask = useCallback(
    (overrideMessage?: string) => {
      const trimmedMessage = (overrideMessage ?? task).trim();
      if (!trimmedMessage) return;
      if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;

      const threadId = `thread-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
      threadIdRef.current = threadId;
      localStorage.setItem(THREAD_ID_KEY, threadId);

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
    [task]
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

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === "Enter" && !e.shiftKey && !loading && !pendingConfirmation) {
        e.preventDefault();
        submitTask();
      }
    },
    [loading, pendingConfirmation, submitTask]
  );

  const copyAnswer = useCallback(() => {
    if (!finalAnswer) return;
    navigator.clipboard.writeText(finalAnswer).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });
  }, [finalAnswer]);

  const reset = useCallback(() => {
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
    threadIdRef.current = null;
    onActiveTaskChange?.(null);
  }, [onActiveTaskChange]);

  useImperativeHandle(ref, () => ({ reset }), [reset]);

  // ─── Render helpers ──────────────────────────────────────────────

  const completedCount = Object.keys(stepResults).length;
  const totalSteps = plan?.length ?? 0;

  const composer = (
    <div className="relative">
      <div className="flex items-end gap-2 rounded-2xl border border-synthai-border bg-synthai-surface-light p-2.5 pl-4 shadow-[0_0_0_1px_rgba(99,102,241,0)] transition-shadow focus-within:border-transparent focus-within:shadow-[0_0_0_1.5px_theme(colors.brand.500)]">
        <button
          type="button"
          title="Attach a file"
          className="mb-1 shrink-0 rounded-lg p-1.5 text-text-muted transition-colors hover:bg-synthai-surface-hover hover:text-text-secondary"
        >
          <Paperclip className="h-4 w-4" />
        </button>
        <textarea
          rows={1}
          value={task}
          onChange={(e) => setTask(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={loading || !!pendingConfirmation}
          placeholder="Assign a task or type / for more"
          className="max-h-40 flex-1 resize-none bg-transparent py-2 text-[15px] text-text-primary placeholder-text-muted outline-none disabled:opacity-60"
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
      {!isConnected && (
        <p className="mt-2 text-center text-xs text-text-muted">Reconnecting…</p>
      )}
    </div>
  );

  // ─── Empty state ───────────────────────────────────────────────

  if (!hasStarted) {
    return (
      <div className="mx-auto flex w-full max-w-2xl flex-1 flex-col items-center justify-center px-6">
        <h1 className="font-serif text-[2.75rem] leading-tight text-text-primary">
          What can I do for you?
        </h1>
        <p className="mb-8 mt-2 text-sm text-text-secondary">
          Give synthAI a goal — it plans, runs tools, and checks its own work.
        </p>

        <div className="w-full">{composer}</div>

        <div className="mt-4 flex flex-wrap justify-center gap-2">
          {QUICK_ACTIONS.map((qa) => (
            <button
              key={qa.label}
              onClick={() => submitTask(qa.prompt)}
              className="flex items-center gap-2 rounded-lg border border-synthai-border bg-synthai-surface px-3.5 py-2 text-sm text-text-secondary transition-colors hover:border-brand-500/30 hover:bg-synthai-surface-hover hover:text-text-primary"
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
    <div className="mx-auto flex w-full max-w-3xl flex-1 flex-col px-6 pb-6">
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
          <div className="rounded-xl border border-synthai-border bg-synthai-surface/60 p-4">
            <div className="mb-3 flex items-center justify-between">
              <p className="text-xs font-semibold uppercase tracking-wide text-text-muted">Plan</p>
              <span className="text-xs text-text-muted">
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
                      <Circle className="mt-0.5 h-4 w-4 shrink-0 text-text-muted" />
                    )}
                    <div className="min-w-0 flex-1">
                      <p className={result ? "text-text-primary" : "text-text-secondary"}>
                        {step.description}
                        {step.tool_name && (
                          <span className="ml-2 rounded bg-synthai-surface-hover px-1.5 py-0.5 font-mono text-[11px] text-text-muted">
                            {step.tool_name}
                          </span>
                        )}
                      </p>
                      {result && (
                        <details className="mt-1 group">
                          <summary className="flex cursor-pointer list-none items-center gap-1 text-xs text-text-muted hover:text-text-secondary">
                            <ChevronDown className="h-3 w-3 transition-transform group-open:rotate-180" />
                            Output
                          </summary>
                          <p className="mt-1 whitespace-pre-wrap rounded-lg bg-synthai-surface-light p-2.5 text-xs text-text-secondary">
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
            <span className="text-text-muted">
              Verification: {verification.status || "unknown"}
              {typeof verification.score === "number" && ` · ${verification.score}/100`}
            </span>
          </div>
        )}

        {/* Confirmation banner */}
        {pendingConfirmation && (
          <div className="rounded-xl border border-amber-500/25 bg-amber-500/10 p-4">
            <p className="text-sm text-text-primary">
              synthAI wants to run{" "}
              <span className="rounded bg-amber-500/15 px-1.5 py-0.5 font-mono text-xs font-semibold text-amber-300">
                {pendingConfirmation.tool_name}
              </span>
            </p>
            <p className="mt-1 text-xs text-text-secondary">{pendingConfirmation.step_description}</p>
            <div className="mt-3 flex gap-2">
              <button
                onClick={confirmTool}
                className="flex items-center gap-1.5 rounded-lg bg-emerald-600 px-3 py-1.5 text-sm font-medium text-white transition-colors hover:bg-emerald-700"
              >
                <Check className="h-3.5 w-3.5" /> Confirm
              </button>
              <button
                onClick={rejectTool}
                className="flex items-center gap-1.5 rounded-lg border border-synthai-border px-3 py-1.5 text-sm font-medium text-text-secondary transition-colors hover:bg-synthai-surface-hover"
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
          <div className="rounded-xl border border-brand-500/25 bg-brand-500/[0.06] p-4">
            <div className="mb-2 flex items-center justify-between">
              <span className="flex items-center gap-1.5 text-xs font-semibold text-brand-300">
                <Sparkles className="h-3.5 w-3.5" /> Answer
              </span>
              <button
                onClick={copyAnswer}
                className="flex items-center gap-1 text-xs text-text-muted transition-colors hover:text-text-secondary"
              >
                <Copy className="h-3 w-3" /> {copied ? "Copied" : "Copy"}
              </button>
            </div>
            <p className="whitespace-pre-wrap leading-relaxed text-text-primary">{finalAnswer}</p>
            {typeof costMetrics?.total_cost_usd === "number" && (
              <p className="mt-2 text-xs text-text-muted">
                Cost: ${costMetrics.total_cost_usd.toFixed(6)}
              </p>
            )}
          </div>
        )}

        {loading && !pendingConfirmation && (
          <div className="flex items-center gap-2 text-xs text-text-muted">
            <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 ${statusPillClasses(currentStatus)}`}>
              <Loader2 className="h-3 w-3 animate-spin" />
              {currentStatus === "connecting" ? "Starting…" : "Working…"}
            </span>
          </div>
        )}

        <div ref={transcriptEndRef} />
      </div>

      {/* Sticky composer once a thread has started */}
      <div className="sticky bottom-0 bg-synthai-background pb-2 pt-4">{composer}</div>
    </div>
  );
});

export default ChatInterface;