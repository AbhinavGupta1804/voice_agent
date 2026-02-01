// API Response and Request Types

export interface InsightModel {
  topics: string[];
  duration_sec: number;
}

export interface NotificationPreferences {
  notify_email: boolean;
  notify_whatsapp: boolean;
  email_address: string | null;
  whatsapp_number: string | null;
  email_sent: boolean;
  whatsapp_sent: boolean;
}

export interface CallRecord {
  call_id: string;
  client_name: string;
  transcript: string;
  insights: InsightModel;
  conversion_status: boolean;
   sentiment: "positive" | "neutral" | "negative" | null;
  timestamp: string;
  summary: string | null;
  follow_up_date: string | null;
  notification_preferences: NotificationPreferences | null;
  phone_number: string | null;
  recording_url: string | null;
  call_type: "inbound" | "outbound" | null;
}

export interface PaginatedCallsResponse {
  page: number;
  page_size: number;
  total: number;
  items: CallRecord[];
}

export interface CallSummaryResponse {
  total_calls: number;
  conversions: number;
  conversion_rate: number;
}

// Request Types
export interface OutboundCallRequest {
  number: string;
  client_name: string;
}

export interface CallRecipient {
  number: string;
  client_name: string;
}

export interface BulkOutboundCallRequest {
  recipients: CallRecipient[];
}

export interface CallResult {
  success: boolean;
  call_sid: string | null;
  client_name: string;
  phone_number: string;
  error: string | null;
}

export interface BulkOutboundCallResponse {
  total_requested: number;
  successful: number;
  failed: number;
  results: CallResult[];
}

export interface InitiateCallResponse {
  success: boolean;
  message: string;
  callSid: string;
  clientName: string;
  phoneNumber: string;
}

// WebSocket Message Types
export interface WebSocketMessage {
  event: string;
  data: Record<string, unknown>;
}

export interface CallInProgressData {
  call_sid: string;
  client_name: string;
  phone_number: string;
  status: string;
}

export interface CallCompletedData extends CallRecord {}

export interface CallAudioReadyData {
  call_id: string;
  recording_url: string;
}

export interface CallFailedData {
  agent_id: string;
  conversation_id: string;
  failure_reason: string;
  metadata: Record<string, unknown>;
}

// Analytics Types (for future use)
export interface AnalyticsOverview {
  total_calls: number;
  avg_duration_sec: number;
  conversion_rate: number;
  sentiment_score: number;
  total_calls_change: number;
  avg_duration_change: number;
  conversion_rate_change: number;
  sentiment_change: number;
}

export interface CallsOverTimeData {
  date: string;
  calls: number;
}

export interface ConversionRateData {
  date: string;
  rate: number;
}

export interface CallDurationData {
  range: string;
  count: number;
}

export interface InquiryTypeData {
  name: string;
  value: number;
  color: string;
}

export interface FollowUpStatusData {
  month: string;
  scheduled: number;
  completed: number;
  missed: number;
}

export interface FunnelData {
  name: string;
  value: number;
  fill: string;
}

export interface SentimentData {
  call_id: string;
  score: number;
}

export interface AnalyticsData {
  overview: AnalyticsOverview;
  calls_over_time: CallsOverTimeData[];
  conversion_rate_trend: ConversionRateData[];
  call_duration_distribution: CallDurationData[];
  inquiry_types: InquiryTypeData[];
  follow_up_status: FollowUpStatusData[];
  conversion_funnel: FunnelData[];
  sentiment_scores: SentimentData[];
}

// Scheduled follow-up (from GET /api/follow-ups)
export interface ScheduledFollowUp {
  id: number;
  call_id: string;
  phone_number: string;
  client_name: string | null;
  scheduled_at: string;
  status: "pending" | "processing" | "completed" | "failed" | "cancelled" | "not_picked";
  retry_count: number;
  max_retries: number;
  last_error: string | null;
  context: Record<string, unknown> | null;
  created_at: string | null;
  executed_at: string | null;
}

export interface PaginatedFollowUpsResponse {
  page: number;
  page_size: number;
  total: number;
  items: ScheduledFollowUp[];
}

// Conversation (WhatsApp/SMS/Email) threads and messages
export type ConversationChannel = "whatsapp" | "sms" | "email";
export type MessageSenderType = "bot" | "client" | "user";

export interface ConversationThread {
  id: number;
  phone_number: string | null;
  channel: ConversationChannel;
  display_name: string | null;
  email_address: string | null;
  created_at: string;
  updated_at: string;
}

export interface ConversationMessage {
  id: number;
  thread_id: number;
  body: string;
  direction: "inbound" | "outbound";
  sender_type: MessageSenderType;
  twilio_message_sid: string | null;
  created_at: string;
}

export interface PaginatedThreadsResponse {
  page: number;
  page_size: number;
  total: number;
  items: ConversationThread[];
}

export interface ThreadMessagesResponse {
  thread_id: number;
  messages: ConversationMessage[];
}

