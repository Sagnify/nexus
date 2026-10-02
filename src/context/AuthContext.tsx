import React, { createContext, useContext, useEffect, useState, useCallback } from "react";
import {
  User as FirebaseUser,
  onAuthStateChanged,
  signInWithPopup,
  signInWithRedirect,
  getRedirectResult,
  signInWithEmailAndPassword,
  createUserWithEmailAndPassword,
  updateProfile,
  signOut,
} from "firebase/auth";
import { auth, googleProvider } from "../config/firebase";

export interface NexusUser {
  id: string;
  firebase_uid: string;
  email: string | null;
  display_name: string | null;
  profile_image_url: string | null;
  created_at: string;
}

interface AuthContextType {
  user: FirebaseUser | null;
  dbUser: NexusUser | null;
  idToken: string | null;
  loading: boolean;
  isGuest: boolean;
  loginWithGoogle: () => Promise<void>;
  signInWithEmail: (email: string, pass: string) => Promise<void>;
  signUpWithEmail: (email: string, pass: string, name?: string) => Promise<void>;
  logout: () => Promise<void>;
  continueAsGuest: () => void;
  refreshUser: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType | null>(null);

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [user, setUser] = useState<any>(() => {
    try {
      const cached = localStorage.getItem("nexus_desktop_auth");
      return cached ? JSON.parse(cached).user : null;
    } catch {
      return null;
    }
  });
  const [dbUser, setDbUser] = useState<NexusUser | null>(() => {
    try {
      const cached = localStorage.getItem("nexus_desktop_auth");
      return cached ? JSON.parse(cached).user : null;
    } catch {
      return null;
    }
  });
  // Bootstrap desktop requests from the cached token; Firebase auth replaces it
  // with a fresh token on mount when a Firebase user is available. The backend
  // still verifies expiry/signature on every request and rejects stale tokens.
  const [idToken, setIdToken] = useState<string | null>(() => {
    try {
      return localStorage.getItem("nexus_desktop_auth")
        ? JSON.parse(localStorage.getItem("nexus_desktop_auth") || "{}").id_token || null
        : null;
    } catch {
      return null;
    }
  });
  const [loading, setLoading] = useState<boolean>(true);
  const [isGuest, setIsGuest] = useState<boolean>(() => {
    return localStorage.getItem("nexus_guest_mode") === "true";
  });
  const activeAuthUserId = user?.uid ?? user?.firebase_uid ?? null;

  useEffect(() => {
    if (idToken || !activeAuthUserId) return;
    try {
      const cached = JSON.parse(localStorage.getItem("nexus_desktop_auth") || "{}");
      const cachedUid = cached.user?.firebase_uid ?? cached.user?.uid;
      if (cached.id_token && cachedUid === activeAuthUserId) {
        setIdToken(cached.id_token);
      }
    } catch {
      // Ignore malformed cached desktop auth data.
    }
  }, [activeAuthUserId, idToken]);

