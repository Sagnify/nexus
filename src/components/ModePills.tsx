import React from 'react';
import { LayoutGrid, AppWindow, Folder, Bot } from 'lucide-react';

export type SpotlightMode = 'all' | 'apps' | 'files' | 'ai';

interface ModePillsProps {
  currentMode: SpotlightMode;
  onSelectMode: (mode: SpotlightMode) => void;
}

const MODES: { id: SpotlightMode; label: string; icon: React.ElementType }[] = [
  { id: 'all',   label: 'All',   icon: LayoutGrid },
  { id: 'apps',  label: 'Apps',  icon: AppWindow },
  { id: 'files', label: 'Files', icon: Folder },
  { id: 'ai',    label: 'AI',    icon: Bot },
];

export const ModePills: React.FC<ModePillsProps> = ({ currentMode, onSelectMode }) => {
  return (
    <div
      role="tablist"
      aria-label="Search Categories"
      className="flex items-center gap-1 px-3 py-1.5 border-t border-white/[0.06] select-none"
    >
      {MODES.map((mode) => {
        const isActive = currentMode === mode.id;
        const Icon = mode.icon;
        return (
          <button
            key={mode.id}
            role="tab"
            aria-selected={isActive}
            onClick={() => onSelectMode(mode.id)}
            className={`flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[11px] font-medium transition-all duration-120 border ${
              isActive
                ? 'bg-white/[0.08] text-white border-white/[0.09] shadow-sm'
                : 'bg-transparent text-white/40 border-transparent hover:text-white/70 hover:bg-white/[0.035]'
            }`}
          >
            <Icon
              className={`w-3.5 h-3.5 flex-shrink-0 transition-colors ${
                isActive ? 'text-sky-400' : 'text-white/40'
              }`}
              strokeWidth={1.9}
            />
            <span>{mode.label}</span>
          </button>
        );
      })}

      <div className="ml-auto flex items-center gap-1 text-white/20 font-mono text-[10px]">
        <kbd className="px-1.5 py-0.5 rounded text-[9px] font-medium border border-white/[0.08] bg-white/[0.03] text-white/35">
          Tab
        </kbd>
        <span>switch</span>
      </div>
    </div>
  );
};
