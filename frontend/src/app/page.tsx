"use client";

import { useState, useCallback } from "react";

interface PlanStep {
  step_id: string;
  description: string;
  status: string;
  result?: string;
}

interface TaskResult {
  status: string;
  plan?: PlanStep[];
  final_answer?: string;
  cost_metrics?: { total_cost_usd: number };
}

export default function Home() {
  const [task, setTask] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<TaskResult | null>(null);
  const [history, setHistory] = useState<string[]>([]);

  const submitTask = useCallback(async () => {
    if (!task.trim()) return;
    setLoading(true);
    setResult(null);
    try {
      const res = await fetch("/api/v1/tasks", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: task, user_id: "dashboard" }),
      });
      if (!res.ok) {
        const errorText = await res.text();
        throw new Error(`Server error (${res.status}): ${errorText.substring(0, 100)}`);
      }
      const data = await res.json();
      setResult(data);
      setHistory((prev) => [...prev, task]);
    } catch (err) {
      console.error("Task submission failed:", err);
      setResult({ status: "error", final_answer: String(err) });
    } finally {
      setLoading(false);
    }
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
        />
        <button
          className="px-6 py-3 bg-blue-600 hover:bg-blue-700 rounded-lg font-semibold disabled:opacity-50"
          onClick={submitTask}
          disabled={loading || !task.trim()}
        >
          {loading ? "Running..." : "Run Agent"}
        </button>
      </div>

      {result && (
        <div className="mt-8 space-y-6">
          <div className="flex items-center gap-3">
            <span className="text-sm font-medium text-gray-400">Status</span>
            <span
              className={`px-3 py-1 rounded-full text-sm font-semibold ${
                result.status === "completed"
                  ? "bg-green-900 text-green-300"
                  : result.status === "failed"
                  ? "bg-red-900 text-red-300"
                  : "bg-yellow-900 text-yellow-300"
              }`}
            >
              {result.status}
            </span>
          </div>

          {result.final_answer && (
            <div className="bg-gray-800 rounded-xl p-5 border border-gray-700">
              <h3 className="text-lg font-semibold mb-2 text-white">Answer</h3>
              <p className="text-gray-200 whitespace-pre-wrap">{result.final_answer}</p>
            </div>
          )}

          {result.cost_metrics && (
            <div className="flex items-center gap-2 text-sm text-gray-500">
              <span>Cost:</span>
              <span className="bg-gray-800 px-2 py-0.5 rounded-full text-gray-300">
                ${result.cost_metrics.total_cost_usd.toFixed(6)}
              </span>
            </div>
          )}
        </div>
      )}
    </main>
  );
}