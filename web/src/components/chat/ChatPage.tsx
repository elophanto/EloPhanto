import { SquarePen } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { useChatStore } from "@/stores/chat";
import { useConnectionStore } from "@/stores/connection";
import { MessageList } from "./MessageList";
import { ChatInput } from "./ChatInput";

export function ChatPage() {
  const messageCount = useChatStore((s) => s.messages.length);
  const status = useConnectionStore((s) => s.status);
  const conversations = useChatStore((s) => s.conversations);
  const currentId = useChatStore((s) => s.currentConversationId);
  const currentConv = conversations.find((c) => c.id === currentId);

  const handleNewChat = () => {
    if (status === "connected") {
      useChatStore.getState().startNewChat();
    } else {
      useChatStore.getState().clearMessages();
    }
  };

  return (
    <div className="flex h-full flex-col">
      {/* Chat header */}
      {messageCount > 0 && (
        <>
          <div className="flex items-center justify-between px-6 py-2">
            <div className="flex min-w-0 items-center gap-2">
              {currentConv && (
                <span className="truncate text-[11px] text-muted-foreground/70">
                  {currentConv.title}
                </span>
              )}
              <span className="shrink-0 font-mono text-[9px] uppercase tracking-[0.1em] text-muted-foreground/40">
                {messageCount} msg{messageCount !== 1 ? "s" : ""}
              </span>
            </div>
            <Button
              variant="ghost"
              size="sm"
              onClick={handleNewChat}
              className="h-7 gap-1.5 px-2 text-muted-foreground/60 hover:text-foreground"
              title="New conversation"
            >
              <SquarePen className="size-3.5" />
              <span className="font-mono text-[9px] uppercase tracking-[0.1em]">
                New Chat
              </span>
            </Button>
          </div>
          <Separator />
        </>
      )}
      <MessageList />
      <ChatInput />
    </div>
  );
}
