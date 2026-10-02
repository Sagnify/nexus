import React, { useState, useEffect } from "react";
import { useAuth } from "../context/AuthContext";
import { auth } from "../config/firebase";
import { sendPasswordResetEmail } from "firebase/auth";
import { NexusSphere } from "./NexusSphere";
import { UserAvatar } from "./UserAvatar";
import nexusLogo from "../assets/nexus-logo.png";
import {
  CheckCircle,
  AlertCircle,
  User as UserIcon,
  Mail,
  Lock,
  Eye,
  EyeOff,
  Copy,
  Check,
  CheckCircle2,
  RefreshCw,
  Laptop,
  ChevronRight,
  ShieldCheck,
  ArrowRight,
  Command,
} from "lucide-react";

export const AuthPage: React.FC = () => {
  const {
    user,
    loginWithGoogle,
    signInWithEmail,
    signUpWithEmail,
    logout,
    loading: authLoading,
  } = useAuth();

  const [mode, setMode] = useState<"signin" | "signup" | "forgot">("signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [infoMessage, setInfoMessage] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [copiedUid, setCopiedUid] = useState(false);
  const [syncedWithDesktop, setSyncedWithDesktop] = useState(false);
  const [syncRetries, setSyncRetries] = useState(0);

  useEffect(() => {
    // Override #root style for full-screen auth page
    const root = document.getElementById("root");
    const body = document.body;
    const html = document.documentElement;

    if (root) {
      root.style.minHeight = "100vh";
      root.style.height = "100%";
      root.style.alignItems = "stretch";
      root.style.width = "100%";
      root.style.overflow = "auto";
      root.style.background = "#000000";
    }
    if (body) {
      body.style.overflow = "auto";
      body.style.background = "#000000";
    }
    if (html) {
      html.style.overflow = "auto";
      html.style.background = "#000000";
    }

    return () => {
      if (root) {
        root.style.minHeight = "";
        root.style.height = "";
        root.style.alignItems = "";
        root.style.width = "";
        root.style.overflow = "";
      }
    };
  }, []);

  // When user is authenticated, sync session to local backend so desktop daemon picks it up
  useEffect(() => {
    if (!user) {
      setSyncedWithDesktop(false);
      return;
    }
    let isMounted = true;

    const syncSession = async () => {
      try {
        const token = await user.getIdToken();
        const res = await fetch("http://127.0.0.1:8000/api/auth/session", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            id_token: token,
            firebase_uid: user.uid,
            email: user.email,
            display_name: user.displayName,
            profile_image_url: user.photoURL,
          }),
        });
        if (res.ok && isMounted) {
          setSyncedWithDesktop(true);
        } else if (isMounted && syncRetries < 3) {
          setTimeout(() => {
            if (isMounted) setSyncRetries((r) => r + 1);
          }, 2000);
        }
      } catch (err) {
        console.error("Failed to sync session with desktop:", err);
        if (isMounted && syncRetries < 3) {
          setTimeout(() => {
            if (isMounted) setSyncRetries((r) => r + 1);
          }, 3000);
        }
      }
    };

    syncSession();

    return () => {
      isMounted = false;
    };
  }, [user, syncRetries]);

  // Compute password strength score (0 to 4)
  const getPasswordStrength = (pass: string) => {
    if (!pass) return 0;
    let score = 0;
    if (pass.length >= 6) score += 1;
    if (pass.length >= 10) score += 1;
    if (/[0-9]/.test(pass)) score += 1;
    if (/[^A-Za-z0-9]/.test(pass)) score += 1;
    return score;
  };

  const passwordStrength = getPasswordStrength(password);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setInfoMessage(null);
    setSubmitting(true);

    try {
      if (mode === "signin") {
        await signInWithEmail(email, password);
      } else if (mode === "signup") {
        if (!name.trim()) {
          setError("Please enter your full name.");
          setSubmitting(false);
          return;
        }
        if (password.length < 6) {
          setError("Password must be at least 6 characters long.");
          setSubmitting(false);
          return;
        }
        await signUpWithEmail(email, password, name.trim());
      } else if (mode === "forgot") {
        if (!email.trim()) {
          setError("Please enter your email address.");
          setSubmitting(false);
          return;
        }
        await sendPasswordResetEmail(auth, email.trim());
        setInfoMessage("Password reset email sent! Please check your inbox and spam folder.");
      }
    } catch (err: any) {
      let msg = err.message || "Authentication failed";
      if (err.code === "auth/invalid-credential" || err.code === "auth/wrong-password") {
        msg = "Invalid email or password. Please verify and try again.";
      } else if (err.code === "auth/user-not-found") {
        msg = "No account found with this email address.";
      } else if (err.code === "auth/email-already-in-use") {
        msg = "An account with this email address already exists. Please sign in instead.";
      } else if (err.code === "auth/weak-password") {
        msg = "Password should be at least 6 characters.";
      } else if (err.code === "auth/invalid-email") {
        msg = "Please enter a valid email address.";
      } else if (err.code === "auth/too-many-requests") {
        msg = "Access temporarily disabled due to many failed attempts. Try again later.";
      }
      setError(msg);
    } finally {
      setSubmitting(false);
    }
  };

  const handleGoogleLogin = async () => {
    setError(null);
    setInfoMessage(null);
    setSubmitting(true);
    try {
      await loginWithGoogle();
    } catch (err: any) {
      if (err.code !== "auth/popup-closed-by-user") {
        setError(err.message || "Failed to sign in with Google.");
      }
    } finally {
      setSubmitting(false);
    }
  };

  const copyUidToClipboard = () => {
    if (user?.uid) {
      navigator.clipboard.writeText(user.uid);
      setCopiedUid(true);
      setTimeout(() => setCopiedUid(false), 2000);
    }
  };

  return (
    <div className="min-h-screen w-full bg-black text-white relative overflow-x-hidden selection:bg-blue-500/30 selection:text-blue-200 font-sans flex flex-col justify-between">
      {/* Background Lighting & Radial Glow */}
      <div className="fixed inset-0 pointer-events-none overflow-hidden z-0">
        {/* Subtle radial ambient spotlight */}
        <div className="absolute top-[-10%] left-1/2 -translate-x-1/2 w-[800px] h-[550px] bg-[radial-gradient(circle_at_50%_25%,rgba(41,121,255,0.14),transparent_70%)] blur-[100px]" />
        <div className="absolute bottom-[-10%] right-[-5%] w-[600px] h-[500px] bg-[radial-gradient(circle_at_50%_50%,rgba(37,99,235,0.08),transparent_70%)] blur-[120px]" />
        {/* Subtle dot matrix */}
        <div
          className="absolute inset-0 opacity-[0.035]"
          style={{
            backgroundImage: `radial-gradient(circle, #ffffff 1px, transparent 1px)`,
            backgroundSize: "32px 32px",
          }}
        />
      </div>

      {/* Floating Capsule Top Navbar (Same as Nexus-AI-main) */}
      <header className="fixed top-6 left-1/2 -translate-x-1/2 z-30 flex items-center justify-between px-6 py-3 backdrop-blur-md rounded-full border border-[#333] bg-[#1f1f1f57] w-[calc(100%-2rem)] max-w-5xl shadow-2xl transition-all">
        {/* Authentic NEXUS Ribbon Logo */}
        <div className="flex items-center gap-3">
          <div className="relative w-7 h-7 flex items-center justify-center group">
            <img
              src={nexusLogo}
              alt="NEXUS"
              className="w-7 h-7 object-contain drop-shadow-[0_0_10px_rgba(56,189,248,0.7)] transition-transform duration-300 group-hover:scale-110"
            />
          </div>
          <span className="font-bold text-sm tracking-widest text-transparent bg-clip-text bg-gradient-to-r from-cyan-400 via-sky-300 to-fuchsia-400">
            N.E.X.U.S.
          </span>
          <span className="hidden sm:inline-block font-mono text-[10px] uppercase tracking-[0.25em] text-blue-300 px-2.5 py-0.5 rounded-full border border-blue-500/20 bg-blue-500/10">
            Desktop Auth
          </span>
        </div>

        {/* Status Indicators */}
        <div className="flex items-center gap-3">
          <div className="hidden sm:flex items-center gap-2 px-3 py-1.5 rounded-full border border-[#333] bg-[rgba(31,31,31,0.62)] text-xs text-gray-300">
            <span className="relative flex h-2 w-2">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
              <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500" />
            </span>
            <span className="font-mono text-[11px] text-gray-300">Local Daemon: 127.0.0.1:8000</span>
          </div>

          <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-full border border-[#333] bg-[rgba(31,31,31,0.62)] text-[11px] text-gray-300 font-mono">
            <Command className="w-3 h-3 text-blue-400" />
            <span>Alt + N</span>
          </div>
        </div>
      </header>

      {/* Main Content Area */}
      <main className="relative z-10 w-full max-w-7xl mx-auto px-4 sm:px-6 pt-28 sm:pt-32 pb-12 flex-1 flex items-center justify-center">
        <div className="w-full grid grid-cols-1 lg:grid-cols-12 gap-10 lg:gap-14 items-center">
          
          {/* Left Column: Brand Hero & Interactive NexusSphere */}
          <div className="lg:col-span-6 xl:col-span-7 flex flex-col justify-center space-y-7 order-2 lg:order-1">
            <div className="space-y-4">
              <div className="inline-flex items-center gap-2 px-3.5 py-1.5 rounded-full border border-blue-500/30 bg-blue-500/10 text-blue-300 text-xs font-mono uppercase tracking-[0.28em]">
                <img src={nexusLogo} alt="" className="w-3.5 h-3.5 object-contain drop-shadow-[0_0_6px_rgba(56,189,248,0.8)]" />
                <span>N.E.X.U.S. DESKTOP</span>
              </div>

              <h1 className="text-3xl sm:text-4xl xl:text-5xl font-bold text-white bg-gradient-to-b from-neutral-50 to-neutral-400 bg-clip-text text-transparent leading-[1.18]">
                N.E.X.U.S. An AI That Learns What To Do
              </h1>

              <p className="text-sm sm:text-base text-neutral-300 leading-relaxed max-w-xl">
                N.E.X.U.S. observes how work gets done, discovers repetitive workflows, and turns approved intent into verified, adaptive digital action.
              </p>

              <div className="flex flex-col sm:flex-row items-start sm:items-center gap-3 sm:gap-6 text-xs sm:text-sm text-neutral-400 pt-1">
                <div className="flex items-center gap-2">
                  <CheckCircle className="h-4 w-4 text-emerald-400 flex-shrink-0" />
                  <span>Human approval by design</span>
                </div>
                <div className="flex items-center gap-2">
                  <CheckCircle className="h-4 w-4 text-emerald-400 flex-shrink-0" />
                  <span>Adaptive execution</span>
                </div>
                <div className="flex items-center gap-2">
                  <CheckCircle className="h-4 w-4 text-emerald-400 flex-shrink-0" />
                  <span>Verified outcomes</span>
                </div>
              </div>
            </div>

            {/* Interactive Nexus Execution Sphere (from Nexus-AI-main) */}
            <div className="pt-2">
              <NexusSphere />
            </div>

            {/* Feature Value Grid */}
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 pt-1">
              <div className="p-4 rounded-2xl border border-white/10 bg-white/[0.04] transition-colors hover:border-blue-400/50 hover:bg-white/[0.07]">
                <h2 className="text-xs font-semibold text-white">Local-First Speed</h2>
                <p className="text-[11px] text-neutral-400 mt-1 leading-snug">
                  Native IPC handshake directly with your machine's filesystem.
                </p>
              </div>

              <div className="p-4 rounded-2xl border border-white/10 bg-white/[0.04] transition-colors hover:border-blue-400/50 hover:bg-white/[0.07]">
                <h2 className="text-xs font-semibold text-white">Guarded Privacy</h2>
                <p className="text-[11px] text-neutral-400 mt-1 leading-snug">
                  Zero raw file scanning or untrusted telemetry sent to third parties.
                </p>
              </div>

              <div className="p-4 rounded-2xl border border-white/10 bg-white/[0.04] transition-colors hover:border-blue-400/50 hover:bg-white/[0.07]">
                <h2 className="text-xs font-semibold text-white">Cloud PostgreSQL</h2>
                <p className="text-[11px] text-neutral-400 mt-1 leading-snug">
                  Unified cloud sync across all your desktop workstations.
                </p>
              </div>
            </div>
          </div>

          {/* Right Column: Sleek Auth Console */}
          <div className="lg:col-span-6 xl:col-span-5 w-full max-w-md mx-auto order-1 lg:order-2">
            <div className="relative">
              {/* Outer Blue Glow */}
              <div className="absolute -inset-1 bg-gradient-to-b from-blue-500/25 via-blue-600/10 to-transparent rounded-[28px] blur-xl opacity-60 pointer-events-none" />

              {/* Glass Card Container */}
              <div className="relative rounded-3xl border border-white/10 bg-black/[0.90] backdrop-blur-2xl p-7 sm:p-9 shadow-2xl">
                {user ? (
                  /* ================= LOGGED IN SUCCESS VIEW ================= */
                  <div className="flex flex-col items-center text-center space-y-6 py-2">
                    {/* Glowing Avatar */}
                    <div className="relative group">
                      <div className="absolute -inset-2 bg-gradient-to-r from-blue-400 to-blue-600 rounded-full blur-md opacity-60 animate-pulse" />
                      <UserAvatar
                        src={user.photoURL}
                        name={user.displayName}
                        email={user.email}
                        size={96}
                        className="relative border-2 border-blue-400/90 shadow-2xl"
                      />
                      <div className="absolute bottom-0 right-0 w-7 h-7 rounded-full bg-emerald-500 flex items-center justify-center text-white ring-4 ring-black shadow-lg">
                        <Check className="w-4 h-4 stroke-[3]" />
                      </div>
                    </div>

                    <div className="space-y-1">
                      <div className="inline-flex items-center gap-1.5 px-3 py-0.5 rounded-full bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 text-[11px] font-mono font-medium mb-1">
                        <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
                        AUTHENTICATED
                      </div>
                      <h2 className="text-2xl font-bold text-white tracking-tight">
                        {user.displayName ? `Welcome, ${user.displayName}` : "Welcome to N.E.X.U.S."}
                      </h2>
                      <p className="text-xs text-neutral-400 font-mono">{user.email}</p>
                    </div>

                    {/* UID Pill with Copy */}
                    <div className="w-full flex items-center justify-between px-3.5 py-2.5 rounded-xl border border-white/10 bg-white/[0.03] text-xs">
                      <div className="flex items-center gap-2 overflow-hidden">
                        <UserIcon className="w-3.5 h-3.5 text-neutral-400 flex-shrink-0" />
                        <span className="text-[11px] text-neutral-400 font-mono truncate">
                          UID: {user.uid}
                        </span>
                      </div>
                      <button
                        type="button"
                        onClick={copyUidToClipboard}
                        className="text-[10px] font-mono px-2.5 py-1 rounded-full border border-white/10 bg-white/[0.06] hover:bg-white/[0.12] text-neutral-300 hover:text-white transition flex items-center gap-1 flex-shrink-0"
                        title="Copy UID"
                      >
                        {copiedUid ? (
                          <>
                            <Check className="w-3 h-3 text-emerald-400" />
                            <span className="text-emerald-400">Copied</span>
                          </>
                        ) : (
                          <>
                            <Copy className="w-3 h-3 text-neutral-400" />
                            <span>Copy</span>
                          </>
                        )}
                      </button>
                    </div>

                    {/* Desktop Daemon Sync Status Card */}
                    <div
                      className={`w-full p-4 rounded-2xl border transition-all text-left flex items-start gap-3.5 ${
                        syncedWithDesktop
                          ? "bg-blue-950/20 border-blue-500/30 shadow-lg shadow-blue-950/20"
                          : "bg-amber-950/20 border-amber-500/20"
                      }`}
                    >
                      <div
                        className={`w-9 h-9 rounded-xl flex items-center justify-center flex-shrink-0 ${
                          syncedWithDesktop
                            ? "bg-blue-500/20 text-blue-400"
                            : "bg-amber-500/20 text-amber-400 animate-spin"
                        }`}
                      >
                        {syncedWithDesktop ? (
                          <CheckCircle2 className="w-5 h-5 text-blue-400" />
                        ) : (
                          <RefreshCw className="w-5 h-5 text-amber-400" />
                        )}
                      </div>
                      <div className="space-y-0.5">
                        <p
                          className={`text-xs font-semibold ${
                            syncedWithDesktop ? "text-blue-300" : "text-amber-300"
                          }`}
                        >
                          {syncedWithDesktop
                            ? "Desktop App Synced Successfully"
                            : "Connecting to Local Desktop App..."}
                        </p>
                        <p className="text-[11px] text-neutral-400 leading-relaxed">
                          {syncedWithDesktop
                            ? "Your session credentials have been transferred to the NEXUS background daemon. You can now return to the app."
                            : "Establishing secure token handshake with the background bridge on localhost:8000."}
                        </p>
                      </div>
                    </div>

                    {/* Action Controls */}
                    <div className="w-full space-y-2.5 pt-1">
                      <div className="p-3 rounded-xl border border-white/10 bg-white/[0.03] flex items-center justify-between text-xs text-neutral-200">
                        <span className="flex items-center gap-2">
                          <Laptop className="w-4 h-4 text-blue-400" />
                          <span>Summon Spotlight</span>
                        </span>
                        <kbd className="px-2.5 py-0.5 rounded bg-black/60 border border-white/20 font-mono text-[11px] text-white font-bold">
                          Alt + N
                        </kbd>
                      </div>

                      <button
                        type="button"
                        onClick={() => window.close()}
                        className="w-full py-3 px-4 rounded-full border border-white/20 bg-white/5 hover:bg-white/10 hover:border-blue-400 text-white text-xs font-semibold transition-all shadow-sm active:scale-[0.99] flex items-center justify-center gap-2"
                      >
                        <span>Close This Tab</span>
                        <ChevronRight className="w-4 h-4 text-white/50" />
                      </button>

                      <button
                        type="button"
                        onClick={() => logout()}
                        className="w-full text-center text-xs text-neutral-400 hover:text-white transition-colors py-2"
                      >
                        Sign Out or Switch Account
                      </button>
                    </div>
                  </div>
                ) : (
                  /* ================= AUTH FORM ================= */
                  <div className="space-y-5">
                    {/* Header Titles */}
                    <div className="text-center space-y-2">
                      <div className="flex justify-center mb-1">
                        <div className="relative p-2.5 rounded-2xl bg-white/[0.03] border border-white/10 shadow-[0_0_24px_rgba(56,189,248,0.2)]">
                          <img src={nexusLogo} alt="Nexus" className="w-10 h-10 object-contain drop-shadow-[0_0_12px_rgba(56,189,248,0.7)]" />
                        </div>
                      </div>
                      <h2 className="text-xl sm:text-2xl font-bold text-white tracking-tight">
                        {mode === "signin"
                          ? "Welcome to N.E.X.U.S."
                          : mode === "signup"
                          ? "Create N.E.X.U.S. Account"
                          : "Reset Password"}
                      </h2>
                      <p className="text-xs text-neutral-400">
                        {mode === "signin"
                          ? "Sign in to authenticate your desktop agent"
                          : mode === "signup"
                          ? "Get started with adaptive workflow execution"
                          : "Enter your email to receive recovery instructions"}
                      </p>
                    </div>

                    {/* Mode Selector (Pill tabs from Nexus-AI-main) */}
                    {mode !== "forgot" ? (
                      <div className="flex p-1 rounded-full border border-[#333] bg-[#1f1f1f57] relative">
                        <button
                          type="button"
                          onClick={() => {
                            setMode("signin");
                            setError(null);
                            setInfoMessage(null);
                          }}
                          className={`flex-1 py-2 text-xs font-medium rounded-full transition-all ${
                            mode === "signin"
                              ? "bg-gradient-to-br from-blue-400 to-blue-600 text-white font-semibold shadow-md"
                              : "text-neutral-400 hover:text-white"
                          }`}
                        >
                          Sign In
                        </button>
                        <button
                          type="button"
                          onClick={() => {
                            setMode("signup");
                            setError(null);
                            setInfoMessage(null);
                          }}
                          className={`flex-1 py-2 text-xs font-medium rounded-full transition-all ${
                            mode === "signup"
                              ? "bg-gradient-to-br from-blue-400 to-blue-600 text-white font-semibold shadow-md"
                              : "text-neutral-400 hover:text-white"
                          }`}
                        >
                          Create Account
                        </button>
                      </div>
                    ) : (
                      <div className="flex items-center justify-between pb-1">
                        <button
                          type="button"
                          onClick={() => {
                            setMode("signin");
                            setError(null);
                            setInfoMessage(null);
                          }}
                          className="text-xs text-blue-400 hover:text-blue-300 flex items-center gap-1 font-medium"
                        >
                          ← Back to Sign In
                        </button>
                      </div>
                    )}

                    {/* Google OAuth Button */}
                    {mode !== "forgot" && (
                      <>
                        <button
                          type="button"
                          onClick={handleGoogleLogin}
                          disabled={submitting || authLoading}
                          className="w-full relative group flex items-center justify-center gap-3 py-2.5 px-4 rounded-full border border-[#333] bg-[rgba(31,31,31,0.62)] hover:border-white/50 hover:bg-white/[0.08] text-neutral-200 hover:text-white text-xs font-medium transition-all shadow-sm disabled:opacity-50"
                        >
                          <svg className="w-4 h-4 flex-shrink-0" viewBox="0 0 24 24">
                            <path
                              fill="#4285F4"
                              d="M23.745 12.27c0-.7-.06-1.4-.19-2.07H12v4.51h6.6c-.29 1.52-1.14 2.82-2.4 3.68v3.05h3.88c2.27-2.09 3.66-5.17 3.66-9.17z"
                            />
                            <path
                              fill="#34A853"
                              d="M12 24c3.24 0 5.95-1.08 7.93-2.91l-3.88-3.05c-1.08.72-2.45 1.16-4.05 1.16-3.12 0-5.77-2.1-6.72-4.93H1.25v3.15C3.26 21.36 7.34 24 12 24z"
                            />
                            <path
                              fill="#FBBC05"
                              d="M5.28 14.27c-.25-.72-.38-1.49-.38-2.27s.13-1.55.38-2.27V6.58H1.25C.45 8.18 0 10.03 0 12s.45 3.82 1.25 5.42l4.03-3.15z"
                            />
                            <path
                              fill="#EA4335"
                              d="M12 4.75c1.77 0 3.35.61 4.6 1.8l3.42-3.42C17.95 1.19 15.24 0 12 0 7.34 0 3.26 2.64 1.25 6.58l4.03 3.15c.95-2.83 3.6-4.98 6.72-4.98z"
                            />
                          </svg>
                          <span>Continue with Google</span>
                        </button>

                        {/* Divider */}
                        <div className="relative flex items-center justify-center my-2">
                          <div className="w-full border-t border-white/10" />
                          <span className="absolute bg-black px-3 text-[10px] text-neutral-500 uppercase tracking-widest font-mono">
                            or with email
                          </span>
                        </div>
                      </>
                    )}

                    {/* Alerts / Error and Info Callouts */}
                    {error && (
                      <div className="p-3 rounded-xl bg-rose-500/10 border border-rose-500/25 text-rose-300 text-xs flex items-start gap-2.5 animate-fadeIn">
                        <AlertCircle className="w-4 h-4 flex-shrink-0 mt-0.5 text-rose-400" />
                        <span className="leading-snug">{error}</span>
                      </div>
                    )}

                    {infoMessage && (
                      <div className="p-3 rounded-xl bg-emerald-500/10 border border-emerald-500/25 text-emerald-300 text-xs flex items-start gap-2.5 animate-fadeIn">
                        <CheckCircle2 className="w-4 h-4 flex-shrink-0 mt-0.5 text-emerald-400" />
                        <span className="leading-snug">{infoMessage}</span>
                      </div>
                    )}

                    {/* Form Controls */}
                    <form onSubmit={handleSubmit} className="space-y-4">
                      {mode === "signup" && (
                        <div>
                          <label className="block text-[11px] font-mono uppercase tracking-wider text-neutral-400 mb-1.5">
                            Full Name
                          </label>
                          <div className="relative group">
                            <UserIcon className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-neutral-500 group-focus-within:text-blue-400 transition-colors" />
                            <input
                              type="text"
                              required
                              placeholder="Alex Parker"
                              value={name}
                              onChange={(e) => setName(e.target.value)}
                              className="w-full bg-white/[0.04] border border-white/10 rounded-xl pl-10 pr-3.5 py-2.5 text-xs text-white placeholder-neutral-500 focus:outline-none focus:border-blue-400 focus:ring-1 focus:ring-blue-400/40 transition-all"
                            />
                          </div>
                        </div>
                      )}

                      <div>
                        <label className="block text-[11px] font-mono uppercase tracking-wider text-neutral-400 mb-1.5">
                          Email Address
                        </label>
                        <div className="relative group">
                          <Mail className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-neutral-500 group-focus-within:text-blue-400 transition-colors" />
                          <input
                            type="email"
                            required
                            placeholder="name@example.com"
                            value={email}
                            onChange={(e) => setEmail(e.target.value)}
                            className="w-full bg-white/[0.04] border border-white/10 rounded-xl pl-10 pr-3.5 py-2.5 text-xs text-white placeholder-neutral-500 focus:outline-none focus:border-blue-400 focus:ring-1 focus:ring-blue-400/40 transition-all"
                          />
                        </div>
                      </div>

                      {mode !== "forgot" && (
                        <div>
                          <div className="flex items-center justify-between mb-1.5">
                            <label className="block text-[11px] font-mono uppercase tracking-wider text-neutral-400">
                              Password
                            </label>
                            {mode === "signin" && (
                              <button
                                type="button"
                                onClick={() => {
                                  setMode("forgot");
                                  setError(null);
                                  setInfoMessage(null);
                                }}
                                className="text-[11px] text-blue-400 hover:text-blue-300 transition-colors font-medium"
                              >
                                Forgot password?
                              </button>
                            )}
                          </div>
                          <div className="relative group">
                            <Lock className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-neutral-500 group-focus-within:text-blue-400 transition-colors" />
                            <input
                              type={showPassword ? "text" : "password"}
                              required
                              placeholder="••••••••••••"
                              value={password}
                              onChange={(e) => setPassword(e.target.value)}
                              className="w-full bg-white/[0.04] border border-white/10 rounded-xl pl-10 pr-10 py-2.5 text-xs text-white placeholder-neutral-500 focus:outline-none focus:border-blue-400 focus:ring-1 focus:ring-blue-400/40 transition-all"
                            />
                            <button
                              type="button"
                              onClick={() => setShowPassword(!showPassword)}
                              className="absolute right-3.5 top-1/2 -translate-y-1/2 text-neutral-400 hover:text-white transition-colors"
                              title={showPassword ? "Hide password" : "Show password"}
                            >
                              {showPassword ? (
                                <EyeOff className="w-4 h-4" />
                              ) : (
                                <Eye className="w-4 h-4" />
                              )}
                            </button>
                          </div>

                          {/* Password Strength Indicator (Signup Mode) */}
                          {mode === "signup" && password.length > 0 && (
                            <div className="mt-2 space-y-1.5">
                              <div className="flex items-center justify-between text-[10px] font-mono text-neutral-400">
                                <span>Password Strength</span>
                                <span
                                  className={
                                    passwordStrength <= 1
                                      ? "text-rose-400 font-semibold"
                                      : passwordStrength === 2
                                      ? "text-amber-400 font-semibold"
                                      : passwordStrength === 3
                                      ? "text-blue-400 font-semibold"
                                      : "text-emerald-400 font-semibold"
                                  }
                                >
                                  {passwordStrength <= 1
                                    ? "Weak"
                                    : passwordStrength === 2
                                    ? "Fair"
                                    : passwordStrength === 3
                                    ? "Good"
                                    : "Strong"}
                                </span>
                              </div>
                              <div className="grid grid-cols-4 gap-1.5 h-1">
                                {[1, 2, 3, 4].map((step) => (
                                  <div
                                    key={step}
                                    className={`rounded-full transition-all duration-300 ${
                                      passwordStrength >= step
                                        ? passwordStrength <= 1
                                          ? "bg-rose-500"
                                          : passwordStrength === 2
                                          ? "bg-amber-400"
                                          : passwordStrength === 3
                                          ? "bg-blue-400"
                                          : "bg-emerald-400"
                                        : "bg-white/10"
                                    }`}
                                  />
                                ))}
                              </div>
                            </div>
                          )}
                        </div>
                      )}

                      {/* Glowing Blue Capsule Action Button (from Nexus-AI-main) */}
                      <div className="relative group w-full mt-3">
                        <div className="absolute inset-0 -m-1 rounded-full bg-blue-400 opacity-40 filter blur-md pointer-events-none transition-all duration-300 ease-out group-hover:opacity-75 group-hover:blur-lg" />
                        <button
                          type="submit"
                          disabled={submitting || authLoading}
                          className="relative z-10 w-full inline-flex items-center justify-center gap-2 py-3 px-6 text-xs sm:text-sm font-semibold text-white bg-gradient-to-br from-blue-400 to-blue-600 rounded-full hover:from-blue-500 hover:to-blue-700 transition-all duration-200 active:scale-[0.99] disabled:opacity-50"
                        >
                          {submitting ? (
                            <div className="flex items-center gap-2">
                              <div className="w-3.5 h-3.5 border-2 border-white border-t-transparent rounded-full animate-spin" />
                              <span>Processing...</span>
                            </div>
                          ) : (
                            <>
                              <span>
                                {mode === "signin"
                                  ? "Sign In to N.E.X.U.S."
                                  : mode === "signup"
                                  ? "Create N.E.X.U.S. Account"
                                  : "Send Password Reset Link"}
                              </span>
                              <ArrowRight className="w-3.5 h-3.5 group-hover:translate-x-0.5 transition-transform" />
                            </>
                          )}
                        </button>
                      </div>
                    </form>

                    {/* Bottom Security Assurance */}
                    <div className="pt-2 text-center">
                      <p className="text-[10px] text-neutral-400 flex items-center justify-center gap-1.5">
                        <ShieldCheck className="w-3.5 h-3.5 text-blue-400" />
                        <span>Protected by Firebase Auth & Neon PostgreSQL</span>
                      </p>
                    </div>
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      </main>

      {/* Footer (Same as Nexus-AI-main) */}
      <footer className="relative z-20 w-full max-w-7xl mx-auto px-6 py-6 border-t border-white/10 flex flex-col sm:flex-row items-center justify-between gap-4 text-[11px] text-neutral-400">
        <div className="flex items-center gap-2">
          <span>© 2026 N.E.X.U.S. All rights reserved.</span>
          <span>•</span>
          <span className="text-neutral-400">Adaptive Execution Desktop Agent</span>
        </div>
        <div className="flex items-center gap-6 text-neutral-400">
          <span className="flex items-center gap-1.5">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
            Zero-Telemetry Local Execution
          </span>
          <span className="text-white/20">|</span>
          <span className="font-mono text-blue-300">Port 8000 Bridge Active</span>
        </div>
      </footer>
    </div>
  );
};
