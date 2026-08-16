"use client";

import { useCallback, useEffect, useState } from "react";
import Nango from "@nangohq/frontend";
import {
  Calendar,
  Check,
  Loader2,
  MessageSquare,
  RefreshCw,
  Trash2,
  Video,
  Building2,
  Receipt,
  Database,
  X,
  ExternalLink,
  Plug,
  Search,
} from "lucide-react";

type IntegrationStatus = "connected" | "disconnected" | "connecting" | "error";

interface CatalogEntry {
  id: string;
  name: string;
  description: string;
  category: string;
  capabilities: string[];
  auth_type: string;
  provider_key: string;
  auth_status_source: "nango" | "manual" | "unsupported";
  can_connect: boolean;
  has_n8n_mcp_workflow: boolean;
  status: IntegrationStatus;
  connected_at?: string | null;
  icon?: string;
}

interface ConnectInfo {
  auth_type: "oauth" | "api_key" | "manual" | "nango";
  oauth_url?: string;
  message?: string;
  env_var?: string;
  session_token?: string;
  host?: string;
  connect_url?: string;
  provider_config_key?: string;
}

const ICON_MAP: Record<string, React.ReactNode> = {
  slack: <MessageSquare className="h-6 w-6" />,
  calendar: <Calendar className="h-6 w-6" />,
  video: <Video className="h-6 w-6" />,
  notion: <Database className="h-6 w-6" />,
  salesforce: <Building2 className="h-6 w-6" />,
  sage: <Receipt className="h-6 w-6" />,
  whatsapp: <MessageSquare className="h-6 w-6" />,
};

const CATEGORY_LABELS: Record<string, string> = {
  communication: "Communication",
  productivity: "Productivity",
  crm: "CRM",
  finance: "Finance",
};

function StatusBadge({ status }: { status: IntegrationStatus }) {
  const styles: Record<IntegrationStatus, string> = {
    connected: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
    disconnected: "bg-synthai-surface-light text-text-muted border-synthai-border",
    connecting: "bg-brand-500/15 text-brand-300 border-brand-500/30",
    error: "bg-red-500/15 text-red-400 border-red-500/30",
  };
  const labels: Record<IntegrationStatus, string> = {
    connected: "Connected",
    disconnected: "Not connected",
    connecting: "Connecting…",
    error: "Error",
  };
  return (
    <span className={`rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${styles[status]}`}>
      {labels[status]}
    </span>
  );
}

