import { useState, useRef, useEffect } from "react";
import {
  MessageSquare,
  Send,
  User,
  Loader2,
  Phone,
  MessageCircle,
  ChevronRight,
  Mail,
} from "lucide-react";
import { DashboardLayout } from "@/components/layout/DashboardLayout";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useQueryClient } from "@tanstack/react-query";
import { useConversationThreads, useThreadMessages, useSendConversationMessage, conversationKeys } from "@/hooks/use-conversations";
import { useDashboardWebSocket } from "@/hooks/use-websocket";
import type { ConversationThread, ConversationMessage, ConversationChannel } from "@/lib/types";

function formatTime(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit", hour12: true });
}

function MessageBubble({
  msg,
  isOutbound,
}: {
  msg: ConversationMessage;
  isOutbound: boolean;
}) {
  // Treat missing direction as inbound so customer messages always show (e.g. legacy DB rows)
  const direction = msg.direction ?? "inbound";
  const senderLabel =
    direction === "inbound"
      ? "Customer"
      : (msg.sender_type === "bot" ? "Sent by bot" : "Sent by you");

  return (
    <div
      className={`flex flex-col max-w-[85%] ${isOutbound ? "ml-auto items-end" : "mr-auto items-start"}`}
    >
      <div
        className={`rounded-2xl px-4 py-2.5 ${
          isOutbound
            ? "bg-primary text-primary-foreground rounded-br-md"
            : "bg-muted text-foreground rounded-bl-md"
        }`}
      >
        <p className="text-sm whitespace-pre-wrap break-words">{msg.body}</p>
      </div>
      <span
        className={`text-xs mt-1 text-muted-foreground italic ${
          isOutbound ? "text-right" : "text-left"
        }`}
      >
        {senderLabel} · {formatTime(msg.created_at)}
      </span>
    </div>
  );
}

