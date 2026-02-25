import { useState, useRef, useCallback } from "react";
import { ArrowUp } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { useConnectionStore } from "@/stores/connection";
import { useChatStore } from "@/stores/chat";

export function ChatInput() {
  const [value, setValue] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const status = useConnectionStore((s) => s.status);
  const isAgentTyping = useChatStore((s) => s.isAgentTyping);
  const sendMessage = useChatStore((s) => s.sendMessage);

  const isDisabled = status !== "connected" || isAgentTyping;
  const canSend = value.trim().length > 0 && !isDisabled;

  const handleSend = useCallback(() => {
    if (!canSend) return;
    sendMessage(value.trim());
    setValue("");
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
    }
  }, [canSend, value, sendMessage]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleInput = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setValue(e.target.value);
    // Auto-resize
    const el = e.target;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 160) + "px";
  };

  return (
    <div className="border-t border-border/50 px-4 py-3">
      <div
        className={cn(
          "chat-input-wrap flex items-end gap-2 rounded-lg border border-border/50 bg-card px-3 py-2 transition-all",
          isDisabled && "opacity-50"
        )}
      >
        <textarea
          ref={textareaRef}
          value={value}
          onChange={handleInput}
          onKeyDown={handleKeyDown}
          placeholder={
            status !== "connected"
              ? "Waiting for connection..."
              : isAgentTyping
                ? "Agent is responding..."
                : "Send a message..."
          }
          disabled={isDisabled}
          rows={1}
          className="max-h-40 flex-1 resize-none bg-transparent text-sm leading-relaxed outline-none placeholder:text-muted-foreground/50"
        />
        <Button
          variant="default"
          size="icon-xs"
          disabled={!canSend}
          onClick={handleSend}
          className="shrink-0 rounded-full"
        >
          <ArrowUp className="size-3.5" />
        </Button>
      </div>
      <div className="mt-1.5 flex items-center justify-between px-1">
        <span className="font-mono text-[9px] text-muted-foreground/30">
          Enter to send, Shift+Enter for new line
        </span>
      </div>
    </div>
  );
}
