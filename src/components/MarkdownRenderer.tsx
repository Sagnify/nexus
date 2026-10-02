import React from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

interface MarkdownRendererProps {
  content: string;
  className?: string;
}

// Helper to strip any unexpected emojis to honor user preference
const sanitizeText = (text: string): string => {
  if (!text) return '';
  return text.replace(
    /([\u2700-\u27BF]|[\uE000-\uF8FF]|\uD83C[\uDC00-\uDFFF]|\uD83D[\uDC00-\uDFFF]|[\u2011-\u26FF]|\uD83E[\uDD10-\uDDFF])/g,
    ''
  );
};

export const MarkdownRenderer: React.FC<MarkdownRendererProps> = ({ content, className = '' }) => {
  const cleanContent = sanitizeText(content);

  return (
    <div className={`nexus-markdown text-xs leading-relaxed text-neutral-200 font-sans ${className}`}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          h1: ({ children }) => (
            <h1 className="text-sm font-semibold text-white mt-3 mb-1.5 pb-1 border-b border-white/10 first:mt-0">
              {children}
            </h1>
          ),
          h2: ({ children }) => (
            <h2 className="text-xs font-semibold text-white mt-2.5 mb-1 pb-0.5 border-b border-white/10 first:mt-0">
              {children}
            </h2>
          ),
          h3: ({ children }) => (
            <h3 className="text-xs font-medium text-neutral-100 mt-2 mb-1 first:mt-0">
              {children}
            </h3>
          ),
          p: ({ children }) => (
            <p className="mb-2 last:mb-0 leading-relaxed text-neutral-200">
              {children}
            </p>
          ),
          strong: ({ children }) => (
            <strong className="font-semibold text-white">
              {children}
            </strong>
          ),
          em: ({ children }) => (
            <em className="text-neutral-300 italic">
              {children}
            </em>
          ),
          ul: ({ children }) => (
            <ul className="list-disc list-inside mb-2 space-y-1 pl-1 text-neutral-300">
              {children}
            </ul>
          ),
          ol: ({ children }) => (
            <ol className="list-decimal list-inside mb-2 space-y-1 pl-1 text-neutral-300">
              {children}
            </ol>
          ),
          li: ({ children }) => (
            <li className="leading-relaxed">
              {children}
            </li>
          ),
          blockquote: ({ children }) => (
            <blockquote className="border-l-2 border-blue-500/50 pl-3 my-2 text-neutral-400 italic bg-white/[0.02] py-1 rounded-r">
              {children}
            </blockquote>
          ),
          code: ({ inline, className, children, ...props }: any) => {
            if (inline) {
              return (
                <code
                  className="bg-white/10 text-indigo-300 font-mono text-[11px] px-1.5 py-0.5 rounded border border-white/10"
                  {...props}
                >
                  {children}
                </code>
              );
            }
            return (
              <div className="my-2 rounded-lg bg-black/50 border border-white/10 overflow-hidden font-mono text-[11px]">
                <div className="px-3 py-1.5 bg-white/[0.04] border-b border-white/10 text-neutral-400 text-[10px] uppercase tracking-wider flex justify-between items-center">
                  <span>Code</span>
                </div>
                <pre className="p-3 overflow-x-auto text-neutral-200">
                  <code {...props}>{children}</code>
                </pre>
              </div>
            );
          },
          table: ({ children }) => (
            <div className="my-2.5 overflow-x-auto rounded-lg border border-white/10 bg-black/30">
              <table className="w-full text-left text-[11px] border-collapse">
                {children}
              </table>
            </div>
          ),
          thead: ({ children }) => (
            <thead className="bg-white/[0.06] text-neutral-200 font-semibold border-b border-white/10">
              {children}
            </thead>
          ),
          tbody: ({ children }) => (
            <tbody className="divide-y divide-white/5 text-neutral-300">
              {children}
            </tbody>
          ),
          tr: ({ children }) => (
            <tr className="hover:bg-white/[0.02] transition-colors">
              {children}
            </tr>
          ),
          th: ({ children }) => (
            <th className="px-3 py-2 font-medium text-white tracking-wide">
              {children}
            </th>
          ),
          td: ({ children }) => (
            <td className="px-3 py-2 align-top leading-snug">
              {children}
            </td>
          ),
          hr: () => <hr className="my-2.5 border-white/10" />,
          a: ({ href, children }) => (
            <a
              href={href}
              target="_blank"
              rel="noreferrer"
              className="text-blue-400 hover:text-blue-300 underline underline-offset-2 transition-colors"
            >
              {children}
            </a>
          ),
        }}
      >
        {cleanContent}
      </ReactMarkdown>
    </div>
  );
};