  const syncWithBackend = useCallback(async (token: string): Promise<NexusUser | null> => {
    try {
      const res = await fetch("http://127.0.0.1:8000/api/auth/verify", {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ id_token: token }),
      });
      if (res.ok) {
        const data = await res.json();
        return data.user as NexusUser;
      }
    } catch {
      // Backend may be offline or local-only; fail silently
    }
    return null;
  }, []);

  // Poll backend for browser login session if running desktop app and unauthenticated
  useEffect(() => {
    let cancelled = false;
    const checkBackendSession = async () => {
      try {
        const res = await fetch("http://127.0.0.1:8000/api/auth/session");
        if (res.ok && !cancelled) {
          const data = await res.json();
          if (data.session && data.session.user) {
            const u = data.session.user;
            // Prefer a fresh Firebase token over the potentially stale stored one
            let freshToken = data.session.id_token;
            if (auth.currentUser) {
              try {
                freshToken = await auth.currentUser.getIdToken();
              } catch {}
            }
            const normalizedUser = {
              uid: u.firebase_uid,
              email: u.email,
              displayName: u.display_name,
              photoURL: u.profile_image_url,
              getIdToken: async (forceRefresh?: boolean) => {
                if (auth.currentUser) {
                  try {
                    const t = await auth.currentUser.getIdToken(forceRefresh);
                    if (t) {
                      setIdToken(t);
                      return t;
                    }
                  } catch {}
                }
                return freshToken;
              },
            };
            setUser(normalizedUser);
            setDbUser(u);
            setIdToken(freshToken);
            setIsGuest(false);
            localStorage.setItem("nexus_desktop_auth", JSON.stringify({ ...data.session, id_token: freshToken }));
          } else if (!data.session) {
            // Restore backend session if server restarted but desktop localStorage has credentials
            try {
              const cached = JSON.parse(localStorage.getItem("nexus_desktop_auth") || "{}");
              const cachedUser = cached?.user;
              const cachedToken = cached?.id_token;
              if (cachedUser && cachedToken) {
                await fetch("http://127.0.0.1:8000/api/auth/session", {
                  method: "POST",
                  headers: { "Content-Type": "application/json" },
                  body: JSON.stringify({
                    id_token: cachedToken,
                    firebase_uid: cachedUser.firebase_uid || cachedUser.uid,
                    email: cachedUser.email,
                    display_name: cachedUser.display_name || cachedUser.displayName,
                    profile_image_url: cachedUser.profile_image_url || cachedUser.photoURL,
                  }),
                });
              }
            } catch {}
          }
        }
      } catch {}
    };

    checkBackendSession();

    const interval = setInterval(() => {
          if (!activeAuthUserId) {
        checkBackendSession();
      }
    }, 15000);

    const handleFocus = () => checkBackendSession();
    window.addEventListener("focus", handleFocus);
    const unsubShow = (window as any).electronAPI?.onWindowShow?.(checkBackendSession);

    return () => {
      cancelled = true;
      clearInterval(interval);
      window.removeEventListener("focus", handleFocus);
      if (unsubShow) unsubShow();
    };
  }, [activeAuthUserId]);

  useEffect(() => {
    const unsubscribe = onAuthStateChanged(auth, async (fbUser) => {
      if (fbUser) {
        setUser(fbUser);
        setIsGuest(false);
        localStorage.removeItem("nexus_guest_mode");
        try {
          const token = await fbUser.getIdToken();
          setIdToken(token);
          const synced = await syncWithBackend(token);
          if (synced) {
            setDbUser(synced);
            localStorage.setItem("nexus_desktop_auth", JSON.stringify({ user: synced, id_token: token }));
          }
        } catch (err) {
          console.error("Failed to retrieve token:", err);
        }
      } else {
        const cached = localStorage.getItem("nexus_desktop_auth");
        if (!cached) {
          setIdToken(null);
          setDbUser(null);
          setUser(null);
        }
      }
      setLoading(false);
    });

    // Handle return from in-tab redirect
    getRedirectResult(auth)
      .then(async (result) => {
        if (!result) return;
        const token = await result.user.getIdToken();
        setIdToken(token);
        const synced = await syncWithBackend(token);
        if (synced) {
          setDbUser(synced);
          localStorage.setItem("nexus_desktop_auth", JSON.stringify({ user: synced, id_token: token }));
        }
        setIsGuest(false);
        localStorage.removeItem("nexus_guest_mode");
      })
      .catch((err) => {
        console.warn("getRedirectResult in AuthContext:", err);
      });

    return () => unsubscribe();
  }, [syncWithBackend]);

  const loginWithGoogle = async () => {
    setLoading(true);
    try {
      const result = await signInWithPopup(auth, googleProvider);
      const token = await result.user.getIdToken();
      setIdToken(token);
      const synced = await syncWithBackend(token);
      if (synced) {
        setDbUser(synced);
        localStorage.setItem("nexus_desktop_auth", JSON.stringify({ user: synced, id_token: token }));
      }
      setIsGuest(false);
      localStorage.removeItem("nexus_guest_mode");
    } catch (err: any) {
      if (err.code === "auth/popup-blocked") {
        console.warn("Popup blocked, falling back to seamless redirect...");
        await signInWithRedirect(auth, googleProvider);
        return;
      }
      throw err;
    } finally {
      setLoading(false);
    }
  };

  const signInWithEmail = async (email: string, pass: string) => {
    setLoading(true);
    try {
      const result = await signInWithEmailAndPassword(auth, email, pass);
      const token = await result.user.getIdToken();
      setIdToken(token);
      const synced = await syncWithBackend(token);
      if (synced) {
        setDbUser(synced);
        localStorage.setItem("nexus_desktop_auth", JSON.stringify({ user: synced, id_token: token }));
      }
      setIsGuest(false);
      localStorage.removeItem("nexus_guest_mode");
    } finally {
      setLoading(false);
    }
  };

  const signUpWithEmail = async (email: string, pass: string, name?: string) => {
    setLoading(true);
    try {
      const result = await createUserWithEmailAndPassword(auth, email, pass);
      if (name && auth.currentUser) {
        await updateProfile(auth.currentUser, { displayName: name });
      }
      const token = await result.user.getIdToken();
      setIdToken(token);
      const synced = await syncWithBackend(token);
      if (synced) {
        setDbUser(synced);
        localStorage.setItem("nexus_desktop_auth", JSON.stringify({ user: synced, id_token: token }));
      }
      setIsGuest(false);
      localStorage.removeItem("nexus_guest_mode");
    } finally {
      setLoading(false);
    }
  };

  const logout = async () => {
    setLoading(true);
    try {
      await signOut(auth);
      localStorage.removeItem("nexus_desktop_auth");
      fetch("http://127.0.0.1:8000/api/auth/logout", { method: "POST" }).catch(() => {});
      setUser(null);
      setDbUser(null);
      setIdToken(null);
      setIsGuest(false);
      localStorage.removeItem("nexus_guest_mode");
    } finally {
      setLoading(false);
    }
  };

  const continueAsGuest = () => {
    setIsGuest(true);
    localStorage.setItem("nexus_guest_mode", "true");
  };

  const refreshUser = async () => {
    if (auth.currentUser) {
      const token = await auth.currentUser.getIdToken(true);
      setIdToken(token);
      const synced = await syncWithBackend(token);
      if (synced) setDbUser(synced);
    }
  };

  return (
    <AuthContext.Provider
      value={{
        user,
        dbUser,
        idToken,
        loading,
        isGuest,
        loginWithGoogle,
        signInWithEmail,
        signUpWithEmail,
        logout,
        continueAsGuest,
        refreshUser,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
};
