import { useQuery } from '@tanstack/react-query';
import { fetchAnalytics } from '@/lib/api';

// Query Keys
export const analyticsKeys = {
  all: ['analytics'] as const,
  data: (period: string) => [...analyticsKeys.all, period] as const,
};

type AnalyticsPeriod = 'week' | 'month' | 'quarter' | 'year';

/**
 * Hook to fetch analytics data.
 * Note: This hook is prepared but not connected to the Analytics page yet.
 * Will be connected later as per user request.
 */
export function useAnalytics(period: AnalyticsPeriod = 'week') {
  return useQuery({
    queryKey: analyticsKeys.data(period),
    queryFn: () => fetchAnalytics(period),
    staleTime: 5 * 60 * 1000, // 5 minutes
    enabled: true,
  });
}

