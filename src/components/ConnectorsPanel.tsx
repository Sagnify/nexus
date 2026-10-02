import React, { useState, useMemo, useEffect, useRef, useCallback } from 'react';
import {
  X,
  Search,
  AlertCircle,
  RefreshCw,
  Trash2,
  Shield,
  Blocks,
  ChevronLeft,
  ExternalLink,
  Loader2,
  Info,
} from 'lucide-react';
import { useConnectors } from '../context/ConnectorsContext';
import { ConnectorItem } from '../types/connectors';
import {
  GmailIcon,
  GoogleCalendarIcon,
  GoogleDriveIcon,
  GithubIcon,
  SpotifyIcon,
  SlackIcon,
  NotionIcon,
  LinearIcon,
  TodoistIcon,
  FilesystemIcon,
} from './icons/BrandIcons';

interface ConnectorsPanelProps {
  onClose: () => void;
}

const CATEGORIES = [
  { id: 'all', label: 'All' },
  { id: 'productivity', label: 'Productivity' },
  { id: 'communication', label: 'Communication' },
  { id: 'development', label: 'Development' },
  { id: 'media', label: 'Media' },
  { id: 'storage', label: 'Storage' },
];

export const ConnectorsPanel: React.FC<ConnectorsPanelProps> = ({ onClose }) => {
  const { connectors, isLoading, connectConnector, disconnectConnector, fetchConnectors, getSpotifyAuthUrl } =
    useConnectors();

  const [searchQuery, setSearchQuery] = useState('');
  const [selectedCategory, setSelectedCategory] = useState('all');
  const [selectedConnector, setSelectedConnector] = useState<ConnectorItem | null>(null);
  const [viewMode, setViewMode] = useState<'list' | 'manage' | 'connect'>('list');
  const [authFormInputs, setAuthFormInputs] = useState<Record<string, string>>({});
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isWaitingForBrowser, setIsWaitingForBrowser] = useState(false);
  const [activeInfoToolId, setActiveInfoToolId] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const pollingRef = useRef<NodeJS.Timeout | null>(null);
  const isPollingActiveRef = useRef<boolean>(false);

  const stopPolling = useCallback(() => {
    isPollingActiveRef.current = false;
    if (pollingRef.current) {
      clearTimeout(pollingRef.current);
      clearInterval(pollingRef.current);
      pollingRef.current = null;
    }
  }, []);

  const handleBackToList = useCallback(() => {
    stopPolling();
    setIsWaitingForBrowser(false);
    setIsSubmitting(false);
    setActionError(null);
    setSelectedConnector(null);
    setViewMode('list');
    fetchConnectors();
  }, [stopPolling, fetchConnectors]);

  // Clean up polling interval on unmount
  useEffect(() => {
    return () => {
      stopPolling();
    };
  }, [stopPolling]);

  // Fetch latest connectors on mount
  useEffect(() => {
    fetchConnectors();
  }, [fetchConnectors]);

  // Keyboard escape to close or return to list
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        if (viewMode !== 'list') {
          handleBackToList();
        } else {
          stopPolling();
          onClose();
        }
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [onClose, viewMode, handleBackToList, stopPolling]);

  // Keep selectedConnector updated with latest data from connectors list
  useEffect(() => {
    if (selectedConnector) {
      const updated = connectors.find((c) => c.id === selectedConnector.id);
      if (updated) setSelectedConnector(updated);
    }
  }, [connectors]);

  // Filter connectors
  const filteredConnectors = useMemo(() => {
    return connectors.filter((c) => {
      const matchesSearch =
        c.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
        c.description.toLowerCase().includes(searchQuery.toLowerCase()) ||
        c.type.toLowerCase().includes(searchQuery.toLowerCase());
      const matchesCategory = selectedCategory === 'all' || c.category === selectedCategory;
      return matchesSearch && matchesCategory;
    });
  }, [connectors, searchQuery, selectedCategory]);

  const connectedList = useMemo(
    () => filteredConnectors.filter((c) => c.status === 'connected'),
    [filteredConnectors]
  );
  const availableList = useMemo(
    () => filteredConnectors.filter((c) => c.status !== 'connected'),
    [filteredConnectors]
  );

  const renderIcon = (iconName: string, className = 'w-4 h-4') => {
    switch (iconName.toLowerCase()) {
      case 'mail':
      case 'gmail':
        return <GmailIcon className={className} />;
      case 'calendar':
      case 'google_calendar':
        return <GoogleCalendarIcon className={className} />;
      case 'harddrive':
      case 'google_drive':
        return <GoogleDriveIcon className={className} />;
      case 'github':
        return <GithubIcon className={className} />;
      case 'music':
      case 'spotify':
        return <SpotifyIcon className={className} />;
      case 'messagesquare':
      case 'slack':
        return <SlackIcon className={className} />;
      case 'filetext':
      case 'notion':
        return <NotionIcon className={className} />;
      case 'layers':
      case 'linear':
        return <LinearIcon className={className} />;
      case 'checksquare':
      case 'todoist':
        return <TodoistIcon className={className} />;
      case 'folderopen':
      case 'filesystem':
        return <FilesystemIcon className={className} />;
      default:
        return <Blocks className={`${className} text-cyan-400`} />;
    }
  };

  const handleOpenConnect = (connector: ConnectorItem) => {
    stopPolling();
    setSelectedConnector(connector);
    setAuthFormInputs({});
    setActionError(null);
    setIsWaitingForBrowser(false);
    setViewMode('connect');
  };

  const handleOpenManage = async (connector: ConnectorItem) => {
    stopPolling();
    setSelectedConnector(connector);
    setActionError(null);
    setIsWaitingForBrowser(false);
    setViewMode('manage');
    try {
      const res = await fetch(`http://127.0.0.1:8000/api/connectors/${connector.id}`);
      if (res.ok) {
        const data = await res.json();
        if (data.connector) setSelectedConnector(data.connector);
      }
    } catch (_) {}
  };

  const handleConnectSubmit = async () => {
    if (!selectedConnector) return;
    setIsSubmitting(true);
    setActionError(null);
    try {
      if (selectedConnector.auth_type === 'google_oauth' || selectedConnector.id === 'spotify') {
        let connectUrl = selectedConnector.id === 'spotify'
          ? await getSpotifyAuthUrl()
          : `http://localhost:5173/?view=connect&connector_id=${selectedConnector.id}`;

        if (selectedConnector.auth_type === 'google_oauth') {
          try {
            const urlRes = await fetch(`http://127.0.0.1:8000/api/connectors/google/auth-url?connector_id=${selectedConnector.id}`);
            if (urlRes.ok) {
              const urlData = await urlRes.json();
              if (urlData.url && !urlData.url.includes('client_id=nexus-local-client')) {
                connectUrl = urlData.url;
              }
            }
          } catch (_) {}
        }
        if (window.electronAPI?.openExternal) {
          window.electronAPI.openExternal(connectUrl);
        } else {
          window.open(connectUrl, '_blank');
        }

        setIsWaitingForBrowser(true);
        setIsSubmitting(false);

        stopPolling();
        isPollingActiveRef.current = true;
        const targetId = selectedConnector.id;

        const poll = async () => {
          if (!isPollingActiveRef.current) return;
          try {
            const loadedConnectors = await fetchConnectors();
            if (!isPollingActiveRef.current) return;
            const found = loadedConnectors.find((connector) => connector.id === targetId);
            if (found && found.status === 'connected') {
              stopPolling();
              setIsWaitingForBrowser(false);
              setSelectedConnector(found);
              setViewMode('manage');
              return;
            }
          } catch (_) {}

          if (isPollingActiveRef.current) {
            pollingRef.current = setTimeout(poll, 1500);
          }
        };

        pollingRef.current = setTimeout(poll, 1500);
        return;
      } else {
        await connectConnector(selectedConnector.id, authFormInputs);
        handleBackToList();
      }
    } catch (err: any) {
      setActionError(err?.message || 'Connection failed.');
    } finally {
      if (selectedConnector?.auth_type !== 'google_oauth') {
        setIsSubmitting(false);
      }
    }
  };

  const handleDisconnect = async (connectorId: string) => {
    if (!confirm('Are you sure you want to disconnect this service?')) return;
    setIsSubmitting(true);
    try {
      stopPolling();
      await disconnectConnector(connectorId);
      handleBackToList();
    } catch (err: any) {
      setActionError(err?.message || 'Failed to disconnect.');
    } finally {
      setIsSubmitting(false);
    }
  };

  const getTypeBadge = (type: string) => {
    switch (type) {
      case 'mcp':
        return (
          <span className="px-1.5 py-0.5 rounded text-[9.5px] font-semibold bg-purple-500/15 text-purple-300 border border-purple-500/30">
            MCP
          </span>
        );
      case 'api':
        return (
          <span className="px-1.5 py-0.5 rounded text-[9.5px] font-semibold bg-sky-500/15 text-sky-300 border border-sky-500/30">
            API
          </span>
        );
      case 'local':
        return (
          <span className="px-1.5 py-0.5 rounded text-[9.5px] font-semibold bg-emerald-500/15 text-emerald-300 border border-emerald-500/30">
            Local
          </span>
        );
      default:
        return (
          <span className="px-1.5 py-0.5 rounded text-[9.5px] font-semibold bg-white/10 text-white/60 border border-white/10">
            {type.toUpperCase()}
          </span>
        );
    }
  };

  const getRiskBadgeInfo = (risk: string) => {
    const r = risk?.toLowerCase();
    if (r === 'destructive') {
      return {
        label: 'destructive',
        badgeClass: 'bg-rose-500/20 text-rose-300 border-rose-500/30',
        dotClass: 'bg-rose-400',
        title: 'Destructive Action: Permanently modifies or deletes resources. Always triggers explicit user confirmation before running.',
      };
    }
    if (r === 'caution' || r === 'mutation') {
      return {
        label: 'caution',
        badgeClass: 'bg-amber-500/20 text-amber-300 border-amber-500/30',
        dotClass: 'bg-amber-400',
        title: 'Caution: Outgoing or mutating action (e.g. sending real emails or publishing data). Triggers the Spotlight Permission Gate so you approve before dispatch.',
      };
    }
    return {
      label: 'safe',
      badgeClass: 'bg-emerald-500/20 text-emerald-300 border-emerald-500/30',
      dotClass: 'bg-emerald-400',
      title: 'Safe Action: Read-only or local staging action (e.g. drafting an email without sending). Executes autonomously without interrupting your flow.',
    };
  };

  return (
    <div className="flex flex-col bg-[#101116]/95 text-white/90 select-none animate-in fade-in duration-150">
      {/* Header */}
      <div className="flex items-center justify-between px-5 py-3.5 border-b border-white/[0.07]">
        <div className="flex items-center gap-2.5">
          {viewMode !== 'list' ? (
            <button
              onClick={handleBackToList}
              type="button"
              className="w-6 h-6 rounded-md flex items-center justify-center text-white/60 hover:text-white hover:bg-white/[0.08] transition-colors"
            >
              <ChevronLeft className="w-4 h-4" />
            </button>
          ) : (
            <div className="w-6 h-6 rounded-lg bg-cyan-500/10 border border-cyan-500/20 flex items-center justify-center p-0.5 shadow-[0_0_8px_rgba(6,182,212,0.25)]">
              <Blocks className="w-3.5 h-3.5 text-cyan-400" />
            </div>
          )}

          <div className="flex items-center gap-2">
            <span className="text-[13px] font-semibold text-white tracking-tight">
              {viewMode === 'manage'
                ? `Manage ${selectedConnector?.name || 'Connector'}`
                : viewMode === 'connect'
                ? `Connect ${selectedConnector?.name || 'Service'}`
                : 'Connectors & MCP Hub'}
            </span>
            <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-white/[0.05] text-white/50 border border-white/[0.07]">
              {viewMode === 'list'
                ? `${connectors.length} services`
                : selectedConnector?.type.toUpperCase()}
            </span>
          </div>
        </div>

        <div className="flex items-center gap-1">
          <button
            onClick={async () => {
              await fetchConnectors();
              if (selectedConnector) {
                try {
                  const res = await fetch(`http://127.0.0.1:8000/api/connectors/${selectedConnector.id}`);
                  if (res.ok) {
                    const data = await res.json();
                    if (data.connector) setSelectedConnector(data.connector);
                  }
                } catch (_) {}
              }
            }}
            type="button"
            title="Refresh connectors"
            disabled={isLoading}
            className="w-6 h-6 rounded-md flex items-center justify-center text-white/40 hover:text-white hover:bg-white/[0.08] disabled:opacity-40 transition-colors"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${isLoading ? 'animate-spin' : ''}`} strokeWidth={1.8} />
          </button>
          <button
            onClick={() => {
              stopPolling();
              onClose();
            }}
            type="button"
            title="Close (Esc)"
            className="w-6 h-6 rounded-md flex items-center justify-center text-white/40 hover:text-white hover:bg-white/[0.08] transition-colors"
          >
            <X className="w-3.5 h-3.5" strokeWidth={1.8} />
          </button>
        </div>
      </div>

      {/* ── MANAGE VIEW ────────────────────────────────────────────────────── */}
      {viewMode === 'manage' && selectedConnector && (
        <div className="px-5 py-4 max-h-[500px] overflow-y-auto space-y-4 text-xs custom-scrollbar">
          <div className="flex items-start justify-between p-3.5 rounded-xl bg-white/[0.03] border border-white/10">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-xl bg-white/5 border border-white/10 flex items-center justify-center flex-shrink-0">
                {renderIcon(selectedConnector.icon, 'w-5 h-5')}
              </div>
              <div>
                <div className="flex items-center gap-2">
                  <h3 className="text-sm font-semibold text-white">{selectedConnector.name}</h3>
                  {getTypeBadge(selectedConnector.type)}
                </div>
                <p className="text-[11px] text-white/50 mt-0.5">{selectedConnector.description}</p>
                {selectedConnector.account_identifier && (
                  <p className="text-[11px] text-cyan-400 mt-1">
                    Connected as: <span className="font-mono text-white/80">{selectedConnector.account_identifier}</span>
                  </p>
                )}
              </div>
            </div>
            <span className="flex items-center gap-1 text-[11px] font-medium text-emerald-400 bg-emerald-500/10 border border-emerald-500/20 px-2 py-0.5 rounded-full">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
              Connected
            </span>
          </div>

          {/* Capabilities */}
          <div>
            <h4 className="text-[11px] font-semibold text-white/60 tracking-wider uppercase mb-2">Capabilities</h4>
            <div className="flex flex-wrap gap-1.5">
              {selectedConnector.capabilities.map((cap, i) => (
                <span key={i} className="px-2.5 py-1 rounded-lg bg-white/5 border border-white/10 text-[11px] text-white/80">
                  {cap}
                </span>
              ))}
            </div>
          </div>

          {/* Discovered Tools */}
          <div>
            <div className="flex items-center justify-between mb-2">
              <h4 className="text-[11px] font-semibold text-white/60 tracking-wider uppercase">
                Active Tools in Unified Registry ({selectedConnector.discovered_tools?.length || 0})
              </h4>
            </div>
            <div className="space-y-2">
              {selectedConnector.discovered_tools && selectedConnector.discovered_tools.length > 0 ? (
                selectedConnector.discovered_tools.map((t) => {
                  const riskInfo = getRiskBadgeInfo(t.risk_level);
                  const isInfoActive = activeInfoToolId === t.tool_id;
                  return (
                    <div key={t.tool_id} className="p-2.5 rounded-lg bg-white/[0.02] border border-white/5 hover:border-white/15 transition-all">
                      <div className="flex items-center justify-between">
                        <span className="font-mono text-[11px] text-cyan-300 font-medium">{t.name}</span>
                        <button
                          type="button"
                          onMouseEnter={() => setActiveInfoToolId(t.tool_id)}
                          onMouseLeave={() => setActiveInfoToolId(null)}
                          onClick={() => setActiveInfoToolId((prev) => (prev === t.tool_id ? null : t.tool_id))}
                          className={`text-[9.5px] px-2 py-0.5 rounded font-mono border ${riskInfo.badgeClass} flex items-center gap-1 cursor-pointer hover:brightness-125 transition-all`}
                        >
                          <span>{riskInfo.label}</span>
                          <Info className="w-2.5 h-2.5 opacity-70" />
                        </button>
                      </div>
                      <p className="text-[10.5px] text-white/50 mt-1">{t.description}</p>

                      {/* Inline in-brief explanation on hover or click - zero clipping */}
                      {isInfoActive && (
                        <div className="mt-2 p-2 rounded-lg bg-black/60 border border-white/10 flex items-start gap-2 text-[10.5px] animate-in fade-in slide-in-from-top-1 duration-150">
                          <Info
                            className={`w-3.5 h-3.5 shrink-0 mt-0.5 ${
                              t.risk_level === 'destructive'
                                ? 'text-rose-400'
                                : t.risk_level === 'caution' || t.risk_level === 'mutation'
                                ? 'text-amber-400'
                                : 'text-emerald-400'
                            }`}
                          />
                          <div className="leading-snug">
                            <span className="font-semibold text-white capitalize">{riskInfo.label} Level: </span>
                            <span className="text-white/70">{riskInfo.title}</span>
                          </div>
                        </div>
                      )}
                    </div>
                  );
                })
              ) : (
                <p className="text-[11px] text-white/40 italic">No tools registered yet.</p>
              )}
            </div>
          </div>

          {/* Actions */}
          <div className="flex items-center justify-between pt-3 border-t border-white/10">
            <button
              onClick={() => handleDisconnect(selectedConnector.id)}
              disabled={isSubmitting || selectedConnector.type === 'local'}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11px] font-medium text-rose-400 bg-rose-500/10 hover:bg-rose-500/20 border border-rose-500/20 disabled:opacity-30 transition-colors"
            >
              <Trash2 className="w-3.5 h-3.5" />
              Disconnect Service
            </button>
            <button
              onClick={() => handleOpenConnect(selectedConnector)}
              className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg text-[11px] font-medium text-white bg-white/10 hover:bg-white/15 transition-colors"
            >
              <RefreshCw className="w-3.5 h-3.5" />
              Reconnect
            </button>
          </div>
        </div>
      )}

      {/* ── CONNECT VIEW ────────────────────────────────────────────────────── */}
      {viewMode === 'connect' && selectedConnector && (
        <div className="px-5 py-4 max-h-[500px] overflow-y-auto space-y-4 text-xs custom-scrollbar">
          <div className="flex items-start gap-3 p-3.5 rounded-xl bg-white/[0.03] border border-white/10">
            <div className="w-10 h-10 rounded-xl bg-white/5 border border-white/10 flex items-center justify-center flex-shrink-0">
              {renderIcon(selectedConnector.icon, 'w-5 h-5')}
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h3 className="text-sm font-semibold text-white">{selectedConnector.name}</h3>
                {getTypeBadge(selectedConnector.type)}
              </div>
              <p className="text-[11px] text-white/50 mt-0.5">{selectedConnector.description}</p>
            </div>
          </div>

          {actionError && (
            <div className="flex items-center gap-2 p-2.5 rounded-lg bg-rose-500/10 border border-rose-500/30 text-rose-300 text-[11px]">
              <AlertCircle className="w-3.5 h-3.5 flex-shrink-0" />
              <span>{actionError}</span>
            </div>
          )}

          {selectedConnector.auth_type === 'google_oauth' || selectedConnector.id === 'spotify' ? (
            isWaitingForBrowser ? (
              <div className="p-5 rounded-xl bg-sky-500/10 border border-sky-500/20 text-center space-y-3 animate-in fade-in duration-200">
                <div className="w-12 h-12 rounded-full bg-sky-500/15 border border-sky-500/30 text-sky-400 flex items-center justify-center mx-auto">
                  <Loader2 className="w-6 h-6 animate-spin text-sky-400" />
                </div>
                <div>
                  <p className="text-xs font-semibold text-white">Opened in your Browser</p>
                  <p className="text-[11px] text-white/60 mt-1 max-w-sm mx-auto leading-relaxed">
                    {selectedConnector.id === 'spotify'
                      ? 'Sign in to Spotify and approve NEXUS. Your session will renew automatically after this one-time authorization.'
                      : 'Please approve the connection using your active Google account in the browser tab. NEXUS will detect it and link automatically.'}
                  </p>
                </div>
                <div className="pt-2 flex items-center justify-center gap-2.5">
                  <button
                    type="button"
                    onClick={async () => {
                      try {
                        const connectUrl = selectedConnector.id === 'spotify'
                          ? await getSpotifyAuthUrl()
                          : `http://localhost:5173/?view=connect&connector_id=${selectedConnector.id}`;
                        if (window.electronAPI?.openExternal) {
                          window.electronAPI.openExternal(connectUrl);
                        } else {
                          window.open(connectUrl, '_blank');
                        }
                      } catch (err: any) {
                        setActionError(err?.message || 'Could not open authorization page.');
                      }
                    }}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11px] font-medium text-white/90 bg-white/10 hover:bg-white/15 transition-colors"
                  >
                    <ExternalLink className="w-3.5 h-3.5" />
                    <span>Re-open Browser</span>
                  </button>
                  <button
                    type="button"
                    onClick={handleBackToList}
                    className="px-3 py-1.5 rounded-lg text-[11px] font-medium text-white/50 hover:text-white/80 transition-colors"
                  >
                    Cancel
                  </button>
                </div>
              </div>
            ) : (
              <div className="p-5 rounded-xl bg-white/[0.02] border border-white/10 text-center space-y-3">
                <div className="w-12 h-12 rounded-xl bg-white/[0.04] border border-white/10 flex items-center justify-center mx-auto shadow-inner">
                  {renderIcon(selectedConnector.icon, 'w-6 h-6')}
                </div>
                <div>
                  <p className="text-xs font-semibold text-white">Connect {selectedConnector.name} in Browser</p>
                  <p className="text-[11px] text-white/50 mt-1 max-w-sm mx-auto leading-relaxed">
                    {selectedConnector.id === 'spotify'
                      ? 'Sign in once in Spotify. NEXUS stores the refresh token locally and renews short-lived access tokens automatically.'
                      : 'Opens in your default browser so you can sign in directly using your existing Google account without re-typing passwords or 2FA.'}
                  </p>
                </div>
                {selectedConnector.id === 'spotify' && (
                  <p className="text-[10px] text-white/45 max-w-sm mx-auto leading-relaxed">
                    One-time setup: set <span className="font-mono text-white/70">SPOTIFY_CLIENT_ID</span> in the backend environment and register
                    <span className="font-mono text-white/70"> http://127.0.0.1:8000/api/connectors/spotify/callback</span> as the redirect URI in your Spotify app.
                  </p>
                )}
                <div className="pt-2">
                  <button
                    onClick={handleConnectSubmit}
                    disabled={isSubmitting}
                    className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl text-xs font-semibold bg-white text-black hover:bg-neutral-200 transition-all shadow-[0_0_15px_rgba(255,255,255,0.2)] hover:scale-[1.01] active:scale-[0.99] disabled:opacity-50"
                  >
                    {renderIcon(selectedConnector.icon, 'w-4 h-4')}
                    <span>{selectedConnector.id === 'spotify' ? 'Connect with Spotify' : 'Authorize in Default Browser'}</span>
                    <ExternalLink className="w-3.5 h-3.5 text-black/60" />
                  </button>
                </div>
                <p className="text-[10px] text-white/40">
                  {selectedConnector.id === 'spotify'
                    ? 'Uses Spotify OAuth with PKCE; no client secret is stored.'
                    : 'Uses your active browser Google profile automatically'}
                </p>
              </div>
            )
          ) : selectedConnector.auth_fields && selectedConnector.auth_fields.length > 0 ? (
            <div className="space-y-3">
              {selectedConnector.auth_fields.map((f) => (
                <div key={f.id}>
                  <label className="block text-[11px] font-medium text-white/70 mb-1">{f.label}</label>
                  <input
                    type={f.type === 'password' ? 'password' : 'text'}
                    placeholder={f.placeholder}
                    value={authFormInputs[f.id] || ''}
                    onChange={(e) => setAuthFormInputs((prev) => ({ ...prev, [f.id]: e.target.value }))}
                    className="w-full px-3 py-2 bg-white/5 border border-white/10 rounded-lg text-xs text-white placeholder-white/30 focus:outline-none focus:border-cyan-500/50"
                  />
                </div>
              ))}
              <div className="pt-2 flex justify-end gap-2">
                <button
                  type="button"
                  onClick={handleBackToList}
                  className="px-3 py-1.5 rounded-lg text-xs font-medium text-white/60 hover:text-white"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  onClick={handleConnectSubmit}
                  disabled={isSubmitting}
                  className="px-4 py-1.5 rounded-lg text-xs font-semibold bg-cyan-500 hover:bg-cyan-400 text-black transition-colors disabled:opacity-50"
                >
                  {isSubmitting ? 'Connecting...' : 'Connect Service'}
                </button>
              </div>
            </div>
          ) : (
            <div className="text-center py-4 space-y-3">
              <p className="text-xs text-white/60">This connector does not require authentication.</p>
              <button
                onClick={handleConnectSubmit}
                disabled={isSubmitting}
                className="px-4 py-1.5 rounded-lg text-xs font-semibold bg-cyan-500 hover:bg-cyan-400 text-black transition-colors"
              >
                {isSubmitting ? 'Enabling...' : 'Enable Connector'}
              </button>
            </div>
          )}
        </div>
      )}

      {/* ── LIST VIEW ──────────────────────────────────────────────────────── */}
      {viewMode === 'list' && (
        <>
          {/* Search & Category Filter */}
          <div className="px-5 pt-3 pb-2 border-b border-white/[0.05] space-y-2">
            <div className="relative flex items-center w-full">
              <Search className="absolute left-2.5 w-3.5 h-3.5 text-white/40" />
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search connectors or protocols (e.g. Gmail, GitHub, MCP)..."
                className="w-full pl-8 pr-7 py-1.5 bg-white/[0.03] border border-white/[0.08] rounded-lg text-xs text-white placeholder-white/35 focus:outline-none focus:border-cyan-500/40 transition-all"
              />
              {searchQuery && (
                <button
                  onClick={() => setSearchQuery('')}
                  className="absolute right-2.5 p-0.5 rounded text-white/40 hover:text-white"
                >
                  <X className="w-3 h-3" />
                </button>
              )}
            </div>

            {/* Category Pills */}
            <div className="flex items-center gap-1 overflow-x-auto pb-0.5 custom-scrollbar">
              {CATEGORIES.map((cat) => (
                <button
                  key={cat.id}
                  onClick={() => setSelectedCategory(cat.id)}
                  type="button"
                  className={`px-2 py-0.5 rounded-md text-[10.5px] font-medium whitespace-nowrap transition-all ${
                    selectedCategory === cat.id
                      ? 'bg-cyan-500/15 text-cyan-300 border border-cyan-500/30'
                      : 'text-white/45 hover:text-white/80 hover:bg-white/[0.04]'
                  }`}
                >
                  {cat.label}
                </button>
              ))}
            </div>
          </div>

          {/* Connectors List Area */}
          <div className="px-5 py-3 max-h-[380px] overflow-y-auto space-y-4 custom-scrollbar">
            {isLoading && connectors.length === 0 ? (
              <div className="flex items-center justify-center py-10 text-xs text-white/40 gap-2">
                <RefreshCw className="w-4 h-4 animate-spin text-cyan-400" />
                <span>Loading connectors...</span>
              </div>
            ) : filteredConnectors.length === 0 ? (
              <div className="text-center py-8 text-xs text-white/40">
                <Blocks className="w-6 h-6 mx-auto mb-2 text-white/20" />
                No connectors match your search or filter.
              </div>
            ) : (
              <>
                {/* CONNECTED SECTION */}
                {connectedList.length > 0 && (
                  <div>
                    <div className="flex items-center gap-2 mb-2">
                      <span className="text-[10px] font-bold tracking-wider text-emerald-400 uppercase">
                        CONNECTED ({connectedList.length})
                      </span>
                      <div className="h-[1px] flex-1 bg-emerald-500/20" />
                    </div>

                    <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                      {connectedList.map((item) => (
                        <div
                          key={item.id}
                          className="flex flex-col justify-between p-3 rounded-xl bg-emerald-500/[0.04] border border-emerald-500/20 hover:border-emerald-500/40 transition-all group"
                        >
                          <div>
                            <div className="flex items-start justify-between gap-2 mb-1.5">
                              <div className="flex items-center gap-2.5 min-w-0">
                                <div className="w-8 h-8 rounded-lg bg-white/5 border border-white/10 flex items-center justify-center flex-shrink-0">
                                  {renderIcon(item.icon, 'w-4 h-4')}
                                </div>
                                <div className="min-w-0">
                                  <div className="flex items-center gap-1.5">
                                    <h3 className="text-xs font-semibold text-white group-hover:text-cyan-300 transition-colors truncate">
                                      {item.name}
                                    </h3>
                                    {getTypeBadge(item.type)}
                                  </div>
                                  <div className="flex items-center gap-1 mt-0.5">
                                    <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
                                    <span className="text-[10px] font-medium text-emerald-400">Connected</span>
                                  </div>
                                </div>
                              </div>
                            </div>
                            <p className="text-[11px] text-white/50 line-clamp-1 mb-2">{item.description}</p>
                          </div>

                          <div className="flex items-center justify-between pt-1.5 border-t border-white/5 mt-auto">
                            <span className="text-[9.5px] text-white/40">
                              {item.discovered_tools?.length || item.capabilities?.length || 0} tools active
                            </span>
                            <button
                              onClick={() => handleOpenManage(item)}
                              type="button"
                              className="px-2.5 py-1 rounded-md text-[11px] font-medium bg-white/10 hover:bg-white/15 text-white transition-colors"
                            >
                              Manage
                            </button>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* AVAILABLE SECTION */}
                <div>
                  <div className="flex items-center gap-2 mb-2">
                    <span className="text-[10px] font-bold tracking-wider text-cyan-400 uppercase">
                      AVAILABLE ({availableList.length})
                    </span>
                    <div className="h-[1px] flex-1 bg-cyan-500/20" />
                  </div>

                  <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                    {availableList.map((item) => (
                      <div
                        key={item.id}
                        className="flex flex-col justify-between p-3 rounded-xl bg-white/[0.02] border border-white/[0.06] hover:border-white/20 transition-all group"
                      >
                        <div>
                          <div className="flex items-start justify-between gap-2 mb-1.5">
                            <div className="flex items-center gap-2.5 min-w-0">
                              <div className="w-8 h-8 rounded-lg bg-white/5 border border-white/10 flex items-center justify-center flex-shrink-0">
                                {renderIcon(item.icon, 'w-4 h-4')}
                              </div>
                              <div className="min-w-0">
                                <div className="flex items-center gap-1.5">
                                  <h3 className="text-xs font-semibold text-white group-hover:text-cyan-300 transition-colors truncate">
                                    {item.name}
                                  </h3>
                                  {getTypeBadge(item.type)}
                                </div>
                                <div className="mt-0.5">
                                  {item.status === 'action_required' ? (
                                    <span className="flex items-center gap-1 text-[10px] text-amber-400 font-medium">
                                      <AlertCircle className="w-2.5 h-2.5" />
                                      Action required
                                    </span>
                                  ) : (
                                    <span className="text-[10px] text-white/40">Not connected</span>
                                  )}
                                </div>
                              </div>
                            </div>
                          </div>
                          <p className="text-[11px] text-white/50 line-clamp-1 mb-2">{item.description}</p>
                        </div>

                        <div className="flex items-center justify-between pt-1.5 border-t border-white/5 mt-auto">
                          <span className="text-[9.5px] text-white/40 truncate max-w-[120px]">
                            {item.capabilities?.slice(0, 2).join(', ')}
                          </span>
                          <button
                            onClick={() => handleOpenConnect(item)}
                            type="button"
                            className="px-2.5 py-1 rounded-md text-[11px] font-semibold bg-cyan-500/20 hover:bg-cyan-500/30 text-cyan-300 border border-cyan-500/40 transition-all"
                          >
                            Connect
                          </button>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              </>
            )}
          </div>
        </>
      )}

      {/* Footer */}
      <div className="flex items-center justify-between px-5 py-2.5 border-t border-white/[0.06] bg-white/[0.01] text-[10.5px] text-white/40">
        <div className="flex items-center gap-1.5">
          <Shield className="w-3.5 h-3.5 text-cyan-400" />
          <span>Protected by NEXUS Permission Gate & Tool Registry.</span>
        </div>
      </div>
    </div>
  );
};