function ConnectModal({
  entry,
  onClose,
  onConnected,
}: {
  entry: CatalogEntry;
  onClose: () => void;
  onConnected: () => void;
}) {
  const [loading, setLoading] = useState(true);
  const [connectInfo, setConnectInfo] = useState<ConnectInfo | null>(null);
  const [apiKey, setApiKey] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch(`/api/integrations/${entry.id}/connect`)
      .then((r) => r.json())
      .then(setConnectInfo)
      .catch(() => setError("Failed to load connection options"))
      .finally(() => setLoading(false));
  }, [entry.id]);

  const handleConnect = async () => {
    setSubmitting(true);
    setError(null);
    try {
      if (connectInfo?.auth_type === "oauth" && connectInfo.oauth_url) {
        window.location.href = connectInfo.oauth_url;
        return;
      }

      if (connectInfo?.auth_type === "nango") {
        // Connect sessions expire quickly. Fetch one only when the user is
        // ready to authorize, instead of reusing the session fetched when the
        // modal opened. This also keeps self-hosted Connect on our Nango API.
        const sessionResponse = await fetch(`/api/integrations/${entry.id}/connect`);
        const session = await sessionResponse.json() as ConnectInfo;
        if (!sessionResponse.ok || !session.session_token || !session.host || !session.connect_url) {
          throw new Error((session as { detail?: string }).detail || "Unable to start authorization");
        }
        const nango = new Nango({ host: session.host });
        nango.openConnectUI({
          sessionToken: session.session_token,
          baseURL: session.connect_url,
          apiURL: session.host,
          onEvent: async (event) => {
            if (event.type !== "connect") return;
            const payload = event.payload as { connectionId: string; providerConfigKey: string };
            try {
              const res = await fetch(`/api/integrations/${entry.id}/connect`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                  connection_id: payload.connectionId,
                  provider_config_key: payload.providerConfigKey,
                }),
              });
              const data = await res.json();
              if (!res.ok) throw new Error(data.detail || "Connection failed");
              onConnected();
              onClose();
            } catch (connectError) {
              setError(connectError instanceof Error ? connectError.message : "Connection failed");
            }
          },
        });
        return;
      }

      const res = await fetch(`/api/integrations/${entry.id}/connect`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ api_key: apiKey }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Connection failed");
      if (data.oauth_url) {
        window.location.href = data.oauth_url;
        return;
      }
      onConnected();
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Connection failed");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm">
      <div className="w-full max-w-md rounded-xl border border-synthai-border bg-synthai-surface p-6 shadow-2xl">
        <div className="mb-4 flex items-start justify-between">
          <div>
            <h3 className="text-lg font-semibold text-text-primary">Connect {entry.name}</h3>
            <p className="mt-1 text-sm text-text-secondary">{entry.description}</p>
          </div>
          <button
            onClick={onClose}
            className="rounded-lg p-1 text-text-muted transition-colors hover:bg-synthai-surface-hover hover:text-text-secondary"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="h-6 w-6 animate-spin text-brand-400" />
          </div>
        ) : (
          <>
            <ul className="mb-4 space-y-1">
              {entry.capabilities.map((cap) => (
                <li key={cap} className="flex items-center gap-2 text-xs text-text-secondary">
                  <Check className="h-3 w-3 shrink-0 text-brand-400" />
                  {cap}
                </li>
              ))}
            </ul>

            {connectInfo?.auth_type === "nango" ? (
              <p className="mb-4 text-sm text-text-secondary">
                Continue to {entry.name} to authorize SynthAI. Your credentials stay with the secure connection service.
              </p>
            ) : connectInfo?.auth_type === "oauth" && connectInfo.oauth_url ? (
              <p className="mb-4 text-sm text-text-secondary">
                Sign in with {entry.name} to grant synthAI access to your workspace.
              </p>
            ) : (
              <div className="mb-4">
                <label className="mb-1.5 block text-xs font-medium text-text-secondary">
                  {connectInfo?.env_var ? `${connectInfo.env_var} or API token` : "API key / token"}
                </label>
                <input
                  type="password"
                  value={apiKey}
                  onChange={(e) => setApiKey(e.target.value)}
                  placeholder="Paste your API key or bot token"
                  className="w-full rounded-lg border border-synthai-border bg-synthai-surface-light px-3 py-2 text-sm text-text-primary placeholder:text-text-muted focus:border-brand-500/50 focus:outline-none focus:ring-1 focus:ring-brand-500/30"
                />
                {connectInfo?.message && (
                  <p className="mt-2 text-xs text-text-muted">{connectInfo.message}</p>
                )}
              </div>
            )}

            {error && <p className="mb-3 text-sm text-red-400">{error}</p>}

            <div className="flex gap-2">
              <button
                onClick={onClose}
                className="flex-1 rounded-lg border border-synthai-border px-4 py-2 text-sm font-medium text-text-secondary transition-colors hover:bg-synthai-surface-hover"
              >
                Cancel
              </button>
              <button
                onClick={handleConnect}
                disabled={submitting || (connectInfo?.auth_type !== "oauth" && connectInfo?.auth_type !== "nango" && !apiKey && !connectInfo?.oauth_url)}
                className="btn-gradient flex flex-1 items-center justify-center gap-2 rounded-lg px-4 py-2 text-sm disabled:opacity-50"
              >
                {submitting ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : connectInfo?.oauth_url || connectInfo?.auth_type === "nango" ? (
                  <>
                    <ExternalLink className="h-4 w-4" />
                    Authorize
                  </>
                ) : (
                  <>
                    <Plug className="h-4 w-4" />
                    Connect
                  </>
                )}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

export default function IntegrationPanel() {
  const [catalog, setCatalog] = useState<CatalogEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState<"all" | "connected" | "available">("all");
  const [connectTarget, setConnectTarget] = useState<CatalogEntry | null>(null);
  const [actionId, setActionId] = useState<string | null>(null);

  const fetchCatalog = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch("/api/integrations");
      if (!res.ok) throw new Error("Failed to fetch");
      const data = await res.json();
      setCatalog(data.integrations || []);
    } catch (e) {
      console.error("Failed to fetch integrations:", e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchCatalog();
  }, [fetchCatalog]);

  const syncIntegration = async (id: string) => {
    setActionId(id);
    try {
      await fetch(`/api/integrations/${id}/sync`, { method: "POST" });
      await fetchCatalog();
    } catch (e) {
      console.error("Sync failed:", e);
    } finally {
      setActionId(null);
    }
  };

  const disconnectIntegration = async (id: string) => {
    setActionId(id);
    try {
      await fetch(`/api/integrations/${id}/disconnect`, { method: "POST" });
      await fetchCatalog();
    } catch (e) {
      console.error("Disconnect failed:", e);
    } finally {
      setActionId(null);
    }
  };

  const connectedCount = catalog.filter((c) => c.status === "connected").length;

  const filtered = catalog.filter((entry) => {
    const q = search.toLowerCase();
    const matchesSearch =
      !q ||
      entry.name.toLowerCase().includes(q) ||
      entry.description.toLowerCase().includes(q) ||
      entry.category.toLowerCase().includes(q);
    const matchesFilter =
      filter === "all" ||
      (filter === "connected" && entry.status === "connected") ||
      (filter === "available" && entry.status !== "connected");
    return matchesSearch && matchesFilter;
  });

  const grouped = filtered.reduce<Record<string, CatalogEntry[]>>((acc, entry) => {
    const cat = entry.category || "other";
    if (!acc[cat]) acc[cat] = [];
    acc[cat].push(entry);
    return acc;
  }, {});

  if (loading) {
    return (
      <div className="flex flex-1 items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-brand-400" />
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="mx-auto max-w-5xl px-6 py-8">
        {/* Header */}
        <div className="mb-8">
          <h1 className="text-3xl font-bold tracking-tight text-text-primary">Plugins</h1>
          <p className="mt-2 max-w-2xl text-text-secondary">
            Connect the tools your agent can reference — Slack messages, Google Calendar meetings,
            Notion docs, Salesforce pipeline, Sage accounting, and more.
          </p>
          <div className="mt-4 flex items-center gap-4 text-sm">
            <span className="rounded-full bg-brand-500/15 px-3 py-1 font-medium text-brand-300">
              {connectedCount} connected
            </span>
            <span className="text-text-muted">{catalog.length} available</span>
          </div>
        </div>

        {/* Search + filter */}
        <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-center">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-text-muted" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search integrations…"
              className="w-full rounded-lg border border-synthai-border bg-synthai-surface-light py-2 pl-10 pr-4 text-sm text-text-primary placeholder:text-text-muted focus:border-brand-500/50 focus:outline-none"
            />
          </div>
          <div className="flex rounded-lg border border-synthai-border bg-synthai-surface-light p-0.5">
            {(["all", "connected", "available"] as const).map((f) => (
              <button
                key={f}
                onClick={() => setFilter(f)}
                className={`rounded-md px-3 py-1.5 text-xs font-medium capitalize transition-colors ${
                  filter === f
                    ? "bg-brand-500/20 text-brand-300"
                    : "text-text-muted hover:text-text-secondary"
                }`}
              >
                {f}
              </button>
            ))}
          </div>
        </div>

        {/* Integration grid by category */}
        {Object.keys(grouped).length === 0 ? (
          <p className="py-12 text-center text-text-muted">No integrations match your search.</p>
        ) : (
          Object.entries(grouped).map(([category, entries]) => (
            <section key={category} className="mb-8">
              <h2 className="mb-3 text-xs font-semibold uppercase tracking-wider text-text-muted">
                {CATEGORY_LABELS[category] || category}
              </h2>
              <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                {entries.map((entry) => (
                  <div
                    key={entry.id}
                    className="group flex flex-col rounded-xl border border-synthai-border bg-synthai-surface-light/50 p-5 transition-colors hover:border-brand-500/30 hover:bg-synthai-surface-light"
                  >
                    <div className="mb-3 flex items-start justify-between gap-3">
                      <div className="flex items-center gap-3">
                        <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-brand-500/15 text-brand-400">
                          {ICON_MAP[entry.icon || entry.id] || <Plug className="h-6 w-6" />}
                        </div>
                        <div>
                          <h3 className="font-semibold text-text-primary">{entry.name}</h3>
                          <StatusBadge status={entry.status} />
                        </div>
                      </div>
                    </div>

                    <p className="mb-3 flex-1 text-sm leading-relaxed text-text-secondary">
                      {entry.description}
                    </p>

                    <div className="mb-4 flex flex-wrap gap-1.5">
                      {entry.capabilities.slice(0, 3).map((cap) => (
                        <span
                          key={cap}
                          className="rounded-md bg-synthai-surface px-2 py-0.5 text-[10px] text-text-muted"
                        >
                          {cap}
                        </span>
                      ))}
                      {entry.capabilities.length > 3 && (
                        <span className="rounded-md bg-synthai-surface px-2 py-0.5 text-[10px] text-text-muted">
                          +{entry.capabilities.length - 3} more
                        </span>
                      )}
                    </div>

                    <div className="flex gap-2">
                      {entry.status === "connected" ? (
                        <>
                          <button
                            onClick={() => syncIntegration(entry.id)}
                            disabled={actionId === entry.id}
                            className="flex flex-1 items-center justify-center gap-1.5 rounded-lg border border-synthai-border px-3 py-2 text-xs font-medium text-text-secondary transition-colors hover:bg-synthai-surface-hover disabled:opacity-50"
                          >
                            {actionId === entry.id ? (
                              <Loader2 className="h-3.5 w-3.5 animate-spin" />
                            ) : (
                              <RefreshCw className="h-3.5 w-3.5" />
                            )}
                            Sync tools
                          </button>
                          <button
                            onClick={() => disconnectIntegration(entry.id)}
                            disabled={actionId === entry.id}
                            className="flex items-center justify-center gap-1.5 rounded-lg border border-red-500/30 px-3 py-2 text-xs font-medium text-red-400 transition-colors hover:bg-red-500/10 disabled:opacity-50"
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                            Disconnect
                          </button>
                        </>
                      ) : entry.can_connect ? (
                        <button
                          onClick={() => setConnectTarget(entry)}
                          className="btn-gradient flex flex-1 items-center justify-center gap-1.5 rounded-lg px-3 py-2 text-xs font-medium"
                        >
                          <Plug className="h-3.5 w-3.5" />
                          Connect
                        </button>
                      ) : (
                        <button
                          disabled
                          title={entry.auth_status_source === "unsupported" ? "This provider is not supported yet." : "A matching n8n MCP workflow is required before this plugin can connect."}
                          className="flex flex-1 items-center justify-center gap-1.5 rounded-lg border border-synthai-border bg-synthai-surface px-3 py-2 text-xs font-medium text-text-muted opacity-70"
                        >
                          <Plug className="h-3.5 w-3.5" />
                          Coming soon
                        </button>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </section>
          ))
        )}
      </div>

      {connectTarget && (
        <ConnectModal
          entry={connectTarget}
          onClose={() => setConnectTarget(null)}
          onConnected={fetchCatalog}
        />
      )}
    </div>
  );
}
