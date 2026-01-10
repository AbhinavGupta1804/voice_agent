import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  fetchOrders,
  fetchPendingOrders,
  fetchOrder,
  updateOrder,
  getTodayCompletedCount,
  type Order,
  type PaginatedOrdersResponse,
} from "@/lib/api";

export function useOrders(page: number = 1, pageSize: number = 20, status?: string) {
  return useQuery({
    queryKey: ["orders", page, pageSize, status],
    queryFn: () => fetchOrders(page, pageSize, status),
  });
}

export function usePendingOrders() {
  return useQuery({
    queryKey: ["orders", "pending"],
    queryFn: () => fetchPendingOrders(),
  });
}

export function useOrder(orderId: string) {
  return useQuery({
    queryKey: ["orders", orderId],
    queryFn: () => fetchOrder(orderId),
    enabled: !!orderId,
  });
}

export function useUpdateOrder() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ orderId, updates }: { orderId: string; updates: Partial<Order> }) =>
      updateOrder(orderId, updates),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ["orders"] });
      queryClient.setQueryData(["orders", data.order_id], data);
    },
  });
}

export function useTodayCompletedCount() {
  return useQuery({
    queryKey: ["orders", "stats", "today-completed"],
    queryFn: () => getTodayCompletedCount(),
  });
}

