import React, { useState } from "react";
import { useAuth } from "../context/AuthContext";
import { X, Mail, Lock, User, LogOut, CheckCircle, Database, ArrowRight } from "lucide-react";
import { UserAvatar } from "./UserAvatar";
import nexusLogo from "../assets/nexus-logo.png";

interface AuthModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export const AuthModal: React.FC<AuthModalProps> = ({ isOpen, onClose }) => {
  const {
    user,
    dbUser,
    loginWithGoogle,
    signInWithEmail,
    signUpWithEmail,
    logout,
    continueAsGuest,
    loading,
  } = useAuth();

  const [mode, setMode] = useState<"signin" | "signup">("signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  if (!isOpen) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      if (mode === "signin") {
        await signInWithEmail(email, password);
      } else {
        if (!name.trim()) {
          setError("Please enter your name");
          setSubmitting(false);
          return;
        }
        await signUpWithEmail(email, password, name.trim());
      }
      onClose();
    } catch (err: any) {
      let msg = err.message || "Authentication failed";
      if (err.code === "auth/invalid-credential" || err.code === "auth/wrong-password") {
        msg = "Invalid email or password.";
      } else if (err.code === "auth/email-already-in-use") {
        msg = "An account with this email already exists.";
      } else if (err.code === "auth/weak-password") {
        msg = "Password should be at least 6 characters.";
      } else if (err.code === "auth/invalid-email") {
        msg = "Please enter a valid email address.";
      }
      setError(msg);
    } finally {
      setSubmitting(false);
    }
  };

  const handleGoogleLogin = async () => {
    setError(null);
    setSubmitting(true);
    try {
      await loginWithGoogle();
      onClose();
    } catch (err: any) {
      if (err.code !== "auth/popup-closed-by-user") {
        setError(err.message || "Failed to sign in with Google");
      }
    } finally {
      setSubmitting(false);
    }
  };

  const handleGuest = () => {
    continueAsGuest();
    onClose();
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-md p-4 animate-fadeIn"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="relative w-full max-w-md overflow-hidden rounded-3xl border border-white/10 bg-black/[0.94] p-7 shadow-2xl backdrop-blur-2xl">
        {/* Ambient Top Glow */}
        <div className="absolute top-0 left-1/2 -translate-x-1/2 w-72 h-36 bg-blue-500/15 rounded-full blur-3xl pointer-events-none" />

        {/* Close Button */}
        <button
          onClick={onClose}
          className="absolute right-5 top-5 rounded-full p-1.5 text-neutral-400 hover:bg-white/10 hover:text-white transition-colors z-10"
        >
          <X className="h-4 w-4" />
        </button>

        {user ? (
          /* Profile / Logged In View */
          <div className="relative flex flex-col items-center text-center space-y-5 pt-2">
            <div className="relative group">
              <div className="absolute -inset-2 bg-gradient-to-r from-blue-400 to-blue-600 rounded-full blur-md opacity-60 animate-pulse" />
              <UserAvatar
                src={user.photoURL}
                name={user.displayName}
                email={user.email}
                size={80}
                className="relative border-2 border-blue-400/90 shadow-2xl"
              />
              <div className="absolute bottom-0 right-0 rounded-full bg-emerald-500 p-1 text-white ring-4 ring-black shadow">
                <CheckCircle className="h-3.5 w-3.5" />
              </div>
            </div>

            <div>
              <div className="inline-flex items-center gap-1.5 px-3 py-0.5 rounded-full bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 text-[10px] font-mono font-medium mb-1.5">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
                AUTHENTICATED
              </div>
              <h3 className="text-xl font-bold text-white">
                {user.displayName || "N.E.X.U.S. User"}
              </h3>
              <p className="text-xs text-neutral-400 font-mono mt-0.5">{user.email}</p>
            </div>

            {/* Neon DB Sync Status */}
            <div className="flex items-center space-x-2 rounded-xl border border-white/10 bg-white/[0.04] px-3.5 py-2 text-xs text-blue-300">
              <Database className="h-3.5 w-3.5 text-blue-400" />
              <span>
                {dbUser ? "Synced to Neon Cloud PostgreSQL" : "Local Daemon Active"}
              </span>
            </div>

            <div className="w-full pt-2">
              <button
                onClick={async () => {
                  await logout();
                  onClose();
                }}
                disabled={loading}
                className="flex w-full items-center justify-center space-x-2 rounded-full border border-rose-500/20 bg-rose-500/10 py-2.5 text-xs font-semibold text-rose-300 hover:bg-rose-500/20 transition-colors"
              >
                <LogOut className="h-4 w-4" />
                <span>Sign Out</span>
              </button>
            </div>
          </div>
        ) : (
          /* Sign In / Sign Up Form */
          <div className="relative space-y-5">
            {/* Authentic Brand Header */}
            <div className="flex flex-col items-center text-center space-y-2">
              <div className="relative p-2 rounded-2xl bg-white/[0.04] border border-white/10 shadow-[0_0_20px_rgba(56,189,248,0.25)] group">
                <img
                  src={nexusLogo}
                  alt="NEXUS"
                  className="w-9 h-9 object-contain drop-shadow-[0_0_12px_rgba(56,189,248,0.8)] transition-transform duration-300 group-hover:scale-105"
                />
              </div>
              <div className="flex items-center gap-2">
                <span className="font-bold text-sm tracking-[0.2em] text-transparent bg-clip-text bg-gradient-to-r from-cyan-400 via-sky-300 to-fuchsia-400">
                  N.E.X.U.S.
                </span>
              </div>
              <h2 className="text-xl font-bold text-white tracking-tight">
                {mode === "signin" ? "Welcome to N.E.X.U.S." : "Create N.E.X.U.S. Account"}
              </h2>
              <p className="text-xs text-neutral-400">
                Persist history, preferences, and models to Neon PostgreSQL
              </p>
            </div>

            {/* Mode Switcher Capsule (Nexus-AI-main) */}
            <div className="flex p-1 rounded-full border border-[#333] bg-[#1f1f1f57]">
              <button
                type="button"
                onClick={() => {
                  setMode("signin");
                  setError(null);
                }}
                className={`flex-1 py-1.5 text-xs font-medium rounded-full transition-all ${
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
                }}
                className={`flex-1 py-1.5 text-xs font-medium rounded-full transition-all ${
                  mode === "signup"
                    ? "bg-gradient-to-br from-blue-400 to-blue-600 text-white font-semibold shadow-md"
                    : "text-neutral-400 hover:text-white"
                }`}
              >
                Create Account
              </button>
            </div>

            {error && (
              <div className="rounded-xl border border-rose-500/25 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
                {error}
              </div>
            )}

            {/* Google OAuth Button */}
            <button
              type="button"
              onClick={handleGoogleLogin}
              disabled={submitting || loading}
              className="w-full flex items-center justify-center gap-3 py-2.5 px-4 rounded-full border border-[#333] bg-[rgba(31,31,31,0.62)] hover:border-white/50 hover:bg-white/[0.08] text-neutral-200 hover:text-white text-xs font-medium transition-all shadow-sm disabled:opacity-50"
            >
              <svg className="h-4 w-4" viewBox="0 0 24 24">
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

            {/* Form */}
            <form onSubmit={handleSubmit} className="space-y-3.5">
              {mode === "signup" && (
                <div>
                  <label className="block text-[11px] font-mono uppercase tracking-wider text-neutral-400 mb-1">
                    Full Name
                  </label>
                  <div className="relative group">
                    <User className="absolute left-3.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-neutral-500 group-focus-within:text-blue-400 transition-colors" />
                    <input
                      type="text"
                      required
                      placeholder="Alex Parker"
                      value={name}
                      onChange={(e) => setName(e.target.value)}
                      className="w-full bg-white/[0.04] border border-white/10 rounded-xl pl-9 pr-3.5 py-2 text-xs text-white placeholder-neutral-500 focus:outline-none focus:border-blue-400 focus:ring-1 focus:ring-blue-400/40 transition-all"
                    />
                  </div>
                </div>
              )}

              <div>
                <label className="block text-[11px] font-mono uppercase tracking-wider text-neutral-400 mb-1">
                  Email Address
                </label>
                <div className="relative group">
                  <Mail className="absolute left-3.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-neutral-500 group-focus-within:text-blue-400 transition-colors" />
                  <input
                    type="email"
                    required
                    placeholder="name@example.com"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    className="w-full bg-white/[0.04] border border-white/10 rounded-xl pl-9 pr-3.5 py-2 text-xs text-white placeholder-neutral-500 focus:outline-none focus:border-blue-400 focus:ring-1 focus:ring-blue-400/40 transition-all"
                  />
                </div>
              </div>

              <div>
                <label className="block text-[11px] font-mono uppercase tracking-wider text-neutral-400 mb-1">
                  Password
                </label>
                <div className="relative group">
                  <Lock className="absolute left-3.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-neutral-500 group-focus-within:text-blue-400 transition-colors" />
                  <input
                    type="password"
                    required
                    placeholder="••••••••••••"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    className="w-full bg-white/[0.04] border border-white/10 rounded-xl pl-9 pr-3.5 py-2 text-xs text-white placeholder-neutral-500 focus:outline-none focus:border-blue-400 focus:ring-1 focus:ring-blue-400/40 transition-all"
                  />
                </div>
              </div>

              {/* Glowing Blue Button */}
              <div className="relative group w-full pt-1">
                <div className="absolute inset-0 -m-1 rounded-full bg-blue-400 opacity-40 filter blur-md pointer-events-none transition-all duration-300 ease-out group-hover:opacity-75 group-hover:blur-lg" />
                <button
                  type="submit"
                  disabled={submitting || loading}
                  className="relative z-10 w-full inline-flex items-center justify-center gap-2 py-2.5 px-4 text-xs font-semibold text-white bg-gradient-to-br from-blue-400 to-blue-600 rounded-full hover:from-blue-500 hover:to-blue-700 transition-all duration-200 active:scale-[0.99] disabled:opacity-50"
                >
                  {submitting ? (
                    <div className="flex items-center gap-2">
                      <div className="w-3.5 h-3.5 border-2 border-white border-t-transparent rounded-full animate-spin" />
                      <span>Processing...</span>
                    </div>
                  ) : (
                    <>
                      <span>{mode === "signin" ? "Sign In to N.E.X.U.S." : "Create Account"}</span>
                      <ArrowRight className="h-3.5 w-3.5" />
                    </>
                  )}
                </button>
              </div>
            </form>

            {/* Guest Option */}
            <div className="pt-2 text-center">
              <button
                type="button"
                onClick={handleGuest}
                className="text-xs text-neutral-400 hover:text-white transition-colors"
              >
                Continue as Guest (Local Offline Only)
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
