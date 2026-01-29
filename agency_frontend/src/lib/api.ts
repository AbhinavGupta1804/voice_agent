import type {
  PaginatedCallsResponse,
  CallSummaryResponse,
  CallRecord,
  OutboundCallRequest,
  InitiateCallResponse,
  BulkOutboundCallRequest,
  BulkOutboundCallResponse,
  AnalyticsData,
} from './types';

// API Base URL - supports both VITE_API_URL (preferred) and VITE_API_BASE_URL (legacy)
const API_BASE_URL =
  import.meta.env.VITE_API_URL ||
  import.meta.env.VITE_API_BASE_URL ||
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
  console.log(response);
  return handleResponse<PaginatedCallsResponse>(response);
}

export async function fetchCallSummary(): Promise<CallSummaryResponse> {
  const response = await fetch(`${API_BASE_URL}/api/calls/summary`);
  return handleResponse<CallSummaryResponse>(response);
}

export async function fetchCall(callId: string): Promise<CallRecord> {
  const response = await fetch(`${API_BASE_URL}/api/call/${encodeURIComponent(callId)}`);
  const data = await handleResponse<CallRecord>(response);
  console.log("Fetched call data:", data);
  return data;
}

// ============ Outbound Call APIs ============

export async function initiateCall(
  request: OutboundCallRequest
): Promise<InitiateCallResponse> {
  console.log("Initiating call with request:", request);
  const response = await fetch(`${API_BASE_URL}/api/initiate_call`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(request),
  });
  console.log("Response:", response);
  return handleResponse<InitiateCallResponse>(response);
}

export async function initiateBulkCalls(
  request: BulkOutboundCallRequest
): Promise<BulkOutboundCallResponse> {
  const response = await fetch(`${API_BASE_URL}/api/outbound-calls/bulk`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(request),
  });
  return handleResponse<BulkOutboundCallResponse>(response);
}

export async function initiateBulkCallsFromCSV(
  file: File
): Promise<BulkOutboundCallResponse> {
  const formData = new FormData();
  formData.append('file', file);
  
  const response = await fetch(`${API_BASE_URL}/api/outbound-calls/bulk-csv`, {
    method: 'POST',
    body: formData,
  });
  return handleResponse<BulkOutboundCallResponse>(response);
}

// ============ Analytics APIs ============

export async function fetchAnalytics(
  period: 'week' | 'month' | 'quarter' | 'year' = 'week'
): Promise<AnalyticsData> {
  const params = new URLSearchParams({ period });
  const response = await fetch(`${API_BASE_URL}/api/analytics?${params}`);
  return handleResponse<AnalyticsData>(response);
}

// ============ WebSocket URL ============

export function getWebSocketUrl(): string {
  const explicitWs = import.meta.env.VITE_WS_URL as string | undefined;
  if (explicitWs) return explicitWs;

  const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const apiUrl = new URL(API_BASE_URL);
  return `${wsProtocol}//${apiUrl.host}/ws/dashboard`;
}

// Export the API base URL for other uses
export { API_BASE_URL, ApiError };