export default function Chat() {
  const queryClient = useQueryClient();
  const [channel, setChannel] = useState<ConversationChannel>("whatsapp");
  const [selectedThread, setSelectedThread] = useState<ConversationThread | null>(null);
  const [sendText, setSendText] = useState("");
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const { data: threadsData, isLoading: threadsLoading } = useConversationThreads(
    channel,
    1,
    50
  );
  const { data: messagesData, isLoading: messagesLoading } = useThreadMessages(
    selectedThread?.id ?? null
  );
  const sendMessage = useSendConversationMessage(selectedThread?.id ?? null);

  // Refetch messages and threads when a new conversation message arrives (inbound or bot reply)
  useDashboardWebSocket({
    onConversationMessage: (data) => {
      queryClient.invalidateQueries({ queryKey: conversationKeys.messages(data.thread_id) });
      queryClient.invalidateQueries({ queryKey: conversationKeys.all });
    },
  });

  const threads = threadsData?.items ?? [];
  const messages = messagesData?.messages ?? [];

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const handleSend = async () => {
    const body = sendText.trim();
    if (!body || !selectedThread) return;
    try {
      await sendMessage.mutateAsync(body);
      setSendText("");
    } catch {
      // toast or inline error
    }
  }

  return (
    <DashboardLayout>
      <div className="flex flex-col h-[calc(100vh-4rem)] w-full max-w-[1400px] mx-auto">
        <header className="mb-4">
          <h1 className="text-2xl font-bold text-foreground flex items-center gap-2">
            <MessageSquare className="h-7 w-7" />
            Chat
          </h1>
          <p className="text-muted-foreground text-sm mt-1">
            WhatsApp, SMS, and email conversations with your users. Bot replies automatically; you can jump in anytime.
          </p>
        </header>

        {/* Channel toggle: WhatsApp | SMS | Email */}
        <Tabs
          value={channel}
          onValueChange={(v) => {
            setChannel(v as ConversationChannel);
            setSelectedThread(null);
          }}
          className="mb-4"
        >
          <TabsList className="grid w-full max-w-[360px] grid-cols-3">
            <TabsTrigger value="whatsapp" className="flex items-center gap-2">
              <MessageCircle className="h-4 w-4" />
              WhatsApp
            </TabsTrigger>
            <TabsTrigger value="sms" className="flex items-center gap-2">
              <Phone className="h-4 w-4" />
              SMS
            </TabsTrigger>
            <TabsTrigger value="email" className="flex items-center gap-2">
              <Mail className="h-4 w-4" />
              Email
            </TabsTrigger>
          </TabsList>
        </Tabs>

        <div className="flex flex-1 min-h-0 border border-border rounded-xl bg-card overflow-hidden">
          {/* Thread list */}
          <aside className="w-72 border-r border-border flex flex-col bg-muted/30">
            <div className="p-2 border-b border-border text-sm font-medium text-foreground">
              Threads
            </div>
            <ScrollArea className="flex-1">
              {threadsLoading && (
                <div className="p-4 space-y-2">
                  {[1, 2, 3].map((i) => (
                    <Skeleton key={i} className="h-14 w-full rounded-lg" />
                  ))}
                </div>
              )}
              {!threadsLoading && threads.length === 0 && (
                <div className="p-6 text-center text-muted-foreground text-sm">
                  No conversations yet. Messages will appear here when users reply on {channel}.
                </div>
              )}
              {!threadsLoading &&
                threads.map((t) => (
                  <button
                    key={t.id}
                    onClick={() => setSelectedThread(t)}
                    className={`w-full flex items-center gap-3 px-4 py-3 text-left border-b border-border/50 hover:bg-accent/50 transition-colors ${
                      selectedThread?.id === t.id ? "bg-accent" : ""
                    }`}
                  >
                    <div className="h-10 w-10 rounded-full bg-primary/10 flex items-center justify-center shrink-0">
                      <User className="h-5 w-5 text-primary" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="font-medium text-foreground truncate">
                        {t.display_name || (t.channel === "email" ? t.email_address : t.phone_number) || "—"}
                      </p>
                      <p className="text-xs text-muted-foreground truncate">
                        {t.channel === "email" ? (t.email_address ?? "") : (t.phone_number ? `+${t.phone_number}` : "")}
                      </p>
                    </div>
                    <ChevronRight className="h-4 w-4 text-muted-foreground shrink-0" />
                  </button>
                ))}
            </ScrollArea>
          </aside>

          {/* Message area */}
          <div className="flex-1 flex flex-col min-w-0">
            {!selectedThread && (
              <div className="flex-1 flex items-center justify-center text-muted-foreground">
                <p className="text-sm">Select a thread to view the conversation</p>
              </div>
            )}
            {selectedThread && (
              <>
                <div className="p-3 border-b border-border flex items-center gap-2">
                  <User className="h-5 w-5 text-muted-foreground" />
                  <span className="font-medium text-foreground">
                    {selectedThread.display_name || (selectedThread.channel === "email" ? selectedThread.email_address : selectedThread.phone_number) || "—"}
                  </span>
                  <span className="text-xs text-muted-foreground">
                    {selectedThread.channel === "email"
                      ? selectedThread.email_address ?? ""
                      : selectedThread.phone_number ? `+${selectedThread.phone_number}` : ""}
                  </span>
                </div>
                <ScrollArea className="flex-1 p-4">
                  {messagesLoading && (
                    <div className="space-y-4">
                      {[1, 2, 3].map((i) => (
                        <Skeleton key={i} className="h-16 w-3/4 rounded-lg" />
                      ))}
                    </div>
                  )}
                  {!messagesLoading && messages.length === 0 && (
                    <p className="text-sm text-muted-foreground text-center py-8">
                      No messages yet. When the user or bot sends a message, it will appear here.
                    </p>
                  )}
                  {!messagesLoading &&
                    messages.length > 0 &&
                    messages.map((msg) => (
                      <div key={msg.id} className="mb-4">
                        <MessageBubble
                          msg={msg}
                          isOutbound={(msg.direction ?? "inbound") === "outbound"}
                        />
                      </div>
                    ))}
                  <div ref={messagesEndRef} />
                </ScrollArea>
                <div className="p-4 border-t border-border flex gap-2">
                  <input
                    type="text"
                    placeholder="Type a message..."
                    value={sendText}
                    onChange={(e) => setSendText(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && !e.shiftKey) {
                        e.preventDefault();
                        handleSend();
                      }
                    }}
                    className="flex-1 rounded-lg border border-input bg-background px-4 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                  />
                  <Button
                    size="icon"
                    onClick={handleSend}
                    disabled={!sendText.trim() || sendMessage.isPending}
                  >
                    {sendMessage.isPending ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <Send className="h-4 w-4" />
                    )}
                  </Button>
                </div>
              </>
            )}
          </div>
        </div>
      </div>
    </DashboardLayout>
  );
}
