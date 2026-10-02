import React, { useState, useEffect } from "react";
import { User } from "lucide-react";

interface UserAvatarProps {
  src?: string | null;
  name?: string | null;
  email?: string | null;
  className?: string;
  size?: number; // size in px, default 24
}

/**
 * Robust, premium user avatar component.
 * Handles Google/Firebase OAuth photo URLs in Electron/Chromium by enforcing
 * referrerPolicy="no-referrer" (which prevents 403s on lh3.googleusercontent.com),
 * and automatically falls back to branded initial badges on load error or missing image.
 */
export const UserAvatar: React.FC<UserAvatarProps> = ({
  src,
  name,
  email,
  className = "",
  size = 24,
}) => {
  const [imageFailed, setImageFailed] = useState(false);

  // Reset error state if the src URL changes
  useEffect(() => {
    setImageFailed(false);
  }, [src]);

  // Compute initials: e.g. "Sagnik Chakraborty" -> "SC", "sagnify" -> "S"
  const getInitials = () => {
    const raw = (name || email || "").trim();
    if (!raw) return "";
    const parts = raw.split(/\s+/).filter(Boolean);
    if (parts.length >= 2) {
      return (parts[0][0] + parts[1][0]).toUpperCase();
    }
    return raw[0].toUpperCase();
  };

  const initials = getInitials();
  const fontSize = Math.max(9, Math.round(size * 0.42));

  if (src && !imageFailed) {
    return (
      <img
        src={src}
        alt=""
        referrerPolicy="no-referrer"
        crossOrigin="anonymous"
        onError={() => setImageFailed(true)}
        className={`rounded-full object-cover flex-shrink-0 select-none ${className}`}
        style={{ width: `${size}px`, height: `${size}px` }}
      />
    );
  }

  return (
    <div
      className={`rounded-full flex items-center justify-center flex-shrink-0 select-none font-medium text-white shadow-inner ${className}`}
      style={{
        width: `${size}px`,
        height: `${size}px`,
        fontSize: `${fontSize}px`,
        background: "linear-gradient(135deg, rgba(56,189,248,0.28) 0%, rgba(99,102,241,0.38) 100%)",
        border: "1px solid rgba(255,255,255,0.18)",
        color: "#ffffff",
      }}
      title={name || email || "User"}
    >
      {initials ? initials : <User style={{ width: `${Math.round(size * 0.55)}px`, height: `${Math.round(size * 0.55)}px` }} className="text-white/80" />}
    </div>
  );
};
