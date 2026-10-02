import { initializeApp, getApps, getApp } from "firebase/app";
import { getAuth, GoogleAuthProvider } from "firebase/auth";

export const firebaseConfig = {
  apiKey: "AIzaSyDhvfOHHQ-5MLX5lEzNdF5qEHJLteie9bI",
  authDomain: "nexus-9290d.firebaseapp.com",
  projectId: "nexus-9290d",
  storageBucket: "nexus-9290d.firebasestorage.app",
  messagingSenderId: "963333825219",
  appId: "1:963333825219:web:f575ea3225ca330f7eb876",
};

// Initialize Firebase app singleton
export const app = getApps().length > 0 ? getApp() : initializeApp(firebaseConfig);

// Initialize Firebase Auth
export const auth = getAuth(app);

// Google Auth Provider configured with prompt selection
export const googleProvider = new GoogleAuthProvider();
googleProvider.setCustomParameters({
  prompt: "select_account",
});
