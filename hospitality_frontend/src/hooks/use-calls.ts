import { useQuery } from "@tanstack/react-query";
import { fetchCalls, fetchCall, type CallRecord, type PaginatedCallsResponse } from "@/lib/api";

export function useCalls(page: number = 1, pageSize: number = 20) {
  return useQuery({
    queryKey: ["calls", page, pageSize],
    queryFn: () => fetchCalls(page, pageSize),
  });
}

export function useCall(callId: string) {
  return useQuery({
    queryKey: ["calls", callId],
    queryFn: () => fetchCall(callId),
    enabled: !!callId,
  });
}
