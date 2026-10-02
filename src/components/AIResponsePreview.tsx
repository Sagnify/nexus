import React, { useState, useEffect } from 'react';
import { Copy, Check, ArrowLeft } from 'lucide-react';

interface AIResponsePreviewProps {
  prompt: string;
  onBack: () => void;
}

export const AIResponsePreview: React.FC<AIResponsePreviewProps> = ({ prompt, onBack }) => {
  const [copied, setCopied] = useState(false);
  const [displayedText, setDisplayedText] = useState('');
  const [isTyping, setIsTyping] = useState(true);

  const fullResponse = `Response for "${prompt}":

• The floating spotlight interface is active.
• Shortcut: Alt + N (or Cmd + Shift + N on Mac).
• Dismiss with Esc or clicking outside.`;

  useEffect(() => {
    setDisplayedText('');
    setIsTyping(true);
    let index = 0;
    const interval = setInterval(() => {
      index += 5;
      if (index >= fullResponse.length) {
        setDisplayedText(fullResponse);
        setIsTyping(false);
        clearInterval(interval);
      } else {
        setDisplayedText(fullResponse.slice(0, index));
      }
    }, 15);

    return () => clearInterval(interval);
  }, [prompt]);

  const handleCopy = () => {
    navigator.clipboard.writeText(fullResponse);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="p-3.5 space-y-2.5 border-t border-white/[0.05]">
      <div className="flex items-center justify-between">
        <button
          onClick={onBack}
          className="flex items-center gap-1 text-[11px] text-white/40 hover:text-white/80 transition-colors"
        >
          <ArrowLeft className="w-3 h-3" />
          <span>Back</span>
        </button>

        <button
          onClick={handleCopy}
          className="flex items-center gap-1 px-1.5 py-0.5 rounded text-[11px] text-white/40 hover:text-white/80 hover:bg-white/[0.06] transition-colors"
        >
          {copied ? (
            <>
              <Check className="w-3 h-3 text-emerald-400" />
              <span className="text-emerald-400">Copied</span>
            </>
          ) : (
            <>
              <Copy className="w-3 h-3" />
              <span>Copy</span>
            </>
          )}
        </button>
      </div>

      <div className="bg-white/[0.03] rounded-lg p-3 text-[13px] text-white/80 leading-relaxed font-mono whitespace-pre-wrap">
        {displayedText}
        {isTyping && <span className="inline-block w-1 h-3 ml-0.5 bg-white/60 animate-pulse align-middle" />}
      </div>
    </div>
  );
};
