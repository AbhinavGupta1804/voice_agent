// Types for the hospitality application

export interface OrderItem {
  name: string;
  quantity: number;
  price?: number;
  notes?: string;
}

export interface Order {
  order_id: string;
  caller_name: string;
  caller_phone: string;
  items: OrderItem[];
  status: 'pending' | 'preparing' | 'ready' | 'completed' | 'cancelled';
  estimated_time_minutes?: number;
  order_timestamp: string;
  completed_at?: string;
  call_id?: string;
  notes?: string;
  total_amount?: number;
}

export interface PaginatedOrdersResponse {
  page: number;
  page_size: number;
  total: number;
  items: Order[];
}

export interface CallRecord {
  call_id: string;
  caller_name?: string;
  caller_phone?: string;
  transcript?: string;
  summary?: string;
  order_id?: string;
  duration_sec: number;
  call_timestamp: string;
  recording_url?: string;
  sentiment?: string;
}

export interface PaginatedCallsResponse {
  page: number;
  page_size: number;
  total: number;
  items: CallRecord[];
}

export interface OrdersSummary {
  period_days: number;
  total_orders: number;
  orders_by_status: Record<string, number>;
  total_revenue: number;
  average_order_value: number;
  orders_per_day: Array<{ date: string; count: number }>;
}

export interface CallsSummary {
  period_days: number;
  total_calls: number;
  calls_with_orders: number;
  conversion_rate: number;
  average_duration_sec: number;
  calls_per_day: Array<{ date: string; count: number }>;
}

export interface DailyRevenue {
  period_days: number;
  daily_revenue: Array<{
    date: string;
    order_count: number;
    revenue: number;
  }>;
}

export interface PopularItem {
  name: string;
  total_quantity: number;
}

export interface PopularItemsResponse {
  period_days: number;
  popular_items: PopularItem[];
}

