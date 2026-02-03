import { useState } from "react";
import {
  Phone,
  RefreshCw,
  User,
  Calendar,
  Clock,
  AlertCircle,
  ChevronLeft,
  ChevronRight,
  PhoneCall,
  FileText,
} from "lucide-react";
import { DashboardLayout } from "@/components/layout/DashboardLayout";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useFollowUps } from "@/hooks/use-follow-ups";
import type { ScheduledFollowUp } from "@/lib/types";

const PAGE_SIZE = 10;
const STATUS_OPTIONS = [
  { value: "all", label: "All" },
  { value: "pending", label: "Pending" },
  { value: "processing", label: "Processing" },
  { value: "completed", label: "Completed" },
  { value: "failed", label: "Failed" },
  { value: "not_picked", label: "Not picked" },
  { value: "cancelled", label: "Cancelled" },
];

function formatDateTime(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
  });
}

function statusVariant(
  status: ScheduledFollowUp["status"]
): "default" | "secondary" | "destructive" | "outline" {
  switch (status) {
    case "completed":
      return "default";
    case "failed":
    case "cancelled":
    case "not_picked":
      return "destructive";
    case "processing":
      return "secondary";
    default:
      return "outline";
  }
}

function getContextSummary(ctx: Record<string, unknown> | null): string {
  if (!ctx) return "—";
  const reason = ctx.reason as string | undefined;
  const summary = ctx.summary as string | undefined;
  const failure = ctx.failure_reason as string | undefined;
  if (reason === "no_answer" && failure) return `No answer: ${failure}`;
  if (summary) return String(summary).slice(0, 80);
  if (reason) return String(reason);
  return "—";
}

