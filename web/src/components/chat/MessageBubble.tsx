import { cn } from "@/lib/utils";
import type { Message } from "@/stores/chat";
import { StreamingText } from "./StreamingText";

interface MessageBubbleProps {
  message: Message;
}

export function MessageBubble({ message }: MessageBubbleProps) {
  const time = new Date(message.timestamp).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
  });

  if (message.type === "system" || message.type === "error") {
    return (
      <div className="message-enter flex justify-center py-2">
        <span
          className={cn(
            "font-mono text-[10px] uppercase tracking-[0.1em]",
            message.type === "error"
              ? "text-destructive"
              : "text-muted-foreground/60"
          )}
        >
          {message.content}
        </span>
      </div>
    );
  }

  if (message.type === "user") {
    return (
      <div className="message-enter flex flex-col items-end gap-1 py-3">
        <div className="flex items-center gap-2">
          <span className="font-mono text-[9px] uppercase tracking-[0.15em] text-muted-foreground/40">
            {time}
          </span>
          <span className="font-mono text-[9px] uppercase tracking-[0.15em] text-muted-foreground/60">
            You
          </span>
        </div>
        <div className="max-w-[80%] rounded-lg border border-border/50 bg-primary/10 px-4 py-3">
          <p className="whitespace-pre-wrap break-words text-sm leading-relaxed">
            {message.content}
          </p>
        </div>
      </div>
    );
  }

  // Agent message
  const isComplete = !message.isStreaming && message.content.length > 0;

  return (
    <div className="message-enter flex flex-col items-start gap-1 py-3">
      <div className="flex items-center gap-2">
        <span className="font-mono text-[9px] uppercase tracking-[0.15em] text-muted-foreground/60">
          EloPhanto
        </span>
        <span className="font-mono text-[9px] uppercase tracking-[0.15em] text-muted-foreground/40">
          {time}
        </span>
      </div>
      <div
        className={cn(
          "max-w-[90%] rounded-lg border border-border/50 px-5 py-4 text-sm",
          isComplete && "crop-marks"
        )}
      >
        <StreamingText
          content={message.content}
          isStreaming={message.isStreaming}
        />
      </div>
    </div>
  );
}
