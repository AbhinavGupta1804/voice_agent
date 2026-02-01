import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  fetchConversationThreads,
  fetchThreadMessages,
  sendConversationMessage,
} from '@/lib/api';
import type { ConversationChannel } from '@/lib/types';

export const conversationKeys = {
  all: ['conversations'] as const,
  threads: (channel: ConversationChannel) =>
    [...conversationKeys.all, 'threads', channel] as const,
  thread: (threadId: number) =>
    [...conversationKeys.all, 'thread', threadId] as const,
  messages: (threadId: number) =>
    [...conversationKeys.all, 'messages', threadId] as const,
};

export function useConversationThreads(
  channel: ConversationChannel,
  page: number = 1,
  pageSize: number = 50
) {
  return useQuery({
    queryKey: [...conversationKeys.threads(channel), { page, pageSize }],
    queryFn: () => fetchConversationThreads(channel, page, pageSize),
    enabled: !!channel,
    staleTime: 15 * 1000,
  });
}

export function useThreadMessages(threadId: number | null, limit: number = 100) {
  return useQuery({
    queryKey: conversationKeys.messages(threadId ?? 0),
    queryFn: () => fetchThreadMessages(threadId!, limit),
    enabled: threadId != null && threadId > 0,
    staleTime: 5 * 1000,
  });
}

export function useSendConversationMessage(threadId: number | null) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: string) => sendConversationMessage(threadId!, body),
    onSuccess: (_, __, context) => {
      if (threadId != null)
        queryClient.invalidateQueries({ queryKey: conversationKeys.messages(threadId) });
      queryClient.invalidateQueries({ queryKey: conversationKeys.all });
    },
  });
}
