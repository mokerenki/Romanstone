// frontend/src/app/history/page.tsx

"use client";

import { useState } from 'react';
import { HistoryList } from '@/components/HistoryList';
import { TaskReplay } from '@/components/TaskReplay';

export default function HistoryPage() {
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  const [replayTaskId, setReplayTaskId] = useState<string | null>(null);

  return (
    <div className="max-w-7xl mx-auto p-6">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-text-primary">Task History</h1>
        <p className="text-sm text-text-muted">
          Browse and replay past task executions
        </p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* History List */}
        <div className="lg:col-span-2">
          <HistoryList
            onSelectTask={setSelectedTaskId}
            onReplayTask={setReplayTaskId}
            selectedTaskId={selectedTaskId}
          />
        </div>

        {/* Task Details / Stats */}
        <div className="lg:col-span-1">
          {selectedTaskId ? (
            <div className="bg-synthai-surface rounded-xl border border-synthai-border p-4">
              <h3 className="text-sm font-medium text-text-secondary mb-3">Task Details</h3>
              <p className="text-xs text-text-muted">Loading task details...</p>
              {/* Add detailed view here */}
            </div>
          ) : (
            <div className="bg-synthai-surface rounded-xl border border-synthai-border p-4">
              <h3 className="text-sm font-medium text-text-secondary mb-3">Stats</h3>
              <p className="text-xs text-text-muted">Select a task to view details</p>
              {/* Add stats here */}
            </div>
          )}
        </div>
      </div>

      {/* Replay Modal */}
      {replayTaskId && (
        <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50 p-4">
          <div className="w-full max-w-4xl max-h-[90vh] overflow-y-auto">
            <TaskReplay
              threadId={replayTaskId}
              onClose={() => setReplayTaskId(null)}
            />
          </div>
        </div>
      )}
    </div>
  );
}