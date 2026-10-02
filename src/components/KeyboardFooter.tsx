import React from 'react';
import { CornerDownLeft } from 'lucide-react';

export const KeyboardFooter: React.FC = () => {
  const hint = (key: React.ReactNode, label: string) => (
    <span className="flex items-center gap-1.5">
      <kbd
        className="flex items-center justify-center min-w-[18px] h-[17px] px-1 rounded text-[9.5px] font-mono font-medium"
        style={{
          color: 'rgba(255,255,255,0.45)',
          border: '1px solid rgba(255,255,255,0.08)',
          background: 'rgba(255,255,255,0.03)',
        }}
      >
        {key}
      </kbd>
      <span className="text-[10px] text-white/35 font-mono">{label}</span>
    </span>
  );

  return (
    <div
      className="flex items-center justify-between px-3.5 py-2"
      style={{
        borderTop: '1px solid rgba(255,255,255,0.06)',
      }}
    >
      <div className="flex items-center gap-3.5">
        {hint(<CornerDownLeft className="w-2.5 h-2.5 text-sky-400/80" />, 'select')}
        {hint('↑↓', 'navigate')}
        {hint('tab', 'mode')}
        {hint('esc', 'close')}
      </div>
      <div className="flex items-center gap-1.5 text-[10px] text-white/25 font-mono">
        <span>toggle</span>
        <kbd
          className="px-1.5 py-0.5 rounded text-[9px] font-mono font-medium"
          style={{
            border: '1px solid rgba(255,255,255,0.08)',
            background: 'rgba(255,255,255,0.03)',
            color: 'rgba(255,255,255,0.40)',
          }}
        >
          Alt+N
        </kbd>
      </div>
    </div>
  );
};
