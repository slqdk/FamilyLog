import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

/** Model-written and help text as Markdown (GitHub tables, lists). Links
    open in a new tab; raw HTML is not rendered. `streaming` adds a caret
    while an answer is still being written. */
export function Markdown({ text, streaming = false }: { text: string; streaming?: boolean }) {
  return (
    <div className={`md${streaming ? ' md-streaming' : ''}`}>
      <ReactMarkdown remarkPlugins={[remarkGfm]}
                     components={{ a: ({ node: _node, ...props }) => <a {...props} target="_blank" rel="noreferrer" /> }}>
        {text}
      </ReactMarkdown>
    </div>
  );
}
