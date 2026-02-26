import {
  LayoutDashboard,
  MessageSquare,
  Wrench,
  Sparkles,
  BookOpen,
  Brain,
  Calendar,
  Radio,
  Settings,
  History,
  ChevronLeft,
  ChevronRight,
  Sun,
  Moon,
  Plus,
  X,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useTheme } from "@/components/theme-provider";
import { useConnectionStore } from "@/stores/connection";
import { useNavigationStore, type Page } from "@/stores/navigation";
import { useChatStore } from "@/stores/chat";
import { gateway } from "@/lib/gateway";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";

interface SidebarProps {
  collapsed: boolean;
  onToggleCollapse: () => void;
}

const navItems: {
  id: Page;
  label: string;
  icon: typeof MessageSquare;
  enabled: boolean;
}[] = [
  { id: "dashboard", label: "Dashboard", icon: LayoutDashboard, enabled: true },
  { id: "chat", label: "Chat", icon: MessageSquare, enabled: true },
  { id: "tools", label: "Tools", icon: Wrench, enabled: true },
  { id: "skills", label: "Skills", icon: Sparkles, enabled: true },
  { id: "knowledge", label: "Knowledge", icon: BookOpen, enabled: true },
  { id: "mind", label: "Mind", icon: Brain, enabled: true },
  { id: "schedule", label: "Schedule", icon: Calendar, enabled: true },
  { id: "channels", label: "Channels", icon: Radio, enabled: true },
  { id: "settings", label: "Settings", icon: Settings, enabled: true },
  { id: "history", label: "History", icon: History, enabled: true },
];

