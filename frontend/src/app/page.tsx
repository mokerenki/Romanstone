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
  message?: string;
  timestamp: string;
  content?: any; // Can be plan, executor output, verifier output, etc.
  status?: string;
  final_answer?: string;
  plan?: PlanStep[];
  verification?: any;
  cost_metrics?: { total_cost_usd: number };
  error?: string;
  trace?: string[];
}

export default function Home() {
  const [task, setTask] = useState("");
  const [loading, setLoading] = useState(false);
  const [events, setEvents] = useState<StreamedEvent[]>([]);
  const [currentStatus, setCurrentStatus] = useState("idle");
  const [finalAnswer, setFinalAnswer] = useState<string | null>(null);
  const [costMetrics, setCostMetrics] = useState<{ total_cost_usd: number } | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const eventLogRef = useRef<HTMLDivElement>(null);

  const client_id = useRef(Math.random().toString(36).substring(7)).current;

  useEffect(() => {
    const connectWebSocket = () => {
      const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
      const ws = new WebSocket(`${protocol}//localhost:8000/api/ws/${client_id}`);

      ws.onopen = () => {
        console.log("WebSocket connected");
      };

      ws.onmessage = (event) => {
        const data: StreamedEvent = JSON.parse(event.data);
        console.log("Received event:", data);
        setEvents((prev) => [...prev, data]);

        if (data.type === "task_start") {
          setCurrentStatus("running");
          setFinalAnswer(null);
          setCostMetrics(null);
        } else if (data.type === "task_complete") {
          setCurrentStatus(data.status || "completed");
          setFinalAnswer(data.final_answer || null);
          setCostMetrics(data.cost_metrics || null);
          setLoading(false); // Task completed, stop loading
        } else if (data.type === "task_error") {
          setCurrentStatus("failed");
          setFinalAnswer(`Error: ${data.error}\n${data.trace?.join("\n") || ""}`);
          setLoading(false); // Task failed, stop loading
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
        // Attempt to reconnect after a delay
        setTimeout(connectWebSocket, 3000);
      };

      ws.onerror = (event) => {
        console.error("WebSocket error event:", event);
        setCurrentStatus("error");
        setLoading(false); // On error, stop loading
      };

      wsRef.current = ws;
    };

    connectWebSocket();

    return () => {
      wsRef.current?.close();
    };
  }, [client_id]);

  useEffect(() => {
    // Scroll to bottom of event log when new events arrive
    if (eventLogRef.current) {
      eventLogRef.current.scrollTop = eventLogRef.current.scrollHeight;
    }
  }, [events]);

  const submitTask = useCallback(() => {
    if (!task.trim() || !wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
      console.warn("WebSocket not open or task is empty.");
      return;
    }
    setLoading(true);
    setEvents([]); // Clear previous events
    setFinalAnswer(null);
    setCostMetrics(null);
    setCurrentStatus("connecting"); // Set status to connecting while waiting for task_start

    wsRef.current.send(JSON.stringify({
      action: "run_task",
      message: task,
      user_id: "dashboard",
      tenant_id: "default",
    }));
  }, [task]);

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
          disabled={loading}
        />
        <button
          className="px-6 py-3 bg-blue-600 hover:bg-blue-700 rounded-lg font-semibold disabled:opacity-50"
          onClick={submitTask}
          disabled={loading || !task.trim() || wsRef.current?.readyState !== WebSocket.OPEN}
        >
          {loading ? "Running..." : "Run Agent"}
        </button>
      </div>

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
                <span className="text-gray-500">[{new Date(event.timestamp).toLocaleTimeString()}]</span>
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