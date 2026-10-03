import React, { useState, useEffect, useRef, useCallback } from 'react';
import {
  CheckCircle2,
  AlertCircle,
  Minimize2,
  ChevronDown,
  ChevronUp,
  Zap,
  Loader2,
  RefreshCw,
  FileText,
  Bold,
  Italic,
  Underline,
  Type,
  Copy,
  Scissors,
  Clipboard,
  Search,
  Replace,
  AlignLeft,
  AlignCenter,
  AlignRight,
  AlignJustify,
  List,
  ListOrdered,
  Table,
  PlusCircle,
  Bookmark,
  Link,
  Layers,
  FileCheck,
  Presentation,
} from 'lucide-react';

interface WordCopilotProps {
  hwnd?: string | null;
  document?: string | null;
}

interface WordContextData {
  application?: string;
  version?: string;
  document_name?: string;
  document_path?: string;
  is_saved?: boolean;
  selection?: {
    text: string;
    length: number;
    has_selection: boolean;
    start: number;
    end: number;
  };
  active_style?: {
    font_name: string;
    font_size: number;
    bold: boolean;
    italic: boolean;
    underline: boolean;
    alignment: string;
    paragraph_text: string;
  };
  statistics?: {
    words: number;
    paragraphs: number;
    characters: number;
    tables: number;
    shapes: number;
    hyperlinks: number;
  };
  headings?: Array<{ style: string; text: string }>;
}

type FeatureTab = 'all' | 'presentation' | 'formatting' | 'clipboard' | 'find_replace' | 'paragraph' | 'insert';