export function Sidebar({ collapsed, onToggleCollapse }: SidebarProps) {
  const { theme, toggleTheme } = useTheme();
  const status = useConnectionStore((s) => s.status);
  const activePage = useNavigationStore((s) => s.activePage);
  const navigate = useNavigationStore((s) => s.navigate);
  const conversations = useChatStore((s) => s.conversations);
  const currentConvId = useChatStore((s) => s.currentConversationId);
  const switchConversation = useChatStore((s) => s.switchConversation);

  const handleDeleteConversation = (id: string) => {
    gateway.sendCommand("delete_conversation", { conversation_id: id });
    const store = useChatStore.getState();
    store.removeConversation(id);
    if (store.currentConversationId === id) {
      store.clearMessages();
    }
  };

  const statusClass =
    status === "connected"
      ? "status-connected"
      : status === "reconnecting"
        ? "status-reconnecting"
        : "status-disconnected";

  const statusLabel =
    status === "connected"
      ? "Connected"
      : status === "reconnecting"
        ? "Reconnecting"
        : status === "connecting"
          ? "Connecting"
          : "Disconnected";

  return (
    <aside
      className={cn(
        "relative flex h-screen flex-col border-r border-border/50 bg-sidebar transition-all duration-200",
        collapsed ? "w-16" : "w-56"
      )}
    >
      {/* Geometric decoration */}
      <div
        className="geo-circle"
        style={{ width: 200, height: 200, top: -80, left: -80 }}
      />

      {/* Logo */}
      <div className="flex h-16 items-center gap-3 px-4">
        <img
          src="/logo.webp"
          alt="EloPhanto"
          className="size-8 shrink-0 rounded-md"
        />
        {!collapsed && (
          <span className="font-mono text-[11px] uppercase tracking-[0.2em] text-foreground/80">
            EloPhanto
          </span>
        )}
      </div>

      <Separator className="opacity-50" />

      {/* Navigation */}
      <nav className="flex-1 space-y-1 overflow-y-auto px-2 py-3">
        {navItems.map((item) => {
          const isActive = item.id === activePage;
          const Icon = item.icon;

          const button = (
            <button
              key={item.id}
              onClick={() => item.enabled && navigate(item.id)}
              disabled={!item.enabled}
              className={cn(
                "nav-item flex w-full items-center gap-3 rounded-md px-3 py-2",
                isActive && "active",
                !item.enabled && "pointer-events-none opacity-30"
              )}
            >
              <Icon className="size-4 shrink-0" />
              {!collapsed && (
                <span className="font-mono text-[11px] uppercase tracking-[0.1em]">
                  {item.label}
                </span>
              )}
            </button>
          );

          // Show conversation list under Chat when active and expanded
          if (item.id === "chat" && isActive && !collapsed) {
            return (
              <div key={item.id}>
                {button}
                <div className="ml-7 mt-1 max-h-48 space-y-px overflow-y-auto pr-1">
                  <button
                    onClick={() => useChatStore.getState().startNewChat()}
                    className="flex w-full items-center gap-1.5 rounded px-2 py-1 text-muted-foreground/50 transition-colors hover:text-foreground"
                  >
                    <Plus className="size-3" />
                    <span className="text-[10px] tracking-wide">New chat</span>
                  </button>
                  {conversations.slice(0, 15).map((conv) => (
                    <div
                      key={conv.id}
                      className={cn(
                        "group flex items-center gap-1 rounded px-2 py-1 transition-colors",
                        conv.id === currentConvId
                          ? "bg-accent/50 text-foreground"
                          : "text-muted-foreground/60 hover:bg-accent/30 hover:text-foreground"
                      )}
                    >
                      <button
                        onClick={() => switchConversation(conv.id)}
                        className="min-w-0 flex-1 truncate text-left text-[11px] leading-tight"
                      >
                        {conv.title}
                      </button>
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          handleDeleteConversation(conv.id);
                        }}
                        className="shrink-0 rounded p-0.5 opacity-0 transition-opacity group-hover:opacity-100 hover:text-destructive"
                      >
                        <X className="size-2.5" />
                      </button>
                    </div>
                  ))}
                </div>
              </div>
            );
          }

          if (collapsed && item.enabled) {
            return (
              <Tooltip key={item.id}>
                <TooltipTrigger asChild>{button}</TooltipTrigger>
                <TooltipContent side="right">{item.label}</TooltipContent>
              </Tooltip>
            );
          }

          return button;
        })}
      </nav>

      {/* Bottom section */}
      <div className="space-y-3 px-3 pb-4">
        {/* Connection status */}
        <div className="flex items-center gap-2.5">
          <span className={cn("status-dot shrink-0", statusClass)} />
          {!collapsed && (
            <span className="font-mono text-[10px] uppercase tracking-[0.1em] text-muted-foreground">
              {statusLabel}
            </span>
          )}
        </div>

        <Separator className="opacity-50" />

        {/* Theme toggle */}
        <Button
          variant="ghost"
          size={collapsed ? "icon-xs" : "sm"}
          onClick={toggleTheme}
          className="w-full justify-start gap-2"
        >
          <div className="relative size-3.5">
            <Sun className="absolute size-3.5 rotate-0 scale-100 transition-all dark:-rotate-90 dark:scale-0" />
            <Moon className="absolute size-3.5 rotate-90 scale-0 transition-all dark:rotate-0 dark:scale-100" />
          </div>
          {!collapsed && (
            <span className="font-mono text-[10px] uppercase tracking-[0.1em]">
              {theme === "dark" ? "Dark" : "Light"}
            </span>
          )}
        </Button>

        {/* Collapse toggle */}
        <Button
          variant="ghost"
          size={collapsed ? "icon-xs" : "sm"}
          onClick={onToggleCollapse}
          className="w-full justify-start gap-2"
        >
          {collapsed ? (
            <ChevronRight className="size-3.5" />
          ) : (
            <>
              <ChevronLeft className="size-3.5" />
              <span className="font-mono text-[10px] uppercase tracking-[0.1em]">
                Collapse
              </span>
            </>
          )}
        </Button>
      </div>
    </aside>
  );
}