export default function FollowUps() {
  const [page, setPage] = useState(1);
  const [statusFilter, setStatusFilter] = useState<string>("all");

  const {
    data: followUpsData,
    isLoading,
    error,
    refetch,
    isFetching,
  } = useFollowUps(
    page,
    PAGE_SIZE,
    statusFilter && statusFilter !== "all" ? statusFilter : undefined
  );

  const totalPages = followUpsData
    ? Math.ceil(followUpsData.total / PAGE_SIZE) || 1
    : 1;
  const from = followUpsData ? (page - 1) * PAGE_SIZE + 1 : 0;
  const to = followUpsData
    ? Math.min(page * PAGE_SIZE, followUpsData.total)
    : 0;

  return (
    <DashboardLayout>
      <div className="w-full max-w-[1400px]">
        <header className="mb-8">
          <div className="flex items-center justify-between flex-wrap gap-4">
            <div>
              <h1 className="text-3xl font-bold text-foreground flex items-center gap-2">
                <PhoneCall className="h-8 w-8" />
                Follow-ups
              </h1>
              <p className="text-muted-foreground mt-2">
                Scheduled callbacks from no-answer and customer-requested follow-ups
              </p>
            </div>
            <div className="flex items-center gap-3">
              <Button
                variant="outline"
                size="sm"
                onClick={() => refetch()}
                disabled={isFetching}
              >
                <RefreshCw
                  className={`h-4 w-4 mr-2 ${isFetching ? "animate-spin" : ""}`}
                />
                Refresh
              </Button>
            </div>
          </div>
        </header>

        {/* Filters & summary */}
        <div className="flex flex-wrap items-center justify-between gap-4 mb-6">
          <div className="flex items-center gap-4">
            <Select
              value={statusFilter}
              onValueChange={(v) => {
                setStatusFilter(v);
                setPage(1);
              }}
            >
              <SelectTrigger className="w-[180px]">
                <SelectValue placeholder="Status" />
              </SelectTrigger>
              <SelectContent>
                {STATUS_OPTIONS.map((opt) => (
                  <SelectItem key={opt.value} value={opt.value}>
                    {opt.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {followUpsData && (
              <p className="text-sm text-muted-foreground">
                {followUpsData.total} follow-up{followUpsData.total !== 1 ? "s" : ""} total
              </p>
            )}
          </div>

          {/* Top Pagination */}
          {!isLoading && followUpsData && followUpsData.total > PAGE_SIZE && (
            <div className="flex items-center gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                disabled={page <= 1}
              >
                <ChevronLeft className="h-4 w-4" />
              </Button>
              <span className="text-sm font-medium">
                {page} / {totalPages}
              </span>
              <Button
                variant="outline"
                size="sm"
                onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                disabled={page >= totalPages}
              >
                <ChevronRight className="h-4 w-4" />
              </Button>
            </div>
          )}
        </div>

        {/* Error */}
        {error && (
          <div className="bg-destructive/10 text-destructive rounded-xl p-6 mb-8 text-center">
            <p className="font-medium">Failed to load follow-ups</p>
            <p className="text-sm mt-1 opacity-80">
              {error instanceof Error ? error.message : "Unknown error"}
            </p>
            <Button variant="outline" size="sm" className="mt-4" onClick={() => refetch()}>
              Try Again
            </Button>
          </div>
        )}

        {/* Table / list */}
        <div className="bg-card rounded-2xl shadow-card overflow-hidden">
          <div className="p-6 border-b border-border flex items-center justify-between flex-wrap gap-4">
            <h2 className="font-semibold text-card-foreground">Scheduled follow-ups</h2>
            {followUpsData && followUpsData.total > 0 && (
              <p className="text-sm text-muted-foreground">
                Showing {from}–{to} of {followUpsData.total}
              </p>
            )}
          </div>

          {isLoading && (
            <div className="divide-y divide-border p-4">
              {[...Array(5)].map((_, i) => (
                <div key={i} className="p-4 flex items-center gap-4">
                  <Skeleton className="h-12 w-12 rounded-full" />
                  <div className="flex-1">
                    <Skeleton className="h-4 w-32 mb-2" />
                    <Skeleton className="h-3 w-48" />
                  </div>
                  <Skeleton className="h-6 w-20" />
                </div>
              ))}
            </div>
          )}

          {!isLoading && followUpsData?.items.length === 0 && (
            <div className="p-12 text-center">
              <PhoneCall className="h-12 w-12 mx-auto text-muted-foreground mb-4" />
              <p className="text-lg font-medium text-card-foreground">
                No follow-ups
              </p>
              <p className="text-sm text-muted-foreground mt-1">
                Follow-ups appear here when a call is not answered or when a customer asks to be called back.
              </p>
            </div>
          )}

          {!isLoading && followUpsData && followUpsData.items.length > 0 && (
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr className="border-b border-border bg-muted/30">
                    <th className="text-left py-3 px-4 text-sm font-medium text-muted-foreground">
                      ID
                    </th>
                    <th className="text-left py-3 px-4 text-sm font-medium text-muted-foreground">
                      Client
                    </th>
                    <th className="text-left py-3 px-4 text-sm font-medium text-muted-foreground">
                      Phone
                    </th>
                    <th className="text-left py-3 px-4 text-sm font-medium text-muted-foreground">
                      Scheduled at
                    </th>
                    <th className="text-left py-3 px-4 text-sm font-medium text-muted-foreground">
                      Status
                    </th>
                    <th className="text-left py-3 px-4 text-sm font-medium text-muted-foreground">
                      Retries
                    </th>
                    <th className="text-left py-3 px-4 text-sm font-medium text-muted-foreground">
                      Context / Reason
                    </th>
                    <th className="text-left py-3 px-4 text-sm font-medium text-muted-foreground">
                      Last error
                    </th>
                    <th className="text-left py-3 px-4 text-sm font-medium text-muted-foreground">
                      Created / Executed
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {followUpsData.items.map((fu) => (
                    <tr
                      key={fu.id}
                      className="border-b border-border hover:bg-accent/20 transition-colors"
                    >
                      <td className="py-3 px-4">
                        <span className="font-mono text-sm text-muted-foreground">
                          #{fu.id}
                        </span>
                      </td>
                      <td className="py-3 px-4">
                        <div className="flex items-center gap-2">
                          <User className="h-4 w-4 text-muted-foreground" />
                          <span className="font-medium text-foreground">
                            {fu.client_name || "—"}
                          </span>
                        </div>
                        <div className="text-xs text-muted-foreground font-mono mt-0.5">
                          {fu.call_id}
                        </div>
                      </td>
                      <td className="py-3 px-4">
                        <div className="flex items-center gap-1.5 text-sm">
                          <Phone className="h-3.5 w-3 text-muted-foreground" />
                          {fu.phone_number}
                        </div>
                      </td>
                      <td className="py-3 px-4">
                        <div className="flex items-center gap-1.5 text-sm">
                          <Calendar className="h-3.5 w-3 text-muted-foreground" />
                          {formatDateTime(fu.scheduled_at)}
                        </div>
                      </td>
                      <td className="py-3 px-4">
                        <Badge variant={statusVariant(fu.status)}>
                          {fu.status}
                        </Badge>
                      </td>
                      <td className="py-3 px-4 text-sm text-muted-foreground">
                        {fu.retry_count} / {fu.max_retries}
                      </td>
                      <td className="py-3 px-4 max-w-[200px]">
                        <div className="flex items-start gap-1.5 text-sm">
                          <FileText className="h-3.5 w-3 text-muted-foreground mt-0.5 shrink-0" />
                          <span className="line-clamp-2 text-muted-foreground">
                            {getContextSummary(fu.context)}
                          </span>
                        </div>
                      </td>
                      <td className="py-3 px-4 max-w-[180px]">
                        {fu.last_error ? (
                          <div className="flex items-start gap-1.5 text-sm text-destructive">
                            <AlertCircle className="h-3.5 w-3 mt-0.5 shrink-0" />
                            <span className="line-clamp-2">{fu.last_error}</span>
                          </div>
                        ) : (
                          <span className="text-muted-foreground">—</span>
                        )}
                      </td>
                      <td className="py-3 px-4 text-sm text-muted-foreground">
                        <div className="flex items-center gap-1">
                          <Clock className="h-3.5 w-3" />
                          {formatDateTime(fu.created_at)}
                        </div>
                        {fu.executed_at && (
                          <div className="text-xs mt-1">
                            Executed: {formatDateTime(fu.executed_at)}
                          </div>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}


        </div>
      </div>
    </DashboardLayout>
  );
}