export const WordCopilot: React.FC<WordCopilotProps> = ({ hwnd, document: documentProp }) => {
  const [isExpanded, setIsExpanded] = useState(false);
  const [activeTab, setActiveTab] = useState<FeatureTab>('all');
  const [instruction, setInstruction] = useState('');
  const [isRunning, setIsRunning] = useState(false);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);
  const [lastResult, setLastResult] = useState<{
    success: boolean;
    message: string;
    plan?: any[];
    results?: any[];
    error?: string;
  } | null>(null);
  const [context, setContext] = useState<WordContextData | null>(null);
  const [showContextDetails, setShowContextDetails] = useState(false);
  const [isLoadingContext, setIsLoadingContext] = useState(false);

  // Dedicated Find & Replace mini inputs
  const [findText, setFindText] = useState('');
  const [replaceText, setReplaceText] = useState('');
  const [showFindReplaceDrawer, setShowFindReplaceDrawer] = useState(false);

  const inputRef = useRef<HTMLInputElement>(null);
  const numericHwnd = hwnd ? parseInt(hwnd, 10) : undefined;
  const currentDocName = documentProp || context?.document_name || 'Word Document';

  // Fetch real-time deep Word context from backend
  const fetchContext = useCallback(async () => {
    setIsLoadingContext(true);
    try {
      const params = new URLSearchParams();
      if (hwnd) params.set('hwnd', hwnd);
      if (documentProp) params.set('document_name', documentProp);

      const res = await fetch(`http://127.0.0.1:8000/api/nexus/word/context?${params.toString()}`);
      if (res.ok) {
        const data = await res.json();
        if (data.context) {
          setContext(data.context);
        }
      }
    } catch (err) {
      console.warn('Could not fetch Word context:', err);
    } finally {
      setIsLoadingContext(false);
    }
  }, [hwnd, documentProp]);

  // Initial context load
  useEffect(() => {
    fetchContext();
  }, [fetchContext]);

  useEffect(() => {
    document.body.classList.add('word-copilot-view');
    return () => {
      document.body.classList.remove('word-copilot-view');
    };
  }, []);

  // Sync window size with Electron based on collapsed / expanded state
  useEffect(() => {
    if (numericHwnd && window.electronAPI?.resizeWordCopilot) {
      if (isExpanded) {
        let height = 450;
        if (showContextDetails) height += 120;
        if (showFindReplaceDrawer) height += 90;
        if (lastResult || statusMessage) height += 100;
        window.electronAPI.resizeWordCopilot(numericHwnd, 480, height);
      } else {
        window.electronAPI.resizeWordCopilot(numericHwnd, 160, 48);
      }
    }
  }, [isExpanded, showContextDetails, showFindReplaceDrawer, numericHwnd, lastResult, statusMessage]);

  // Focus input when expanded
  useEffect(() => {
    if (isExpanded) {
      setTimeout(() => {
        inputRef.current?.focus();
      }, 100);
    }
  }, [isExpanded]);

  const handleExecute = async (queryToRun?: string) => {
    const text = (queryToRun || instruction).trim();
    if (!text || isRunning) return;

    setIsRunning(true);
    setStatusMessage('Analyzing document and executing Word operation...');
    setLastResult(null);

    try {
      const res = await fetch('http://127.0.0.1:8000/api/nexus/word/execute', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          instruction: text,
          hwnd: numericHwnd,
          document_name: documentProp || undefined,
        }),
      });

      const data = await res.json();
      if (data.success) {
        setLastResult({
          success: true,
          message: data.message || 'Operation executed and verified in Word.',
          plan: data.plan,
          results: data.results,
        });
        if (data.updated_context) {
          setContext(data.updated_context);
        } else {
          fetchContext();
        }
        setInstruction('');
      } else {
        setLastResult({
          success: false,
          message: data.error || data.message || 'Operation could not be completed.',
          error: data.error,
          plan: data.plan,
        });
      }
    } catch (err: any) {
      setLastResult({
        success: false,
        message: err?.message || 'Connection error with NEXUS backend.',
        error: String(err),
      });
    } finally {
      setIsRunning(false);
      setStatusMessage(null);
    }
  };

  const handleDedicatedFindReplace = () => {
    if (!findText.trim()) return;
    const query = replaceText.trim()
      ? `Replace all occurrences of "${findText.trim()}" with "${replaceText.trim()}"`
      : `Find "${findText.trim()}"`;
    handleExecute(query);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      handleExecute();
    } else if (e.key === 'Escape') {
      setIsExpanded(false);
    }
  };

  // 6 Feature Categories Actions (including Presentation from Context)
  const quickActionsByCategory: Record<
    Exclude<FeatureTab, 'all'>,
    Array<{ label: string; query: string; icon?: React.ReactNode }>
  > = {
    presentation: [
      {
        label: '📊 PPT to Desktop',
        query: 'take the context from the word file and make a powerpoint presentation on that context or topic and save it in desktop',
        icon: <Presentation className="w-3 h-3 text-amber-400" />,
      },
      {
        label: '📑 6-Slide Summary Deck',
        query: 'Create a 6-slide executive presentation from this document and save to Desktop',
        icon: <FileText className="w-3 h-3 text-cyan-400" />,
      },
      {
        label: '💡 Tech Indigo Theme',
        query: 'Make a PowerPoint presentation with tech_indigo theme from this Word file on Desktop',
      },
      {
        label: '🌲 Emerald Crisp Theme',
        query: 'Make a PowerPoint presentation with emerald_green theme from this Word file on Desktop',
      },
    ],
    formatting: [
      { label: 'Bold', query: 'Make selected text bold', icon: <Bold className="w-3 h-3" /> },
      { label: 'Italic', query: 'Make selected text italic', icon: <Italic className="w-3 h-3" /> },
      { label: 'Underline', query: 'Underline selected text', icon: <Underline className="w-3 h-3" /> },
      { label: 'Font 14pt', query: 'Set font size to 14', icon: <Type className="w-3 h-3" /> },
      { label: 'Font 18pt', query: 'Set font size to 18' },
      { label: 'Highlight Yellow', query: 'Highlight selection in yellow' },
      { label: 'Navy Blue Text', query: 'Change font color to navy' },
      { label: 'Uppercase', query: 'Make selection uppercase' },
      { label: 'Title Case', query: 'Convert selection to title case' },
    ],
    clipboard: [
      { label: 'Copy Selection', query: 'Copy selection to clipboard', icon: <Copy className="w-3 h-3" /> },
      { label: 'Cut Selection', query: 'Cut selection to clipboard', icon: <Scissors className="w-3 h-3" /> },
      { label: 'Paste at Cursor', query: 'Paste clipboard content at cursor', icon: <Clipboard className="w-3 h-3" /> },
      { label: 'Duplicate Paragraph', query: 'Duplicate current paragraph', icon: <Layers className="w-3 h-3" /> },
    ],
    find_replace: [
      { label: 'Replace Draft → Final', query: 'Replace all occurrences of draft with final', icon: <Replace className="w-3 h-3" /> },
      { label: 'Remove Double Spaces', query: 'Replace double spaces with single space' },
      { label: 'Open Search Drawer', query: '__OPEN_FIND_DRAWER__', icon: <Search className="w-3 h-3" /> },
    ],
    paragraph: [
      { label: 'Center Align', query: 'Center align current paragraph', icon: <AlignCenter className="w-3 h-3" /> },
      { label: 'Left Align', query: 'Left align current paragraph', icon: <AlignLeft className="w-3 h-3" /> },
      { label: 'Right Align', query: 'Right align current paragraph', icon: <AlignRight className="w-3 h-3" /> },
      { label: 'Justify Text', query: 'Justify current paragraph', icon: <AlignJustify className="w-3 h-3" /> },
      { label: '1.5 Line Spacing', query: 'Set line spacing to 1.5' },
      { label: 'Double Spacing', query: 'Set line spacing to double' },
      { label: 'Bullet List', query: 'Format selection as bulleted list', icon: <List className="w-3 h-3" /> },
      { label: 'Numbered List', query: 'Format selection as numbered list', icon: <ListOrdered className="w-3 h-3" /> },
      { label: 'Indent +0.5"', query: 'Indent paragraph by 0.5 inches' },
    ],
    insert: [
      { label: 'Table (3x3)', query: 'Insert a table with 3 rows and 3 columns', icon: <Table className="w-3 h-3" /> },
      { label: 'Table (4x5)', query: 'Insert a table with 4 rows and 5 columns', icon: <Table className="w-3 h-3" /> },
      { label: 'Page Break', query: 'Insert a page break', icon: <PlusCircle className="w-3 h-3" /> },
      { label: 'Header & Page #', query: 'Add document header with title and page number', icon: <Bookmark className="w-3 h-3" /> },
      { label: 'Hyperlink Google', query: 'Insert a hyperlink to https://google.com with text Google', icon: <Link className="w-3 h-3" /> },
      { label: 'Rectangle Shape', query: 'Insert a rectangle shape' },
    ],
  };

  const getVisibleActions = () => {
    if (activeTab === 'all') {
      return [
        {
          label: '📊 PPT to Desktop',
          query: 'take the context from the word file and make a powerpoint presentation on that context or topic and save it in desktop',
          icon: <Presentation className="w-3 h-3 text-amber-400" />,
        },
        { label: 'Bold', query: 'Make selected text bold', icon: <Bold className="w-3 h-3" /> },
        { label: 'Italic', query: 'Make selected text italic', icon: <Italic className="w-3 h-3" /> },
        { label: 'Center Align', query: 'Center align current paragraph', icon: <AlignCenter className="w-3 h-3" /> },
        { label: 'Bullet List', query: 'Format selection as bulleted list', icon: <List className="w-3 h-3" /> },
        { label: 'Table 3x3', query: 'Insert a table with 3 rows and 3 columns', icon: <Table className="w-3 h-3" /> },
        { label: 'Copy Selection', query: 'Copy selection to clipboard', icon: <Copy className="w-3 h-3" /> },
        { label: 'Paste at Cursor', query: 'Paste clipboard content at cursor', icon: <Clipboard className="w-3 h-3" /> },
        { label: 'Find & Replace', query: '__OPEN_FIND_DRAWER__', icon: <Replace className="w-3 h-3" /> },
        { label: 'Page Break', query: 'Insert a page break', icon: <PlusCircle className="w-3 h-3" /> },
      ];
    }
    return quickActionsByCategory[activeTab] || [];
  };

  // Collapsed Mode: Small Floating NEXUS badge with Microsoft Word blue branding
  if (!isExpanded) {
    return (
      <div className="w-[160px] h-[48px] p-1 flex items-center justify-center select-none">
        <button
          onClick={() => setIsExpanded(true)}
          className="group relative flex items-center gap-2 px-3 py-1.5 rounded-full bg-slate-900/95 hover:bg-slate-800 border border-blue-500/50 hover:border-blue-400 shadow-[0_0_20px_rgba(37,99,235,0.45)] backdrop-blur-md transition-all duration-200 cursor-pointer active:scale-95"
          title={`NEXUS Floating Word Copilot - Click to command ${currentDocName}`}
        >
          <div className="relative flex items-center justify-center w-5 h-5 rounded-full bg-blue-500/20 text-blue-400">
            <span className="w-2 h-2 rounded-full bg-blue-400 animate-ping absolute" />
            <span className="w-2 h-2 rounded-full bg-blue-400 relative" />
          </div>
          <span className="text-xs font-semibold text-slate-100 group-hover:text-white tracking-wide">
            NEXUS
          </span>
          <span className="text-[10px] px-1.5 py-0.5 rounded bg-blue-950/90 text-blue-300 font-mono font-semibold border border-blue-500/40">
            Word
          </span>
        </button>
      </div>
    );
  }

  // Expanded Mode: Floating Word Command Window
  return (
    <div className="w-full h-full p-2 flex flex-col font-sans select-none animate-in fade-in zoom-in-95 duration-150">
      <div className="flex-1 flex flex-col rounded-2xl bg-slate-950/95 border border-blue-500/40 shadow-[0_10px_35px_rgba(0,0,0,0.85),0_0_25px_rgba(37,99,235,0.25)] backdrop-blur-xl overflow-hidden text-slate-200">
        
        {/* Header Bar */}
        <div className="flex items-center justify-between px-3.5 py-2.5 bg-gradient-to-r from-slate-900/90 via-blue-950/30 to-slate-950 border-b border-blue-500/20">
          <div className="flex items-center gap-2 min-w-0">
            <div className="flex items-center justify-center w-6 h-6 rounded-lg bg-blue-500/20 text-blue-400 border border-blue-500/40 shadow-[0_0_10px_rgba(37,99,235,0.3)]">
              <FileText className="w-3.5 h-3.5" />
            </div>
            <div className="flex flex-col min-w-0">
              <div className="flex items-center gap-1.5">
                <span className="text-xs font-bold text-white tracking-wide">NEXUS</span>
                <span className="text-[10px] px-1.5 py-0.5 rounded bg-blue-900/50 text-blue-300 border border-blue-500/30 font-medium truncate max-w-[150px]">
                  {currentDocName}
                </span>
                {context?.is_saved ? (
                  <span className="text-[9px] px-1.5 py-0.2 rounded bg-emerald-950/70 text-emerald-400 border border-emerald-500/30 flex items-center gap-0.5">
                    <FileCheck className="w-2.5 h-2.5" /> Saved
                  </span>
                ) : (
                  <span className="text-[9px] px-1.5 py-0.2 rounded bg-amber-950/70 text-amber-400 border border-amber-500/30">
                    Editing
                  </span>
                )}
              </div>
            </div>
          </div>

          <div className="flex items-center gap-1">
            <button
              onClick={fetchContext}
              disabled={isLoadingContext}
              className="p-1 rounded-lg hover:bg-slate-800 text-slate-400 hover:text-blue-300 transition-colors"
              title="Refresh Word document context"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${isLoadingContext ? 'animate-spin text-blue-400' : ''}`} />
            </button>
            <button
              onClick={() => setIsExpanded(false)}
              className="p-1 rounded-lg hover:bg-slate-800 text-slate-400 hover:text-slate-100 transition-colors"
              title="Minimize to floating icon"
            >
              <Minimize2 className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>

        {/* Real-time Context Bar */}
        <div className="flex items-center justify-between px-3.5 py-1.5 bg-slate-900/50 border-b border-slate-800/80 text-[11px] text-slate-400">
          <div className="flex items-center gap-2 overflow-hidden text-ellipsis whitespace-nowrap">
            {context?.statistics && (
              <span className="flex items-center gap-1.5 text-slate-300 font-mono text-[10px]">
                <span className="text-blue-400">{context.statistics.words} words</span>
                <span>•</span>
                <span>{context.statistics.paragraphs} para</span>
                {context.statistics.tables > 0 && (
                  <>
                    <span>•</span>
                    <span className="text-indigo-300">{context.statistics.tables} tables</span>
                  </>
                )}
              </span>
            )}
            {context?.selection?.has_selection && (
              <span className="text-blue-400/90 font-mono text-[10px] truncate max-w-[140px]">
                Sel: &quot;{context.selection.text}&quot;
              </span>
            )}
          </div>
          <button
            onClick={() => setShowContextDetails(!showContextDetails)}
            className="flex items-center gap-0.5 text-blue-400 hover:text-blue-300 text-[10px] font-medium shrink-0 ml-2"
          >
            <span>{showContextDetails ? 'Hide Details' : 'Inspect Context'}</span>
            {showContextDetails ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
          </button>
        </div>

        {/* Collapsible Context Inspector */}
        {showContextDetails && context && (
          <div className="px-3.5 py-2.5 bg-slate-900/95 border-b border-slate-800 max-h-36 overflow-y-auto text-xs space-y-2">
            <div className="grid grid-cols-2 gap-2 text-[10px]">
              <div className="p-1.5 rounded bg-slate-950/70 border border-slate-800">
                <span className="text-slate-400 block mb-0.5">Active Font & Style:</span>
                <span className="font-mono text-blue-300 font-semibold">
                  {context.active_style?.font_name} {context.active_style?.font_size}pt
                </span>
                <div className="flex gap-1.5 mt-1 text-[9px] text-slate-300">
                  {context.active_style?.bold && <span className="text-blue-400 font-bold">Bold</span>}
                  {context.active_style?.italic && <span className="italic">Italic</span>}
                  {context.active_style?.underline && <span className="underline">Underline</span>}
                  <span className="capitalize">{context.active_style?.alignment}</span>
                </div>
              </div>
              <div className="p-1.5 rounded bg-slate-950/70 border border-slate-800">
                <span className="text-slate-400 block mb-0.5">Structure Count:</span>
                <div className="text-[10px] text-slate-300 flex flex-wrap gap-x-2 gap-y-0.5">
                  <span>Chars: {context.statistics?.characters || 0}</span>
                  <span>Shapes: {context.statistics?.shapes || 0}</span>
                  <span>Links: {context.statistics?.hyperlinks || 0}</span>
                </div>
              </div>
            </div>

            {context.headings && context.headings.length > 0 && (
              <div>
                <span className="text-[10px] font-semibold text-slate-400 block mb-1">Headings Outline:</span>
                <div className="flex flex-col gap-1 max-h-20 overflow-y-auto pr-1">
                  {context.headings.map((h, i) => (
                    <div key={i} className="text-[10px] text-slate-300 font-mono flex items-center gap-1.5 truncate">
                      <span className="text-blue-400/80 text-[9px]">[{h.style}]</span>
                      <span className="truncate">{h.text}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {/* Feature Categories Bar */}
        <div className="flex items-center gap-1 px-3 pt-2 pb-1 border-b border-slate-800/60 overflow-x-auto text-[10px]">
          {(
            [
              { id: 'all', label: 'All Operations' },
              { id: 'presentation', label: '📊 PowerPoint PPT' },
              { id: 'formatting', label: 'Text Format' },
              { id: 'clipboard', label: 'Clipboard' },
              { id: 'find_replace', label: 'Find & Replace' },
              { id: 'paragraph', label: 'Paragraphs' },
              { id: 'insert', label: 'Insert Elements' },
            ] as const
          ).map((tab) => (
            <button
              key={tab.id}
              onClick={() => {
                setActiveTab(tab.id);
                if (tab.id === 'find_replace') {
                  setShowFindReplaceDrawer(true);
                }
              }}
              className={`px-2 py-0.5 rounded-full whitespace-nowrap transition-colors cursor-pointer ${
                activeTab === tab.id
                  ? 'bg-blue-600 text-white font-medium shadow-[0_0_8px_rgba(37,99,235,0.4)]'
                  : 'bg-slate-900 text-slate-400 hover:text-slate-200 hover:bg-slate-800 border border-slate-800'
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {/* Dedicated Find & Replace Mini Drawer */}
        {showFindReplaceDrawer && (
          <div className="px-3 py-2 bg-slate-900/80 border-b border-blue-500/20 flex flex-col gap-1.5 animate-in slide-in-from-top-2 duration-150">
            <div className="flex items-center justify-between text-[11px] text-blue-300 font-medium">
              <span className="flex items-center gap-1">
                <Replace className="w-3 h-3 text-blue-400" /> Find & Replace in Document
              </span>
              <button
                onClick={() => setShowFindReplaceDrawer(false)}
                className="text-[10px] text-slate-400 hover:text-slate-200"
              >
                Close
              </button>
            </div>
            <div className="flex gap-1.5 items-center">
              <input
                type="text"
                placeholder="Find text..."
                value={findText}
                onChange={(e) => setFindText(e.target.value)}
                className="flex-1 px-2 py-1 rounded-lg bg-slate-950 border border-slate-700 text-xs text-white placeholder-slate-500 outline-none focus:border-blue-500"
              />
              <input
                type="text"
                placeholder="Replace with..."
                value={replaceText}
                onChange={(e) => setReplaceText(e.target.value)}
                className="flex-1 px-2 py-1 rounded-lg bg-slate-950 border border-slate-700 text-xs text-white placeholder-slate-500 outline-none focus:border-blue-500"
              />
              <button
                onClick={handleDedicatedFindReplace}
                disabled={isRunning || !findText.trim()}
                className="px-2.5 py-1 rounded-lg bg-blue-600 hover:bg-blue-500 disabled:opacity-40 text-white text-xs font-semibold flex items-center gap-1"
              >
                Replace All
              </button>
            </div>
          </div>
        )}

        {/* Input Bar */}
        <div className="p-3 flex flex-col gap-2">
          <div className="relative flex items-center">
            <input
              ref={inputRef}
              type="text"
              value={instruction}
              onChange={(e) => setInstruction(e.target.value)}
              onKeyDown={handleKeyDown}
              disabled={isRunning}
              placeholder="What should I do in Word? (e.g. Bold title, insert table 3x3, align center...)"
              className="w-full pr-24 pl-3 py-2 rounded-xl bg-slate-900/90 border border-slate-700 focus:border-blue-500 focus:ring-1 focus:ring-blue-500 outline-none text-xs text-white placeholder-slate-500 transition-all"
            />
            <button
              onClick={() => handleExecute()}
              disabled={isRunning || !instruction.trim()}
              className="absolute right-1.5 px-3 py-1.5 rounded-lg bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 disabled:opacity-40 disabled:pointer-events-none text-white text-xs font-semibold flex items-center gap-1.5 shadow-[0_0_10px_rgba(37,99,235,0.3)] transition-all cursor-pointer"
            >
              {isRunning ? (
                <>
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  <span>Acting...</span>
                </>
              ) : (
                <>
                  <Zap className="w-3.5 h-3.5" />
                  <span>Execute</span>
                </>
              )}
            </button>
          </div>

          {/* Quick Action Chips for Current Category */}
          <div className="flex flex-wrap gap-1.5 pt-0.5 max-h-24 overflow-y-auto">
            {getVisibleActions().map((action, i) => (
              <button
                key={i}
                onClick={() => {
                  if (action.query === '__OPEN_FIND_DRAWER__') {
                    setShowFindReplaceDrawer(true);
                  } else {
                    setInstruction(action.query);
                    handleExecute(action.query);
                  }
                }}
                disabled={isRunning}
                className="flex items-center gap-1 px-2 py-1 rounded-md bg-slate-900/90 hover:bg-blue-950/70 border border-slate-800 hover:border-blue-500/40 text-[10px] text-slate-300 hover:text-blue-300 transition-all cursor-pointer active:scale-95"
              >
                {action.icon}
                <span>{action.label}</span>
              </button>
            ))}
          </div>
        </div>

        {/* Live Status & Result Feedback */}
        {(statusMessage || lastResult) && (
          <div className="px-3 pb-3">
            {statusMessage && (
              <div className="flex items-center gap-2 p-2 rounded-lg bg-blue-950/40 border border-blue-500/30 text-xs text-blue-300">
                <Loader2 className="w-4 h-4 animate-spin text-blue-400 shrink-0" />
                <span className="truncate">{statusMessage}</span>
              </div>
            )}

            {lastResult && (
              <div
                className={`flex items-start gap-2 p-2.5 rounded-xl border text-xs ${
                  lastResult.success
                    ? 'bg-emerald-950/40 border-emerald-500/40 text-emerald-300 shadow-[0_0_15px_rgba(16,185,129,0.15)]'
                    : 'bg-rose-950/40 border-rose-500/40 text-rose-300 shadow-[0_0_15px_rgba(244,63,94,0.15)]'
                }`}
              >
                {lastResult.success ? (
                  <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0 mt-0.5" />
                ) : (
                  <AlertCircle className="w-4 h-4 text-rose-400 shrink-0 mt-0.5" />
                )}
                <div className="flex flex-col min-w-0">
                  <span className="font-semibold">{lastResult.message}</span>
                  {lastResult.plan && lastResult.plan.length > 0 && (
                    <span className="text-[10px] text-slate-400 mt-0.5 font-mono">
                      ✓ Tool: {lastResult.plan.map((p) => p.tool).join(', ')} verified in Word
                    </span>
                  )}
                  {lastResult.results?.some((r: any) => r.metadata?.file_path) && (
                    <div className="mt-2 p-1.5 rounded-lg bg-amber-950/40 border border-amber-500/30 text-amber-300 text-[11px] flex items-center gap-1.5">
                      <Presentation className="w-3.5 h-3.5 text-amber-400 shrink-0" />
                      <span className="truncate font-mono text-[10px]">
                        Saved to Desktop: {lastResult.results.find((r: any) => r.metadata?.file_path)?.metadata?.file_path}
                      </span>
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
        )}

      </div>
    </div>
  );
};
