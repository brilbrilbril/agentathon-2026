import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

/**
 * The agent answers in markdown — tables, bold, headings, lists. Rendering it
 * as plain text made a comparison table read as a wall of pipes.
 *
 * Styles are set per element rather than via the typography plugin so the
 * output stays compact enough to sit inside a chat bubble.
 */
export function Markdown({ children }: { children: string }) {
  return (
    <div className="text-sm leading-relaxed text-slate-800">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          h1: ({ children }) => <h1 className="mb-2 mt-3 text-base font-bold first:mt-0">{children}</h1>,
          h2: ({ children }) => <h2 className="mb-2 mt-3 text-sm font-bold first:mt-0">{children}</h2>,
          h3: ({ children }) => <h3 className="mb-1 mt-3 text-sm font-semibold first:mt-0">{children}</h3>,
          p: ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
          ul: ({ children }) => <ul className="mb-2 ml-4 list-disc space-y-0.5 last:mb-0">{children}</ul>,
          ol: ({ children }) => <ol className="mb-2 ml-4 list-decimal space-y-0.5 last:mb-0">{children}</ol>,
          li: ({ children }) => <li className="pl-0.5">{children}</li>,
          strong: ({ children }) => <strong className="font-semibold text-slate-900">{children}</strong>,
          a: ({ children, href }) => (
            <a href={href} className="text-sky-700 underline" target="_blank" rel="noreferrer">
              {children}
            </a>
          ),
          code: ({ children, className }) =>
            className?.includes('language-') ? (
              <code className="block overflow-x-auto rounded bg-slate-900 p-3 font-mono text-xs text-slate-100">
                {children}
              </code>
            ) : (
              <code className="rounded bg-slate-100 px-1 py-0.5 font-mono text-[12px] text-slate-800">
                {children}
              </code>
            ),
          pre: ({ children }) => <pre className="mb-2 last:mb-0">{children}</pre>,
          blockquote: ({ children }) => (
            <blockquote className="mb-2 border-l-2 border-slate-300 pl-3 text-slate-600">{children}</blockquote>
          ),
          table: ({ children }) => (
            <div className="mb-2 overflow-x-auto last:mb-0">
              <table className="w-full border-collapse text-xs">{children}</table>
            </div>
          ),
          thead: ({ children }) => <thead className="border-b border-slate-200">{children}</thead>,
          th: ({ children }) => (
            <th className="px-2 py-1.5 text-left font-semibold text-slate-500">{children}</th>
          ),
          td: ({ children }) => (
            <td className="border-b border-slate-50 px-2 py-1.5 align-top">{children}</td>
          ),
          hr: () => <hr className="my-3 border-slate-200" />,
        }}
      >
        {children}
      </ReactMarkdown>
    </div>
  )
}
