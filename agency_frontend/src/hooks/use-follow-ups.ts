import { useQuery } from '@tanstack/react-query';
import { fetchFollowUps } from '@/lib/api';

export const followUpsKeys = {
  all: ['follow-ups'] as const,
  lists: () => [...followUpsKeys.all, 'list'] as const,
  list: (page: number, pageSize: number, status?: string) =>
    [...followUpsKeys.lists(), { page, pageSize, status }] as const,
};

export function useFollowUps(
  page: number = 1,
  pageSize: number = 20,
  status?: string
) {
  return useQuery({
    queryKey: followUpsKeys.list(page, pageSize, status),
    queryFn: () => fetchFollowUps(page, pageSize, status),
    staleTime: 30 * 1000,
  });
}
