import { MessageList } from "./MessageList";
import { ChatInput } from "./ChatInput";

export function ChatPage() {
  return (
    <div className="flex h-full flex-col">
      <MessageList />
      <ChatInput />
    </div>
  );
}
