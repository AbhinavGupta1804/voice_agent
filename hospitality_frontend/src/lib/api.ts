import type {
  PaginatedCallsResponse,
  PaginatedOrdersResponse,
  CallRecord,
  Order,
  OrdersSummary,
  CallsSummary,
  DailyRevenue,
  PopularItemsResponse,
} from './types';

// API Base URL
const API_BASE_URL =
  import.meta.env.VITE_API_URL ||
  'http://localhost:8000';

class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public data?: unknown
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

async function handleResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    throw new ApiError(
      response.status,
      errorData.detail || response.statusText,
      errorData
    );
  }
  return response.json();
}

// ============ Orders APIs ============

export async function fetchOrders(
  page: number = 1,
  pageSize: number = 20,
  status?: string
): Promise<PaginatedOrdersResponse> {
  const params = new URLSearchParams({
    page: page.toString(),
    page_size: pageSize.toString(),
  });
  if (status) {
    params.append('status', status);
  }
  
  const response = await fetch(`${API_BASE_URL}/api/orders?${params}`);
  return handleResponse<PaginatedOrdersResponse>(response);
}

export async function fetchPendingOrders(): Promise<PaginatedOrdersResponse> {
  const response = await fetch(`${API_BASE_URL}/api/orders/pending`);
  return handleResponse<PaginatedOrdersResponse>(response);
}

export async function fetchOrder(orderId: string): Promise<Order> {
  const response = await fetch(`${API_BASE_URL}/api/orders/${encodeURIComponent(orderId)}`);
  return handleResponse<Order>(response);
}

export async function updateOrder(
  orderId: string,
  updates: Partial<Order>
): Promise<Order> {
  const response = await fetch(`${API_BASE_URL}/api/orders/${encodeURIComponent(orderId)}`, {
    method: 'PATCH',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(updates),
  });
  return handleResponse<Order>(response);
}

export async function getTodayCompletedCount(): Promise<{ count: number }> {
  const response = await fetch(`${API_BASE_URL}/api/orders/stats/today-completed`);
  return handleResponse<{ count: number }>(response);
}

// ============ Call History APIs ============

export async function fetchCalls(
  page: number = 1,
  pageSize: number = 20
): Promise<PaginatedCallsResponse> {
  const params = new URLSearchParams({
    page: page.toString(),
    page_size: pageSize.toString(),
  });
  
  const response = await fetch(`${API_BASE_URL}/api/calls?${params}`);
  return handleResponse<PaginatedCallsResponse>(response);
}

export async function fetchCall(callId: string): Promise<CallRecord> {
  const response = await fetch(`${API_BASE_URL}/api/calls/${encodeURIComponent(callId)}`);
  return handleResponse<CallRecord>(response);
}

// ============ Analytics APIs ============

export async function fetchOrdersSummary(
  days: number = 7
): Promise<OrdersSummary> {
  const params = new URLSearchParams({ days: days.toString() });
  const response = await fetch(`${API_BASE_URL}/api/analytics/orders/summary?${params}`);
  return handleResponse<OrdersSummary>(response);
}

export async function fetchCallsSummary(
  days: number = 7
): Promise<CallsSummary> {
  const params = new URLSearchParams({ days: days.toString() });
  const response = await fetch(`${API_BASE_URL}/api/analytics/calls/summary?${params}`);
  return handleResponse<CallsSummary>(response);
}

export async function fetchDailyRevenue(
  days: number = 30
): Promise<DailyRevenue> {
  const params = new URLSearchParams({ days: days.toString() });
  const response = await fetch(`${API_BASE_URL}/api/analytics/revenue/daily?${params}`);
  return handleResponse<DailyRevenue>(response);
}

export async function fetchPopularItems(
  days: number = 30,
  limit: number = 10
): Promise<PopularItemsResponse> {
  const params = new URLSearchParams({
    days: days.toString(),
    limit: limit.toString(),
  });
  const response = await fetch(`${API_BASE_URL}/api/analytics/popular-items?${params}`);
  return handleResponse<PopularItemsResponse>(response);
}

// ============ WebSocket URL ============

export function getWebSocketUrl(): string {
  const explicitWs = import.meta.env.VITE_WS_URL as string | undefined;
  if (explicitWs) return explicitWs;

  const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const apiUrl = new URL(API_BASE_URL);
  return `${wsProtocol}//${apiUrl.host}/api/dashboard/ws`;
}

// Export the API base URL for other uses
export { API_BASE_URL, ApiError };

