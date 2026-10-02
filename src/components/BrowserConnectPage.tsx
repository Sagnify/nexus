import React, { useState, useEffect } from 'react';
import { auth } from '../config/firebase';
import { GoogleAuthProvider, signInWithPopup, signInWithRedirect, getRedirectResult } from 'firebase/auth';
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
} from './icons/BrandIcons';
import {
  CheckCircle2,
  AlertCircle,
  Loader2,
  ArrowRight,
  ShieldCheck,
  Sparkles,
  Lock,
  Mail,
  Calendar,
} from 'lucide-react';
import nexusLogo from '../assets/nexus-logo.png';

interface ConnectorInfo {
  id: string;
  name: string;
  description: string;
  required_scopes?: string[];
  status?: string;
  account_identifier?: string;
}

export const BrowserConnectPage: React.FC = () => {
  const urlParams = new URLSearchParams(window.location.search);
  const connectorId = urlParams.get('connector_id') || 'gmail';

  const [loading, setLoading] = useState(true);
  const [authorizing, setAuthorizing] = useState(false);
  const [connector, setConnector] = useState<ConnectorInfo | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
  const [connectedEmail, setConnectedEmail] = useState<string | null>(null);

  const [serverAuthUrl, setServerAuthUrl] = useState<string | null>(null);

  // Full-screen and flex-stretch reset so page centers accurately on all monitor sizes
  useEffect(() => {
    const root = document.getElementById('root');
    const body = document.body;
    const html = document.documentElement;

    if (root) {
      root.style.minHeight = '100vh';
      root.style.height = '100%';
      root.style.width = '100%';
      root.style.alignItems = 'stretch';
      root.style.overflow = 'auto';
      root.style.background = '#08090e';
    }
    if (body) {
      body.style.overflow = 'auto';
      body.style.background = '#08090e';
      body.style.width = '100%';
    }
    if (html) {
      html.style.overflow = 'auto';
      html.style.background = '#08090e';
      html.style.width = '100%';
    }

    return () => {
      if (root) {
        root.style.minHeight = '';
        root.style.height = '';
        root.style.alignItems = '';
        root.style.width = '';
        root.style.overflow = '';
      }
    };
  }, []);

  // Fetch connector details and check if offline backend OAuth is configured
  useEffect(() => {
    const fetchInfo = async () => {
      setLoading(true);
      try {
        const [connRes, authUrlRes] = await Promise.allSettled([
          fetch(`http://127.0.0.1:8000/api/connectors/${connectorId}`),
          fetch(`http://127.0.0.1:8000/api/connectors/google/auth-url?connector_id=${connectorId}`),
        ]);

        if (authUrlRes.status === 'fulfilled' && authUrlRes.value.ok) {
          const urlData = await authUrlRes.value.json().catch(() => ({}));
          if (urlData.url && !urlData.url.includes('client_id=nexus-local-client')) {
            setServerAuthUrl(urlData.url);
          }
        }

        if (connRes.status === 'fulfilled' && connRes.value.ok) {
          const data = await connRes.value.json();
          setConnector(data.connector);
        } else {
          if (connectorId === 'gmail') {
            setConnector({
              id: 'gmail',
              name: 'Gmail',
              description: 'Send and draft emails directly through official Gmail API.',
              required_scopes: [
                'https://www.googleapis.com/auth/gmail.send',
                'https://www.googleapis.com/auth/gmail.compose',
              ],
            });
          } else if (connectorId === 'google_calendar') {
            setConnector({
              id: 'google_calendar',
              name: 'Google Calendar',
              description: 'View schedules, find open time slots, and manage meetings seamlessly.',
              required_scopes: [
                'https://www.googleapis.com/auth/calendar.events',
                'https://www.googleapis.com/auth/calendar.readonly',
              ],
            });
          } else if (connectorId === 'google_drive') {
            setConnector({
              id: 'google_drive',
              name: 'Google Drive',
              description: 'Search documents, spreadsheets, and files stored in your Google Drive.',
              required_scopes: [
                'https://www.googleapis.com/auth/drive.readonly',
              ],
            });
          } else {
            setConnector({
              id: connectorId,
              name: connectorId.toUpperCase(),
              description: 'External app integration for NEXUS.',
            });
          }
        }
      } catch (_) {
        setConnector({
          id: connectorId,
          name: connectorId === 'gmail' ? 'Gmail' : connectorId === 'google_calendar' ? 'Google Calendar' : connectorId === 'google_drive' ? 'Google Drive' : connectorId,
          description: 'Official API integration for NEXUS.',
          required_scopes:
            connectorId === 'gmail'
              ? [
                  'https://www.googleapis.com/auth/gmail.send',
                  'https://www.googleapis.com/auth/gmail.compose',
                ]
              : connectorId === 'google_drive'
              ? [
                  'https://www.googleapis.com/auth/drive.readonly',
                ]
              : [
                  'https://www.googleapis.com/auth/calendar.events',
                  'https://www.googleapis.com/auth/calendar.readonly',
                ],
        });
      } finally {
        setLoading(false);
      }
    };

    fetchInfo();
  }, [connectorId]);

  // Check if returning from a seamless in-tab Google Auth redirect
  useEffect(() => {
    getRedirectResult(auth)
      .then(async (result) => {
        if (!result) return;
        const credential = GoogleAuthProvider.credentialFromResult(result);
        const accessToken = credential?.accessToken;
        if (!accessToken) return;

        const email = result.user.email || 'Google Account';
        setConnectedEmail(email);

        const res = await fetch(`http://127.0.0.1:8000/api/connectors/${connectorId}/connect`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            tokens: {
              access_token: accessToken,
              account_identifier: email,
            },
          }),
        });

        if (res.ok) {
          setSuccess(true);
        } else {
          const data = await res.json().catch(() => ({}));
          setError(data.detail || 'Failed to save connector credentials.');
        }
      })
      .catch((err) => {
        console.warn('Redirect auth result error:', err);
      });
  }, [connectorId]);

  const handleDirectRedirect = async () => {
    if (serverAuthUrl) {
      window.location.href = serverAuthUrl;
      return;
    }
    setAuthorizing(true);
    setError(null);

    const provider = new GoogleAuthProvider();
    provider.setCustomParameters({ prompt: 'consent select_account' });

    const scopes =
      connector?.required_scopes ||
      (connectorId === 'gmail'
        ? [
            'https://www.googleapis.com/auth/gmail.send',
            'https://www.googleapis.com/auth/gmail.compose',
          ]
        : connectorId === 'google_drive'
        ? [
            'https://www.googleapis.com/auth/drive.readonly',
          ]
        : [
            'https://www.googleapis.com/auth/calendar.events',
            'https://www.googleapis.com/auth/calendar.readonly',
          ]);

    scopes.forEach((s) => provider.addScope(s));
    await signInWithRedirect(auth, provider);
  };

  const handleGoogleAuth = async () => {
    // 1. If backend has official OAuth Client ID configured, redirect directly (never blocked by popup blocker)
    if (serverAuthUrl) {
      window.location.href = serverAuthUrl;
      return;
    }

    setAuthorizing(true);
    setError(null);

    // 2. Prepare Google Auth Provider synchronously
    const provider = new GoogleAuthProvider();
    provider.setCustomParameters({ prompt: 'consent select_account' });

    const scopes =
      connector?.required_scopes ||
      (connectorId === 'gmail'
        ? [
            'https://www.googleapis.com/auth/gmail.send',
            'https://www.googleapis.com/auth/gmail.compose',
          ]
        : connectorId === 'google_drive'
        ? [
            'https://www.googleapis.com/auth/drive.readonly',
          ]
        : [
            'https://www.googleapis.com/auth/calendar.events',
            'https://www.googleapis.com/auth/calendar.readonly',
          ]);

    scopes.forEach((s) => provider.addScope(s));

    try {
      // Trigger popup
      const result = await signInWithPopup(auth, provider);
      const credential = GoogleAuthProvider.credentialFromResult(result);
      const accessToken = credential?.accessToken;

      if (!accessToken) {
        throw new Error('Google did not return an access token for requested permissions.');
      }

      const email = result.user.email || 'Google Account';
      setConnectedEmail(email);

      // Post token to NEXUS local backend
      const res = await fetch(`http://127.0.0.1:8000/api/connectors/${connectorId}/connect`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          tokens: {
            access_token: accessToken,
            account_identifier: email,
          },
        }),
      });

      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || `Server error (${res.status}) while saving connector.`);
      }

      setSuccess(true);
    } catch (err: any) {
      if (err.code === 'auth/popup-blocked') {
        console.info('Popup blocked by browser. Automatically continuing via in-tab redirect...');
        setAuthorizing(true);
        setError(null);
        await signInWithRedirect(auth, provider);
        return;
      } else if (err.code === 'auth/popup-closed-by-user') {
        setError('Sign-in cancelled: The Google popup was closed before completion.');
      } else {
        setError(err.message || 'Authorization failed. Please try again.');
      }
    } finally {
      setAuthorizing(false);
    }
  };

  const renderConnectorIcon = (size = 'w-10 h-10') => {
    switch (connectorId) {
      case 'gmail':
        return <GmailIcon className={size} />;
      case 'google_calendar':
        return <GoogleCalendarIcon className={size} />;
      case 'google_drive':
        return <GoogleDriveIcon className={size} />;
      case 'github':
        return <GithubIcon className={size} />;
      case 'spotify':
        return <SpotifyIcon className={size} />;
      case 'slack':
        return <SlackIcon className={size} />;
      case 'notion':
        return <NotionIcon className={size} />;
      case 'linear':
        return <LinearIcon className={size} />;
      case 'todoist':
        return <TodoistIcon className={size} />;
      default:
        return (
          <div
            className={`${size} rounded-xl bg-sky-500/20 text-sky-400 flex items-center justify-center font-bold text-lg`}
          >
            {connector?.name?.charAt(0) || 'C'}
          </div>
        );
    }
  };

  return (
    <div className="w-full min-h-screen bg-[#08090e] text-white flex flex-col justify-between items-center px-6 py-8 md:py-12 relative overflow-x-hidden font-sans antialiased selection:bg-sky-500/30">
      {/* Centered ambient glows spanning the screen */}
      <div className="absolute top-1/4 left-1/2 -translate-x-1/2 w-[900px] h-[500px] bg-gradient-to-r from-sky-500/[0.04] via-indigo-500/[0.03] to-cyan-500/[0.04] rounded-full blur-[140px] pointer-events-none" />

      {/* Header (Centered Container) */}
      <header className="w-full max-w-5xl flex items-center justify-between z-10 mb-8">
        <div className="flex items-center gap-3">
          <img src={nexusLogo} alt="NEXUS" className="w-8 h-8 rounded-lg shadow-sm" />
          <span className="text-sm font-semibold tracking-wide text-white/90">
            NEXUS
          </span>
        </div>

        <div className="flex items-center gap-2 text-xs text-white/50 bg-white/[0.03] border border-white/[0.06] px-3 py-1.5 rounded-full">
          <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
          <span>Desktop App Connected</span>
        </div>
      </header>

      {/* Main Grid: Left Auth Card + Right Preview Card (Centered Container) */}
      <main className="w-full max-w-5xl grid grid-cols-1 lg:grid-cols-12 gap-8 items-stretch relative z-10 my-auto">
        {/* ── LEFT: AUTHENTICATION CARD ────────────────────────────────────── */}
        <div className="lg:col-span-6 w-full flex flex-col justify-between bg-[#10121a]/90 border border-white/[0.08] backdrop-blur-2xl rounded-2xl p-7 md:p-8 shadow-[0_20px_50px_rgba(0,0,0,0.5)]">
          {loading ? (
            <div className="py-20 flex flex-col items-center justify-center gap-3 text-white/50">
              <Loader2 className="w-7 h-7 animate-spin text-sky-400" />
              <span className="text-xs">Preparing connection...</span>
            </div>
          ) : success ? (
            <div className="py-10 flex flex-col items-center text-center animate-in zoom-in-95 duration-200 my-auto">
              <div className="w-14 h-14 rounded-full bg-emerald-500/15 border border-emerald-500/30 flex items-center justify-center text-emerald-400 mb-4 shadow-lg shadow-emerald-500/10">
                <CheckCircle2 className="w-7 h-7" />
              </div>

              <h2 className="text-xl font-semibold text-white mb-1.5">
                Connected to {connector?.name || 'Google'}
              </h2>
              <p className="text-xs text-white/60 mb-5">
                Linked as <span className="text-emerald-300 font-medium">{connectedEmail}</span>
              </p>

              <div className="bg-white/[0.03] border border-white/[0.08] rounded-xl px-4 py-3 text-xs text-white/70 mb-6 flex items-center gap-2.5 text-left w-full">
                <ShieldCheck className="w-4 h-4 shrink-0 text-emerald-400" />
                <span>
                  NEXUS Spotlight has updated automatically. You can now use {connector?.name || 'this service'}.
                </span>
              </div>

              <button
                onClick={() => window.close()}
                className="w-full py-2.5 px-4 rounded-xl bg-white/[0.08] hover:bg-white/[0.12] border border-white/10 text-white font-medium text-xs transition-colors"
              >
                Done, Close Tab
              </button>
            </div>
          ) : (
            <div className="flex flex-col justify-between h-full">
              <div>
                {/* Header */}
                <div className="flex items-center gap-3.5 pb-5 border-b border-white/[0.06]">
                  <div className="p-2.5 bg-white/[0.04] border border-white/[0.08] rounded-xl flex items-center justify-center">
                    {renderConnectorIcon('w-8 h-8')}
                  </div>
                  <div>
                    <h1 className="text-base font-semibold text-white">
                      Connect {connector?.name || 'Google Account'}
                    </h1>
                    <p className="text-xs text-white/50 mt-0.5">
                      Authorize NEXUS to access your {connector?.name || 'account'}.
                    </p>
                  </div>
                </div>

                {/* Explanation */}
                <div className="py-5 space-y-4">
                  <p className="text-xs text-white/65 leading-relaxed">
                    {connector?.description || 'Enable NEXUS to seamlessly assist you with your tasks.'}
                  </p>

                  <div className="p-3.5 rounded-xl bg-white/[0.02] border border-white/[0.06] text-xs space-y-1.5">
                    <div className="font-medium text-white/80 flex items-center gap-2">
                      <Sparkles className="w-3.5 h-3.5 text-sky-400" />
                      <span>One-click browser authorization</span>
                    </div>
                    <p className="text-[11px] text-white/50 leading-normal">
                      Since this is in your primary browser, you can simply pick your existing Google profile without typing passwords.
                    </p>
                  </div>
                </div>

                {/* Error */}
                {error && (
                  <div className="mb-4 p-3 rounded-xl bg-red-500/10 border border-red-500/20 flex items-center gap-2.5 text-xs text-red-300">
                    <AlertCircle className="w-4 h-4 shrink-0 text-red-400" />
                    <span>{error}</span>
                  </div>
                )}
              </div>

              {/* Action Button & Security */}
              <div className="pt-4">
                <button
                  onClick={handleGoogleAuth}
                  disabled={authorizing}
                  className="w-full py-3 px-4 rounded-xl bg-white text-black hover:bg-neutral-200 font-medium text-xs tracking-tight transition-all flex items-center justify-center gap-2 shadow-lg shadow-white/5 hover:scale-[1.005] active:scale-[0.99] disabled:opacity-50"
                >
                  {authorizing ? (
                    <>
                      <Loader2 className="w-4 h-4 animate-spin text-black" />
                      <span>Signing in...</span>
                    </>
                  ) : (
                    <>
                      <span>Continue with Google</span>
                      <ArrowRight className="w-3.5 h-3.5" />
                    </>
                  )}
                </button>

                <button
                  type="button"
                  onClick={handleDirectRedirect}
                  disabled={authorizing}
                  className="w-full mt-2.5 py-2 px-3 rounded-xl bg-white/[0.04] hover:bg-white/[0.08] border border-white/[0.06] text-white/60 hover:text-white/90 text-xs transition-colors flex items-center justify-center gap-1.5"
                >
                  <span>Authorize in this tab (No popup required)</span>
                  <ArrowRight className="w-3 h-3 text-white/40" />
                </button>

                <div className="mt-3.5 flex items-center justify-center gap-1.5 text-[11px] text-white/35">
                  <Lock className="w-3 h-3" />
                  <span>Tokens are stored locally on your device</span>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* ── RIGHT: SPOTLIGHT PREVIEW & VALUES ────────────────────────────── */}
        <div className="lg:col-span-6 w-full flex flex-col justify-between bg-[#10121a]/60 border border-white/[0.06] rounded-2xl p-7 md:p-8 shadow-xl">
          <div className="space-y-4">
            <span className="text-[11px] font-medium text-white/40 tracking-wider uppercase block">
              How it works in NEXUS
            </span>

            {/* Mockup Spotlight Bar */}
            <div className="rounded-xl bg-black/60 border border-white/[0.09] p-4 shadow-inner space-y-3">
              <div className="flex items-center gap-2.5 text-xs">
                <div className="w-2 h-2 rounded-full bg-cyan-400 animate-pulse shrink-0" />
                <span className="text-white/90 font-medium">
                  {connectorId === 'gmail'
                    ? 'Draft a quick reply to Sarah confirming tomorrow’s design review'
                    : connectorId === 'google_calendar'
                    ? 'What does my schedule look like this afternoon?'
                    : `Help me manage my tasks with ${connector?.name || 'NEXUS'}`}
                </span>
              </div>

              {/* Mockup Result Card */}
              <div className="p-2.5 rounded-lg bg-white/[0.03] border border-white/[0.06] text-[11px] text-white/70 space-y-1.5">
                <div className="flex items-center justify-between text-white/40 text-[10px]">
                  <span className="flex items-center gap-1.5">
                    {connectorId === 'gmail' ? <Mail className="w-3 h-3 text-sky-400" /> : <Calendar className="w-3 h-3 text-sky-400" />}
                    <span>{connectorId === 'gmail' ? 'Gmail Draft Ready' : 'Calendar Overview'}</span>
                  </span>
                  <span className="px-1.5 py-0.5 rounded bg-amber-500/15 text-amber-300 border border-amber-500/20 font-mono text-[9px]">
                    Requires Approval
                  </span>
                </div>
                <p className="text-white/80 italic text-[11.5px] leading-relaxed">
                  {connectorId === 'gmail'
                    ? '"Hey Sarah, sounds great! Let’s meet at 10 AM as planned. I’ll share the updated Figma beforehand."'
                    : '2 events scheduled: 1:30 PM Product Sync • 3:00 PM Design Review'}
                </p>
              </div>
            </div>

            {/* Simple Value Points */}
            <div className="pt-2 space-y-3">
              <div className="flex items-start gap-3 text-xs">
                <div className="w-5 h-5 rounded-md bg-white/[0.04] border border-white/[0.06] flex items-center justify-center shrink-0 mt-0.5 text-white/80">
                  ✓
                </div>
                <div>
                  <h4 className="font-medium text-white/90">Hands-free productivity</h4>
                  <p className="text-white/50 text-[11px] mt-0.5 leading-relaxed">
                    Ask Spotlight to draft messages or look up info without opening new browser tabs.
                  </p>
                </div>
              </div>

              <div className="flex items-start gap-3 text-xs">
                <div className="w-5 h-5 rounded-md bg-white/[0.04] border border-white/[0.06] flex items-center justify-center shrink-0 mt-0.5 text-white/80">
                  ✓
                </div>
                <div>
                  <h4 className="font-medium text-white/90">You are always in control</h4>
                  <p className="text-white/50 text-[11px] mt-0.5 leading-relaxed">
                    NEXUS always shows you the drafted content and asks before sending or mutating anything.
                  </p>
                </div>
              </div>

              <div className="flex items-start gap-3 text-xs">
                <div className="w-5 h-5 rounded-md bg-white/[0.04] border border-white/[0.06] flex items-center justify-center shrink-0 mt-0.5 text-white/80">
                  ✓
                </div>
                <div>
                  <h4 className="font-medium text-white/90">Private & local</h4>
                  <p className="text-white/50 text-[11px] mt-0.5 leading-relaxed">
                    Direct integration with Google APIs. Your data never passes through intermediate servers.
                  </p>
                </div>
              </div>
            </div>
          </div>
        </div>
      </main>

      {/* Simple Clean Footer (Centered Container) */}
      <footer className="w-full max-w-5xl flex items-center justify-between text-xs text-white/30 z-10 pt-8 border-t border-white/[0.05]">
        <span>Official Google OAuth 2.0</span>
        <span>Secure Local Connection</span>
      </footer>
    </div>
  );
};
