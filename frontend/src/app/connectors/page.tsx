// frontend/src/app/connectors/page.tsx

"use client";

import { useState, useEffect, useCallback } from 'react';
import { Search, RefreshCw, Grid3x3, List, Plug, Loader2 } from 'lucide-react';
import { ConnectorCard } from '@/components/ConnectorCard';
import { CONNECTORS, Connector } from '@/data/connectors';

export default function ConnectorsPage() {
  const [connectors, setConnectors] = useState<Connector[]>(CONNECTORS);
  const [searchTerm, setSearchTerm] = useState('');
  const [selectedCategory, setSelectedCategory] = useState<string>('all');
  const [viewMode, setViewMode] = useState<'grid' | 'list'>('grid');
  const [connecting, setConnecting] = useState<string | null>(null);
  const [connectedConnectors, setConnectedConnectors] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(true);

  // Get unique categories
  const categories = ['all', ...new Set(connectors.map(c => c.category))];
  const categoryLabels: Record<string, string> = {
    all: 'All',
    productivity: 'Productivity',
    marketing: 'Marketing',
    sales: 'Sales',
    development: 'Development',
    analytics: 'Analytics',
    social: 'Social',
    ai: 'AI',
  };

  // Load connected connectors from API
  const loadConnections = useCallback(async () => {
    try {
      const response = await fetch('/api/connectors/status');
      if (response.ok) {
        const data = await response.json();
        setConnectedConnectors(new Set(data.connected || []));
      }
    } catch (error) {
      console.error('Failed to load connections:', error);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadConnections();
  }, [loadConnections]);

  // Filter connectors
  const filteredConnectors = connectors.filter(connector => {
    const matchesSearch = connector.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
                          connector.description.toLowerCase().includes(searchTerm.toLowerCase());
    const matchesCategory = selectedCategory === 'all' || connector.category === selectedCategory;
    return matchesSearch && matchesCategory;
  });

  // Handle connect - OAuth flow
  const handleConnect = async (connectorId: string) => {
    setConnecting(connectorId);
    try {
      const connector = connectors.find(c => c.id === connectorId);
      
      if (connector?.authType === 'oauth2') {
        // Get OAuth URL from backend
        const response = await fetch(`/api/connectors/${connectorId}/auth-url`);
        const data = await response.json();
        
        if (data.url) {
          // Open OAuth popup
          const width = 600;
          const height = 700;
          const left = (window.screen.width - width) / 2;
          const top = (window.screen.height - height) / 2;
          
          const popup = window.open(
            data.url,
            'oauth',
            `width=${width},height=${height},left=${left},top=${top}`
          );
          
          // Listen for OAuth callback message
          const handleMessage = (event: MessageEvent) => {
            if (event.data?.type === 'oauth_success') {
              loadConnections();
              setConnecting(null);
              window.removeEventListener('message', handleMessage);
            }
          };
          window.addEventListener('message', handleMessage);
          
          // Check if popup was closed without completing
          const checkPopup = setInterval(() => {
            if (popup?.closed) {
              clearInterval(checkPopup);
              setConnecting(null);
              window.removeEventListener('message', handleMessage);
            }
          }, 500);
        }
      } else if (connector?.authType === 'api_key') {
        // Show API key modal
        const apiKey = prompt(`Enter API key for ${connector.name}:`);
        if (apiKey) {
          const response = await fetch(`/api/connectors/${connectorId}/connect`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ api_key: apiKey }),
          });
          if (response.ok) {
            await loadConnections();
          }
        }
      }
    } catch (error) {
      console.error('Connection failed:', error);
    } finally {
      setConnecting(null);
    }
  };

  // Handle disconnect
  const handleDisconnect = async (connectorId: string) => {
    const connector = connectors.find(c => c.id === connectorId);
    if (!confirm(`Disconnect ${connector?.name}?`)) return;
    
    try {
      const response = await fetch(`/api/connectors/${connectorId}/disconnect`, {
        method: 'POST',
      });
      if (response.ok) {
        await loadConnections();
      }
    } catch (error) {
      console.error('Disconnect failed:', error);
    }
  };

  // Handle configure
  const handleConfigure = (connectorId: string) => {
    // Open configuration modal
    console.log('Configure:', connectorId);
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="w-8 h-8 animate-spin text-blue-600" />
      </div>
    );
  }

  return (
    <div className="max-w-7xl mx-auto p-6">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Connectors</h1>
          <p className="text-sm text-gray-500 mt-1">
            Connect apps and APIs to share your context
          </p>
        </div>
        <button
          onClick={loadConnections}
          className="flex items-center gap-2 px-4 py-2 rounded-lg border border-gray-200 hover:bg-gray-50 transition-colors text-sm"
        >
          <RefreshCw className="w-4 h-4" />
          Refresh
        </button>
      </div>

      {/* Search & Filters */}
      <div className="flex flex-wrap items-center gap-3 mb-6">
        <div className="flex-1 min-w-[200px] relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
          <input
            type="text"
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            placeholder="Search connectors..."
            className="w-full bg-white rounded-lg pl-9 pr-4 py-2 text-sm border border-gray-200 focus:border-blue-500 outline-none transition-colors"
          />
        </div>
        <div className="flex items-center gap-2 overflow-x-auto pb-1">
          {categories.map((category) => (
            <button
              key={category}
              onClick={() => setSelectedCategory(category)}
              className={`px-3 py-1.5 text-sm rounded-lg whitespace-nowrap transition-colors ${
                selectedCategory === category
                  ? 'bg-blue-600 text-white'
                  : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
              }`}
            >
              {categoryLabels[category] || category}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-1 border-l border-gray-200 pl-3">
          <button
            onClick={() => setViewMode('grid')}
            className={`p-1.5 rounded transition-colors ${
              viewMode === 'grid' ? 'bg-gray-200 text-gray-800' : 'text-gray-400 hover:text-gray-600'
            }`}
          >
            <Grid3x3 className="w-4 h-4" />
          </button>
          <button
            onClick={() => setViewMode('list')}
            className={`p-1.5 rounded transition-colors ${
              viewMode === 'list' ? 'bg-gray-200 text-gray-800' : 'text-gray-400 hover:text-gray-600'
            }`}
          >
            <List className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Connectors Grid */}
      {filteredConnectors.length === 0 ? (
        <div className="text-center py-12">
          <Plug className="w-12 h-12 mx-auto text-gray-300 mb-3" />
          <p className="text-gray-500">No connectors found matching your filters</p>
        </div>
      ) : (
        <div className={`grid ${
          viewMode === 'grid' 
            ? 'grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4' 
            : 'grid-cols-1 gap-3'
        }`}>
          {filteredConnectors.map((connector) => (
            <ConnectorCard
              key={connector.id}
              connector={connector}
              onConnect={handleConnect}
              onDisconnect={handleDisconnect}
              onConfigure={handleConfigure}
              isConnected={connectedConnectors.has(connector.id)}
              isConnecting={connecting === connector.id}
            />
          ))}
        </div>
      )}

      {/* Stats */}
      <div className="mt-6 pt-4 border-t border-gray-200 flex items-center justify-between text-xs text-gray-400">
        <span>
          Showing {filteredConnectors.length} of {connectors.length} connectors
        </span>
        <span>
          {connectedConnectors.size} connected
        </span>
      </div>
    </div>
  );
}