import React, { useState, useEffect, useCallback } from "react";
import { NexusLogoMedia } from "./NexusLogoMedia";

interface NexusSphereProps {
  className?: string;
}

const introLines = [
  "Hi this is N.E.X.U.S.",
  "Your Adaptive Automation Companion",
];

const workflowStates = [
  "Monitoring The Workflow...",
  "Adapting to Environment...",
  "Waiting For User Approval...",
  "Approved by User",
  "Executing...",
];

export const NexusSphere: React.FC<NexusSphereProps> = ({ className = "" }) => {
  const [mode, setMode] = useState<"intro" | "workflow">("intro");
  const [lineIndex, setLineIndex] = useState(0);
  const [typedText, setTypedText] = useState("");
  const [isDeleting, setIsDeleting] = useState(false);
  const [statusIndex, setStatusIndex] = useState(0);

  const activate = useCallback(() => {
    setMode((prev) => (prev === "intro" ? "workflow" : "intro"));
    setTypedText("");
    setIsDeleting(false);
    setStatusIndex(0);
  }, []);

  useEffect(() => {
    if (mode === "workflow") {
      const timer = window.setTimeout(() => {
        setStatusIndex((index) => (index + 1) % workflowStates.length);
      }, 2200);
      return () => window.clearTimeout(timer);
    }

    const target = introLines[lineIndex];
    const isComplete = typedText === target;
    const timer = window.setTimeout(
      () => {
        if (!isDeleting && !isComplete) {
          setTypedText(target.slice(0, typedText.length + 1));
        } else if (!isDeleting && isComplete) {
          setIsDeleting(true);
        } else if (isDeleting && typedText.length > 0) {
          setTypedText(target.slice(0, typedText.length - 1));
        } else {
          setIsDeleting(false);
          setLineIndex((index) => (index + 1) % introLines.length);
        }
      },
      isComplete && !isDeleting ? 1400 : isDeleting ? 40 : 55
    );
    return () => window.clearTimeout(timer);
  }, [lineIndex, mode, isDeleting, typedText]);

  return (
    <div
      role="button"
      tabIndex={0}
      aria-label={mode === "workflow" ? "Restart N.E.X.U.S. workflow" : "Activate N.E.X.U.S. workflow"}
      onClick={activate}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          activate();
        }
      }}
      className={`group relative block h-[320px] sm:h-[360px] w-full cursor-pointer overflow-hidden rounded-3xl border border-white/10 bg-black/[0.95] backdrop-blur-xl transition-all duration-300 hover:border-blue-400/40 focus:outline-none focus:ring-2 focus:ring-blue-400 ${className}`}
    >
      {/* Background Radial Glow */}
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_50%_50%,rgba(41,121,255,0.08),transparent_65%)]" />

      {/* Sphere Core & Concentric Rings */}
      <div className="absolute left-1/2 top-[42%] -translate-x-1/2 -translate-y-1/2 flex items-center justify-center">
        {/* Core Glowing Sphere with 3D Nexus Logo */}
        <div
          className={`h-40 w-40 sm:h-48 sm:w-48 rounded-full border border-blue-400/30 bg-[radial-gradient(circle_at_50%_50%,rgba(56,189,248,0.22),rgba(168,85,247,0.18)_45%,rgba(0,0,0,0.92)_74%)] shadow-[0_0_55px_rgba(56,189,248,0.3)] flex items-center justify-center transition-all duration-500 ease-out overflow-hidden ${
            mode === "workflow"
              ? "animate-heartbeat shadow-[0_0_85px_rgba(168,85,247,0.5)]"
              : "group-hover:scale-105 group-hover:shadow-[0_0_75px_rgba(56,189,248,0.45)]"
          }`}
        >
          <NexusLogoMedia
            type={mode === "workflow" ? "video" : "image"}
            className={
              mode === "workflow"
                ? "w-32 h-32 sm:w-36 sm:h-36"
                : "w-24 h-24 sm:w-28 sm:h-28"
            }
            mediaClassName={
              mode === "workflow"
                ? ""
                : "drop-shadow-[0_0_24px_rgba(56,189,248,0.9)] transition-all duration-700 group-hover:scale-110"
            }
            alt="N.E.X.U.S. Core"
          />
        </div>
      </div>

      {/* Inner Orbital Ring */}
      <div
        className={`pointer-events-none absolute left-1/2 top-[42%] h-56 w-56 sm:h-64 sm:w-64 -translate-x-1/2 -translate-y-1/2 rounded-full border border-white/10 transition-transform duration-700 ease-out ${
          mode === "workflow"
            ? "rotate-45 scale-110"
            : "rotate-[18deg] group-hover:rotate-12"
        }`}
      />

      {/* Outer Orbital Ring */}
      <div
        className={`pointer-events-none absolute left-1/2 top-[42%] h-64 w-64 sm:h-72 sm:w-72 -translate-x-1/2 -translate-y-1/2 rounded-full border border-blue-400/15 transition-transform duration-1000 ease-out ${
          mode === "workflow"
            ? "-rotate-45 scale-105"
            : "-rotate-[24deg] group-hover:-rotate-12"
        }`}
      />

      {/* Interactive Mode Indicator Pill */}
      <div className="absolute top-4 right-4 z-10 flex items-center gap-1.5 px-3 py-1 rounded-full border border-white/10 bg-black/60 text-[11px] font-mono text-neutral-400">
        <span
          className={`w-1.5 h-1.5 rounded-full ${
            mode === "workflow" ? "bg-emerald-400 animate-pulse" : "bg-blue-400"
          }`}
        />
        <span>{mode === "workflow" ? "WORKFLOW LOOP" : "CLICK TO INTERACT"}</span>
      </div>

      {/* Typewriter Text Display at Bottom */}
      <div className="absolute inset-x-4 bottom-5 min-h-[50px] flex items-center justify-center text-center font-mono text-xs sm:text-sm tracking-wide text-transparent bg-gradient-to-r from-blue-300 via-cyan-200 to-blue-500 bg-clip-text">
        {mode === "intro" ? (
          <span>
            {typedText}
            <span className="ml-0.5 animate-pulse text-blue-300">▋</span>
          </span>
        ) : (
          <span className="animate-pulse">
            {workflowStates[statusIndex]}
          </span>
        )}
      </div>
    </div>
  );
};
