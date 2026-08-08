"use client";

import { useState, useCallback, useEffect, useRef } from "react";

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

const THREAD_ID_KEY = "aether_thread_id";

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
  const wsRef = useRef<WebSocket | null>(null);
  const eventLogRef = useRef<HTMLDivElement>(null);
  const reconnectAttemptRef = useRef(0);

  const connectWebSocket = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const ws = new WebSocket(`${protocol}//${window.location.host}/ws`);

    ws.onopen = () => {
      console.log("WebSocket connected");
      reconnectAttemptRef.current = 0;

      const savedThreadId = localStorage.getItem(THREAD_ID_KEY);
      if (savedThreadId && currentStatus !== "idle") {
        ws.send(
          JSON.stringify({
            action: "resume_task",
            thread_id: savedThreadId,
          })
        );
      }
    };

    ws.onmessage = (event) => {
      const data: StreamedEvent = JSON.parse(event.data);
      console.log("Received event:", data);
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
      if (loading) {
        setCurrentStatus("disconnected");
      }
      const delay = Math.min(1000 * 2 ** reconnectAttemptRef.current, 30000);
      setTimeout(connectWebSocket, delay);
      reconnectAttemptRef.current += 1;
    };

    ws.onerror = (event) => {
      console.error("WebSocket error event:", event);
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

  const submitTask = useCallback(() => {
    if (!task.trim() || !wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
      console.warn("WebSocket not open or task is empty.");
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

    wsRef.current.send(
      JSON.stringify({
        action: "run_task",
        message: task,
        user_id: "dashboard",
        tenant_id: "default",
        thread_id: threadId,
      })
    );
  }, [task]);

  const confirmTool = useCallback(() => {
    if (!pendingConfirmation || !wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;
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
    if (!pendingConfirmation || !wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;
    wsRef.current.send(
      JSON.stringify({
        action: "reject_tool",
        task_id: pendingConfirmation.task_id,
        thread_id: pendingConfirmation.thread_id,
        step_index: pendingConfirmation.step_index,
        message: task,
        user_id: "dashboard",
        tenant_id: "default",
      })
    );
    setPendingConfirmation(null);
    setLoading(true);
  }, [pendingConfirmation, task]);

  return (
    <main className="max-w-4xl mx-auto p-8">
      <h1 className="text-4xl font-bold mb-2">Romanstone</h1>
      <p className="text-gray-400 mb-8">Autonomous Agent Platform · Phase 0</p>

      <div className="flex gap-4 mb-8">
        <input
          className="flex-1 p-3 rounded-lg bg-gray-800 border border-gray-700 focus:outline-none focus:ring-2 focus:ring-blue-500"
          placeholder="Enter a task (e.g., 'Who is the president of South Africa?')"
          value={task}
          onChange={(e) => setTask(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && submitTask()}
          disabled={loading || !!pendingConfirmation}
        />
        <button
          className="px-6 py-3 bg-blue-600 hover:bg-blue-700 rounded-lg font-semibold disabled:opacity-50"
          onClick={submitTask}
          disabled={loading || !task.trim() || !!pendingConfirmation || wsRef.current?.readyState !== WebSocket.OPEN}
        >
          {loading ? "Running..." : pendingConfirmation ? "Awaiting confirmation..." : "Run Agent"}
        </button>
      </div>

      {pendingConfirmation && (
        <div className="bg-yellow-900/50 border border-yellow-700 rounded-xl p-5 mb-6">
          <h3 className="text-lg font-semibold text-yellow-300 mb-2">Confirmation Required</h3>
          <p className="text-gray-200 mb-1">
            The agent wants to run <span className="font-mono font-bold">{pendingConfirmation.tool_name}</span>
          </p>
          <p className="text-gray-400 text-sm mb-1">{pendingConfirmation.step_description}</p>
          {Object.keys(pendingConfirmation.tool_args).length > 0 && (
            <pre className="text-xs bg-gray-900 p-2 rounded mt-2 mb-3 text-gray-300">
              {JSON.stringify(pendingConfirmation.tool_args, null, 2)}
            </pre>
          )}
          <div className="flex gap-3 mt-4">
            <button
              onClick={confirmTool}
              className="px-4 py-2 bg-green-600 hover:bg-green-700 rounded-lg font-semibold text-sm"
            >
              Confirm
            </button>
            <button
              onClick={rejectTool}
              className="px-4 py-2 bg-red-600 hover:bg-red-700 rounded-lg font-semibold text-sm"
            >
              Reject
            </button>
          </div>
        </div>
      )}

      {currentStatus !== "idle" && (
        <div className="mt-8 space-y-6">
          <div className="flex items-center gap-3">
            <span className="text-sm font-medium text-gray-400">Status</span>
            <span
              className={`px-3 py-1 rounded-full text-sm font-semibold ${
                currentStatus === "completed"
                  ? "bg-green-900 text-green-300"
                  : currentStatus === "failed"
                  ? "bg-red-900 text-red-300"
                  : currentStatus === "running"
                  ? "bg-blue-900 text-blue-300"
                  : "bg-yellow-900 text-yellow-300"
              }`}
            >
              {currentStatus}
            </span>
          </div>

          <div className="bg-gray-800 rounded-xl p-5 border border-gray-700 max-h-96 overflow-y-auto" ref={eventLogRef}>
            <h3 className="text-lg font-semibold mb-2 text-white">Event Log</h3>
              {events.map((event, index) => (
                <div key={index} className="text-gray-200 text-sm mb-1">
                  <span className="text-gray-500">[{new Date(event.timestamp || Date.now()).toLocaleTimeString()}]</span>
                  <span className="font-semibold ml-2">{event.type}:</span>
                  {event.type === "planner_output" && (
                    <pre className="whitespace-pre-wrap text-xs bg-gray-900 p-2 rounded mt-1">
                      {JSON.stringify(event.content, null, 2)}
                    </pre>
                  )}
                  {event.type === "executor_output" && (
                    <div className="ml-4">
                      <p><strong>Step:</strong> {event.content.step}</p>
                      {event.content.tool && <p><strong>Tool:</strong> {event.content.tool}</p>}
                      <p><strong>Output:</strong> <span className="whitespace-pre-wrap">{event.content.output}</span></p>
                    </div>
                  )}
                  {event.type === "verifier_output" && (
                    <p className="ml-4 whitespace-pre-wrap">{JSON.stringify(event.content, null, 2)}</p>
                  )}
                  {event.type === "task_error" && (
                    <pre className="text-red-400 whitespace-pre-wrap text-xs bg-gray-900 p-2 rounded mt-1">
                      {event.error}\n{event.trace?.join("\n")}
                    </pre>
                  )}
                  {event.type === "error" && (
                    <pre className="text-red-400 whitespace-pre-wrap text-xs bg-gray-900 p-2 rounded mt-1">
                      {event.message || event.error || "Unknown error"}
                    </pre>
                  )}
                  {(event.type === "task_start" || event.type === "task_complete") && (
                    <span className="ml-2 whitespace-pre-wrap">{event.message || event.status}</span>
                  )}
                  {event.type === "raw_graph_event" && (
                    <pre className="whitespace-pre-wrap text-xs bg-gray-900 p-2 rounded mt-1">
                      {JSON.stringify(event.content, null, 2)}
                    </pre>
                  )}
                </div>
              ))}
          </div>

          {finalAnswer && (
            <div className="bg-gray-800 rounded-xl p-5 border border-gray-700">
              <h3 className="text-lg font-semibold mb-2 text-white">Final Answer</h3>
              <p className="text-gray-200 whitespace-pre-wrap">{finalAnswer}</p>
            </div>
          )}

          {costMetrics && (
            <div className="flex items-center gap-2 text-sm text-gray-500">
              <span>Cost:</span>
              <span className="bg-gray-800 px-2 py-0.5 rounded-full text-gray-300">
                ${costMetrics.total_cost_usd.toFixed(6)}
              </span>
            </div>
          )}
        </div>
      )}
    </main>
  );
}
