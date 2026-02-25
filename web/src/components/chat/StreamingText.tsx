import { useEffect, useState, useRef } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

interface StreamingTextProps {
  content: string;
  isStreaming: boolean;
}

export function StreamingText({ content, isStreaming }: StreamingTextProps) {
  const [displayLength, setDisplayLength] = useState(0);
  const prevContentRef = useRef("");
  const timerRef = useRef<ReturnType<typeof setInterval>>(undefined);

  useEffect(() => {
    if (content.length > prevContentRef.current.length && content.length > 0) {
      const startFrom = prevContentRef.current.length;
      setDisplayLength(startFrom);

      if (timerRef.current) clearInterval(timerRef.current);

      const totalNew = content.length - startFrom;
      const charsPerFrame = Math.max(3, Math.ceil(totalNew / 50));

      timerRef.current = setInterval(() => {
        setDisplayLength((prev) => {
          const next = Math.min(prev + charsPerFrame, content.length);
          if (next >= content.length) {
            clearInterval(timerRef.current);
          }
          return next;
        });
      }, 16);
    }

    prevContentRef.current = content;

    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [content]);

  if (!content) {
    return isStreaming ? (
      <span className="streaming-cursor text-muted-foreground">&nbsp;</span>
    ) : null;
  }

  const visible = content.slice(0, displayLength);
  const showCursor = isStreaming || displayLength < content.length;

  return (
    <div className="markdown-content text-sm">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{visible}</ReactMarkdown>
      {showCursor && <span className="streaming-cursor" />}
    </div>
  );
}
