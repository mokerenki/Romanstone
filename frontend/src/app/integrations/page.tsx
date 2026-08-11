"use client";

import Sidebar from "@/components/Sidebar";
import IntegrationPanel from "@/components/integrationpanel";

export default function IntegrationsPage() {
  return (
    <div className="flex h-screen bg-synthai-background">
      <Sidebar />

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center justify-between border-b border-synthai-border px-6 py-3">
          <span className="text-sm font-medium text-text-secondary">Plugins & Integrations</span>
          <div className="flex items-center gap-3 text-xs">
            <span className="rounded-full bg-synthai-surface-light px-3 py-1 text-text-secondary">
              test beta
            </span>
          </div>
        </header>

        <IntegrationPanel />
      </div>
    </div>
  );
}
