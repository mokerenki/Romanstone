"use client";

import { useState, useEffect, useCallback } from "react";

interface TaskResult {
  status: string;
  plan?: Array<{ step_id: string; description: string; status: string; result?: string }>;
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
      const data = await res.json();
      setResult(data);
      setHistory((prev) => [...prev, task]);
    } catch (err) {
      setResult({ status: "error", final_answer: String(err) });
    } finally {
      setLoading(false);
    }
  }, [task]);

  return (
    <main className="max-w-4xl mx-auto p-8">
      <h1 className="text-4xl font-bold mb-2">Romanstone</h1>
      <p className="text-gray-400 mb-8">Autonomous Agent Platform ·</p>

      <div className="flex gap-4 mb-8">
        <input
          className="flex-1 p-3 rounded-lg bg-gray-800 border border-gray-700 focus:outline-none focus:ring-2 focus:ring-blue-500"
          placeholder="Enter a task (e.g., 'Search for recent AI regulations in South Africa')"
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
        <div className="bg-gray-800 rounded-lg p-6 mb-8">
          <h2 className="text-xl font-semibold mb-4">Result</h2>
          <div className="space-y-3">
            <p><span className="text-gray-400">Status:</span> {result.status}</p>
            {result.final_answer && (
              <p><span className="text-gray-400">Answer:</span> {result.final_answer}</p>
            )}
            {result.cost_metrics && (
              <p><span className="text-gray-400">Cost:</span> ${result.cost_metrics.total_cost_usd.toFixed(6)}</p>
            )}
          </div>
          {result.plan && (
            <div className="mt-4">
              <h3 className="font-semibold mb-2">Execution Plan</h3>
              {result.plan.map((step) => (
                <div key={step.step_id} className="text-sm py-1">
                  <span className={step.status === "completed" ? "text-green-400" : "text-yellow-400"}>
                    {step.status === "completed" ? "✓" : "○"}
                  </span>{" "}
                  {step.description}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </main>
  );
}