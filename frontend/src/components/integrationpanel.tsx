"use client";

import { useState, useEffect } from 'react';
import { Check, X, Loader2, RefreshCw, Settings, Trash2, Database } from 'lucide-react';

interface Integration {
  id: string;
  name: string;
  type: 'mcp' | 'custom';
  status: 'connected' | 'disconnected' | 'connecting' | 'error';
  last_sync?: string;
  config: Record<string, any>;
  description?: string;
}

export default function IntegrationPanel() {
  const [integrations, setIntegrations] = useState<Integration[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchIntegrations();
  }, []);

  const fetchIntegrations = async () => {
    setLoading(true);
    try {
      const response = await fetch('/api/integrations');
      if (!response.ok) throw new Error('Failed to fetch integrations');
      const data = await response.json();
      setIntegrations(data.integrations || []);
    } catch (error) {
      console.error('Failed to fetch integrations:', error);
    } finally {
      setLoading(false);
    }
  };

  const syncIntegration = async (id: string) => {
    // Trigger a sync (refresh MCP tools)
    try {
      const response = await fetch(`/api/integrations/${id}/sync`, { method: 'POST' });
      if (!response.ok) throw new Error('Sync failed');
      await fetchIntegrations();
    } catch (error) {
      console.error('Sync failed:', error);
    }
  };

  // ... rest of component (similar to previous version)
}