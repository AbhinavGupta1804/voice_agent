import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  fetchCalls,
  fetchCallSummary,
  fetchCall,
  initiateCall,
  initiateBulkCalls,
  initiateBulkCallsFromCSV,
} from '@/lib/api';
import type {
  OutboundCallRequest,
  BulkOutboundCallRequest,
  CallRecord,
} from '@/lib/types';

// Query Keys
export const callsKeys = {
  all: ['calls'] as const,
  lists: () => [...callsKeys.all, 'list'] as const,
  list: (page: number, pageSize: number) =>
    [...callsKeys.lists(), { page, pageSize }] as const,
  summary: () => [...callsKeys.all, 'summary'] as const,
  details: () => [...callsKeys.all, 'detail'] as const,
  detail: (callId: string) => [...callsKeys.details(), callId] as const,
};

// ============ Query Hooks ============

export function useCalls(page: number = 1, pageSize: number = 20) {
  return useQuery({
    queryKey: callsKeys.list(page, pageSize),
    queryFn: () => fetchCalls(page, pageSize),
    staleTime: 30 * 1000, // 30 seconds
  });
}

export function useCallSummary() {
  return useQuery({
    queryKey: callsKeys.summary(),
    queryFn: fetchCallSummary,
    staleTime: 60 * 1000, // 1 minute
  });
}

export function useCall(callId: string) {
  return useQuery({
    queryKey: callsKeys.detail(callId),
    queryFn: () => fetchCall(callId),
    enabled: !!callId,
  });
}

// ============ Mutation Hooks ============

export function useInitiateCall() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (request: OutboundCallRequest) => initiateCall(request),
    onSuccess: () => {
      // Invalidate calls list to refresh data
      queryClient.invalidateQueries({ queryKey: callsKeys.lists() });
      queryClient.invalidateQueries({ queryKey: callsKeys.summary() });
    },
  });
}

export function useInitiateBulkCalls() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (request: BulkOutboundCallRequest) => initiateBulkCalls(request),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: callsKeys.lists() });
      queryClient.invalidateQueries({ queryKey: callsKeys.summary() });
    },
  });
}

export function useInitiateBulkCallsFromCSV() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (file: File) => initiateBulkCallsFromCSV(file),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: callsKeys.lists() });
      queryClient.invalidateQueries({ queryKey: callsKeys.summary() });
    },
  });
}

// ============ Cache Update Utilities ============

/**
 * Manually add a new call record to the cache (useful for WebSocket updates)
 */
export function useAddCallToCache() {
  const queryClient = useQueryClient();

  return (newCall: CallRecord) => {
    // Update all list queries
    queryClient.setQueriesData(
      { queryKey: callsKeys.lists() },
      (oldData: unknown) => {
        if (!oldData || typeof oldData !== 'object') return oldData;
        const typedData = oldData as { items: CallRecord[]; total: number };
        return {
          ...typedData,
          items: [newCall, ...typedData.items],
          total: typedData.total + 1,
        };
      }
    );

    // Invalidate summary
    queryClient.invalidateQueries({ queryKey: callsKeys.summary() });
  };
}

/**
 * Update an existing call record in the cache (useful for WebSocket updates)
 */
export function useUpdateCallInCache() {
  const queryClient = useQueryClient();

  return (updatedCall: CallRecord) => {
    // Update the specific call detail cache
    queryClient.setQueryData(callsKeys.detail(updatedCall.call_id), updatedCall);

    // Update all list queries
    queryClient.setQueriesData(
      { queryKey: callsKeys.lists() },
      (oldData: unknown) => {
        if (!oldData || typeof oldData !== 'object') return oldData;
        const typedData = oldData as { items: CallRecord[] };
        return {
          ...typedData,
          items: typedData.items.map((call) =>
            call.call_id === updatedCall.call_id ? updatedCall : call
          ),
        };
      }
    );

    // Invalidate summary
    queryClient.invalidateQueries({ queryKey: callsKeys.summary() });
  };
}

/**
 * Partially update a call record in the cache (e.g., just update recording_url)
 */
export function usePartialUpdateCallInCache() {
  const queryClient = useQueryClient();

  return (callId: string, updates: Partial<CallRecord>) => {
    // Update the specific call detail cache
    queryClient.setQueryData(
      callsKeys.detail(callId),
      (oldData: CallRecord | undefined) => {
        if (!oldData) return oldData;
        return { ...oldData, ...updates };
      }
    );

    // Update all list queries
    queryClient.setQueriesData(
      { queryKey: callsKeys.lists() },
      (oldData: unknown) => {
        if (!oldData || typeof oldData !== 'object') return oldData;
        const typedData = oldData as { items: CallRecord[] };
        return {
          ...typedData,
          items: typedData.items.map((call) =>
            call.call_id === callId ? { ...call, ...updates } : call
          ),
        };
      }
    );
  };
}

