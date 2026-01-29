import { useState, useEffect, useRef } from "react";
import {
  Phone,
  Clock,
  Calendar,
  ArrowUpRight,
  User,
  Loader2,
  RefreshCw,
  ChevronLeft,
  ChevronRight,
  Wifi,
  WifiOff,
  Play,
  Pause,
  Volume2,
  VolumeX,
  Download,
  ArrowDownLeft,
  ArrowUpCircle,
} from "lucide-react";
import { DashboardLayout } from "@/components/layout/DashboardLayout";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useCalls, useCallSummary, useCall, useUpdateCallInCache, usePartialUpdateCallInCache } from "@/hooks/use-calls";
import { useDashboardWebSocket } from "@/hooks/use-websocket";
import type { CallRecord, CallInProgressData, CallCompletedData, CallAudioReadyData } from "@/lib/types";
import { toast } from "@/hooks/use-toast";

const PAGE_SIZE = 20;

// Custom Audio Player Component - matches UI design system
function AudioPlayer({ audioUrl }: { audioUrl: string }) {
  const audioRef = useRef<HTMLAudioElement>(null);
  const [isPlaying, setIsPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [volume, setVolume] = useState(1);
  const [isMuted, setIsMuted] = useState(false);

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;

    const updateTime = () => setCurrentTime(audio.currentTime);
    const updateDuration = () => setDuration(audio.duration);
    const handlePlay = () => setIsPlaying(true);
    const handlePause = () => setIsPlaying(false);
    const handleEnded = () => setIsPlaying(false);

    audio.addEventListener('timeupdate', updateTime);
    audio.addEventListener('loadedmetadata', updateDuration);
    audio.addEventListener('play', handlePlay);
    audio.addEventListener('pause', handlePause);
    audio.addEventListener('ended', handleEnded);

    return () => {
      audio.removeEventListener('timeupdate', updateTime);
      audio.removeEventListener('loadedmetadata', updateDuration);
      audio.removeEventListener('play', handlePlay);
      audio.removeEventListener('pause', handlePause);
      audio.removeEventListener('ended', handleEnded);
    };
  }, []);

  const togglePlay = () => {
    const audio = audioRef.current;
    if (!audio) return;

    if (isPlaying) {
      audio.pause();
    } else {
      audio.play();
    }
  };

  const handleSeek = (e: React.ChangeEvent<HTMLInputElement>) => {
    const audio = audioRef.current;
    if (!audio) return;

    const newTime = parseFloat(e.target.value);
    audio.currentTime = newTime;
    setCurrentTime(newTime);
  };

  const handleVolumeChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const audio = audioRef.current;
    if (!audio) return;

    const newVolume = parseFloat(e.target.value);
    audio.volume = newVolume;
    setVolume(newVolume);
    setIsMuted(newVolume === 0);
  };

  const toggleMute = () => {
    const audio = audioRef.current;
    if (!audio) return;

    if (isMuted) {
      audio.volume = volume || 0.5;
      setIsMuted(false);
    } else {
      audio.volume = 0;
      setIsMuted(true);
    }
  };

  const formatTime = (seconds: number): string => {
    if (isNaN(seconds)) return "0:00";
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}:${secs.toString().padStart(2, '0')}`;
  };

  return (
    <div className="bg-accent/30 rounded-lg p-4 space-y-3">
      {/* Hidden audio element */}
      <audio ref={audioRef} src={audioUrl} preload="metadata" />
      
      {/* Controls */}
      <div className="flex items-center gap-3">
        {/* Play/Pause Button */}
        <Button
          variant="outline"
          size="icon"
          onClick={togglePlay}
          className="h-10 w-10 rounded-full shrink-0"
        >
          {isPlaying ? (
            <Pause className="h-4 w-4" />
          ) : (
            <Play className="h-4 w-4" />
          )}
        </Button>

        {/* Time Display */}
        <div className="text-sm text-muted-foreground font-mono min-w-[80px]">
          {formatTime(currentTime)} / {formatTime(duration)}
        </div>

        {/* Progress Bar */}
        <div className="flex-1 flex items-center gap-2">
          <input
            type="range"
            min="0"
            max={duration || 0}
            value={currentTime}
            onChange={handleSeek}
            className="flex-1 h-2 bg-muted rounded-lg appearance-none cursor-pointer accent-primary"
            style={{
              background: `linear-gradient(to right, hsl(var(--primary)) 0%, hsl(var(--primary)) ${(currentTime / duration) * 100}%, hsl(var(--muted)) ${(currentTime / duration) * 100}%, hsl(var(--muted)) 100%)`
            }}
          />
        </div>

        {/* Volume Control */}
        <div className="flex items-center gap-2">
          <Button
            variant="ghost"
            size="icon"
            onClick={toggleMute}
            className="h-8 w-8"
          >
            {isMuted || volume === 0 ? (
              <VolumeX className="h-4 w-4" />
            ) : (
              <Volume2 className="h-4 w-4" />
            )}
          </Button>
          <input
            type="range"
            min="0"
            max="1"
            step="0.01"
            value={isMuted ? 0 : volume}
            onChange={handleVolumeChange}
            className="w-20 h-2 bg-muted rounded-lg appearance-none cursor-pointer accent-primary"
          />
        </div>
      </div>
    </div>
  );
}

function formatDate(dateString: string): string {
  const date = new Date(dateString);
  return date.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

function formatTime(dateString: string): string {
  const date = new Date(dateString);
  return date.toLocaleTimeString("en-US", {
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
  });
}

function formatDuration(seconds: number): string {
  if (seconds === 0) return "0:00";
  const mins = Math.floor(seconds / 60);
  const secs = seconds % 60;
  return `${mins}:${secs.toString().padStart(2, "0")}`;
}

function getCallStatus(
  call: CallRecord
): "completed" | "missed" | "in_progress" {
  if (call.insights?.duration_sec === 0 && !call.transcript) {
    return "missed";
  }
  return "completed";
}

function getSentiment(call: CallRecord): "positive" | "neutral" | "negative" {
  if (call.sentiment === "positive" || call.sentiment === "negative") {
    return call.sentiment;
  }
  return "neutral";
}

const statusColors = {
  completed: "bg-success/10 text-success border-success/20",
  missed: "bg-destructive/10 text-destructive border-destructive/20",
  in_progress: "bg-warning/10 text-warning border-warning/20",
};

const sentimentColors = {
  positive: "bg-success/10 text-success",
  neutral: "bg-muted text-muted-foreground",
  negative: "bg-destructive/10 text-destructive",
};

const callTypeColors = {
  inbound: "bg-blue-500/10 text-blue-600 border-blue-500/20",
  outbound: "bg-green-500/10 text-green-600 border-green-500/20",
};

export default function CallHistory() {
  const [page, setPage] = useState(1);
  const [selectedCallId, setSelectedCallId] = useState<string | null>(null);

  // Fetch calls and summary
  const {
    data: callsData,
    isLoading: isLoadingCalls,
    error: callsError,
    refetch: refetchCalls,
    isFetching,
  } = useCalls(page, PAGE_SIZE);

  const { data: summaryData, isLoading: isLoadingSummary } = useCallSummary();

  // Fetch full call details when a call is selected (to get latest recording_url)
  const { data: selectedCallData } = useCall(selectedCallId || "");
  const selectedCall = selectedCallData || (selectedCallId ? callsData?.items.find(c => c.call_id === selectedCallId) : null) || null;

  // Cache update functions for WebSocket updates
  const updateCallInCache = useUpdateCallInCache();
  const partialUpdateCallInCache = usePartialUpdateCallInCache();

  // WebSocket connection for real-time updates
  const { isConnected } = useDashboardWebSocket({
    onCallInProgress: (data: CallInProgressData) => {
      toast({
        title: "Call In Progress",
        description: `Calling ${data.client_name} at ${data.phone_number}`,
      });
    },
    onCallCompleted: (data: CallCompletedData) => {
      // Update the cache with the new call
      updateCallInCache(data);
      toast({
        title: "Call Completed",
        description: `Call with ${data.client_name} has ended`,
      });
    },
    onCallAudioReady: (data: CallAudioReadyData) => {
      // Update the call's recording_url in the cache
      partialUpdateCallInCache(data.call_id, { recording_url: data.recording_url });
      
      toast({
        title: "Recording Ready",
        description: "Call audio is now available for playback",
      });
    },
  });

  const totalPages = callsData
    ? Math.ceil(callsData.total / PAGE_SIZE)
    : 1;

  const stats = [
    {
      label: "Total Calls",
      value: summaryData?.total_calls.toString() ?? "-",
    },
    {
      label: "Conversions",
      value: summaryData?.conversions.toString() ?? "-",
    },
    {
      label: "Conversion Rate",
      value: summaryData
        ? `${(summaryData.conversion_rate * 100).toFixed(1)}%`
        : "-",
    },
    {
      label: "This Page",
      value: callsData?.items.length.toString() ?? "-",
    },
  ];


  return (
    <DashboardLayout>
      <div className="max-w-5xl">
        <header className="mb-8">
          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-3xl font-bold text-foreground">Call History</h1>
              <p className="text-muted-foreground mt-2">
                View and analyze your past calls
              </p>
            </div>
            <div className="flex items-center gap-3">
              {/* Connection Status */}
              <div
                className={`flex items-center gap-2 px-3 py-1.5 rounded-full text-xs font-medium ${
                  isConnected
                    ? "bg-success/10 text-success"
                    : "bg-muted text-muted-foreground"
                }`}
              >
                {isConnected ? (
                  <Wifi className="h-3 w-3" />
                ) : (
                  <WifiOff className="h-3 w-3" />
                )}
                {isConnected ? "Live" : "Offline"}
              </div>
              {/* Refresh Button */}
              <Button
                variant="outline"
                size="sm"
                onClick={() => refetchCalls()}
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

        {/* Stats */}
        <div className="grid grid-cols-4 gap-4 mb-8">
          {stats.map((stat) => (
            <div
              key={stat.label}
              className="bg-card rounded-xl p-4 shadow-soft text-center"
            >
              {isLoadingSummary ? (
                <Skeleton className="h-8 w-16 mx-auto mb-1" />
              ) : (
                <p className="text-2xl font-bold text-card-foreground">
                  {stat.value}
                </p>
              )}
              <p className="text-sm text-muted-foreground">{stat.label}</p>
            </div>
          ))}
        </div>

        {/* Error State */}
        {callsError && (
          <div className="bg-destructive/10 text-destructive rounded-xl p-6 mb-8 text-center">
            <p className="font-medium">Failed to load calls</p>
            <p className="text-sm mt-1 opacity-80">
              {callsError instanceof Error
                ? callsError.message
                : "Unknown error occurred"}
            </p>
            <Button
              variant="outline"
              size="sm"
              className="mt-4"
              onClick={() => refetchCalls()}
            >
              Try Again
            </Button>
          </div>
        )}

        {/* Call List */}
        <div className="bg-card rounded-2xl shadow-card overflow-hidden">
          <div className="p-6 border-b border-border flex items-center justify-between">
            <div>
              <h2 className="font-semibold text-card-foreground">Recent Calls</h2>
              {callsData && (
                <p className="text-sm text-muted-foreground">
                  Showing {(page - 1) * PAGE_SIZE + 1} -{" "}
                  {Math.min(page * PAGE_SIZE, callsData.total)} of{" "}
                  {callsData.total}
                </p>
              )}
            </div>
          </div>

          {/* Loading State */}
          {isLoadingCalls && (
            <div className="divide-y divide-border">
              {[...Array(5)].map((_, i) => (
                <div key={i} className="p-4 flex items-center gap-4">
                  <Skeleton className="h-12 w-12 rounded-full" />
                  <div className="flex-1">
                    <Skeleton className="h-4 w-32 mb-2" />
                    <Skeleton className="h-3 w-24" />
                  </div>
                  <div className="text-right">
                    <Skeleton className="h-3 w-20 mb-2" />
                    <Skeleton className="h-3 w-16" />
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* Empty State */}
          {!isLoadingCalls && callsData?.items.length === 0 && (
            <div className="p-12 text-center">
              <Phone className="h-12 w-12 mx-auto text-muted-foreground mb-4" />
              <p className="text-lg font-medium text-card-foreground">
                No calls yet
              </p>
              <p className="text-sm text-muted-foreground mt-1">
                Start making calls to see them here
              </p>
            </div>
          )}

          {/* Call Items */}
          {!isLoadingCalls && callsData && callsData.items.length > 0 && (
            <div className="divide-y divide-border">
              {callsData.items.map((call) => {
                const status = getCallStatus(call);
                return (
                  <button
                    key={call.call_id}
                    onClick={() => setSelectedCallId(call.call_id)}
                    className="w-full p-4 flex items-center gap-4 hover:bg-accent/30 transition-colors text-left"
                  >
                    <div className="h-12 w-12 rounded-full bg-accent flex items-center justify-center flex-shrink-0">
                      <User className="h-6 w-6 text-muted-foreground" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <p className="font-medium text-card-foreground truncate">
                          {call.client_name}
                        </p>
                        {call.call_type && (
                          <Badge
                            variant="outline"
                            className={callTypeColors[call.call_type]}
                          >
                            {call.call_type === "inbound" ? (
                              <>
                                <ArrowDownLeft className="h-3 w-3 mr-1" />
                                Incoming
                              </>
                            ) : (
                              <>
                                <ArrowUpCircle className="h-3 w-3 mr-1" />
                                Outgoing
                              </>
                            )}
                          </Badge>
                        )}
                        <Badge
                          variant="outline"
                          className={statusColors[status]}
                        >
                          {status.replace("_", " ")}
                        </Badge>
                      </div>
                      <p className="text-sm text-muted-foreground">
                        {call.phone_number || "No phone number"}
                      </p>
                    </div>
                    <div className="text-right flex-shrink-0">
                      <div className="flex items-center gap-1 text-sm text-muted-foreground">
                        <Calendar className="h-4 w-4" />
                        {formatDate(call.timestamp)}
                      </div>
                      <div className="flex items-center gap-1 text-sm text-muted-foreground">
                        <Clock className="h-4 w-4" />
                        {formatTime(call.timestamp)} ·{" "}
                        {formatDuration(call.insights?.duration_sec ?? 0)}
                      </div>
                    </div>
                    <ArrowUpRight className="h-5 w-5 text-muted-foreground" />
                  </button>
                );
              })}
            </div>
          )}

          {/* Pagination */}
          {callsData && totalPages > 1 && (
            <div className="p-4 border-t border-border flex items-center justify-between">
              <Button
                variant="outline"
                size="sm"
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                disabled={page === 1 || isFetching}
              >
                <ChevronLeft className="h-4 w-4 mr-1" />
                Previous
              </Button>
              <span className="text-sm text-muted-foreground">
                Page {page} of {totalPages}
              </span>
              <Button
                variant="outline"
                size="sm"
                onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                disabled={page === totalPages || isFetching}
              >
                Next
                <ChevronRight className="h-4 w-4 ml-1" />
              </Button>
            </div>
          )}
        </div>

        {/* Call Detail Dialog */}
        <Dialog 
          open={!!selectedCallId} 
          onOpenChange={(open) => {
            if (!open) {
              setSelectedCallId(null);
            }
          }}
        >
          <DialogContent className="max-w-2xl max-h-[90vh] bg-card border border-border">
            <DialogHeader>
              <DialogTitle className="flex items-center gap-3">
                <div className="h-10 w-10 rounded-full bg-accent flex items-center justify-center">
                  <Phone className="h-5 w-5 text-foreground" />
                </div>
                <div>
                  <p className="text-lg font-semibold">
                    {selectedCall?.client_name}
                  </p>
                  <p className="text-sm text-muted-foreground font-normal">
                    {selectedCall?.phone_number || "No phone number"}
                  </p>
                </div>
              </DialogTitle>
            </DialogHeader>
            {selectedCall && (
              <ScrollArea className="max-h-[60vh]">
                <div className="space-y-6 pr-4">
                  {/* Call Info */}
                  <div className="flex flex-wrap gap-3">
                    {selectedCall.call_type && (
                      <Badge
                        variant="outline"
                        className={callTypeColors[selectedCall.call_type]}
                      >
                        {selectedCall.call_type === "inbound" ? (
                          <>
                            <ArrowDownLeft className="h-3 w-3 mr-1" />
                            Incoming
                          </>
                        ) : (
                          <>
                            <ArrowUpCircle className="h-3 w-3 mr-1" />
                            Outgoing
                          </>
                        )}
                      </Badge>
                    )}
                    <Badge
                      variant="outline"
                      className={statusColors[getCallStatus(selectedCall)]}
                    >
                      {getCallStatus(selectedCall).replace("_", " ")}
                    </Badge>
                    <Badge
                      variant="outline"
                      className={sentimentColors[getSentiment(selectedCall)]}
                    >
                      {getSentiment(selectedCall)} sentiment
                    </Badge>
                    {selectedCall.conversion_status && (
                      <Badge variant="secondary">Converted</Badge>
                    )}
                    {selectedCall.insights?.topics?.map((topic) => (
                      <Badge key={topic} variant="secondary">
                        {topic}
                      </Badge>
                    ))}
                  </div>

                  <div className="grid grid-cols-3 gap-4">
                    <div className="bg-accent/50 rounded-lg p-3">
                      <p className="text-xs text-muted-foreground">Date</p>
                      <p className="font-medium text-card-foreground">
                        {formatDate(selectedCall.timestamp)}
                      </p>
                    </div>
                    <div className="bg-accent/50 rounded-lg p-3">
                      <p className="text-xs text-muted-foreground">Time</p>
                      <p className="font-medium text-card-foreground">
                        {formatTime(selectedCall.timestamp)}
                      </p>
                    </div>
                    <div className="bg-accent/50 rounded-lg p-3">
                      <p className="text-xs text-muted-foreground">Duration</p>
                      <p className="font-medium text-card-foreground">
                        {formatDuration(selectedCall.insights?.duration_sec ?? 0)}
                      </p>
                    </div>
                  </div>

                  {/* Follow-up Date */}
                  {selectedCall.follow_up_date && (
                    <div className="bg-primary/10 rounded-lg p-4">
                      <p className="text-xs text-primary font-medium mb-1">
                        Follow-up Scheduled
                      </p>
                      <p className="font-medium text-card-foreground">
                        {formatDate(selectedCall.follow_up_date)}
                      </p>
                    </div>
                  )}

                  {/* Call Recording Audio Player */}
                  {selectedCall.recording_url ? (
                    <div>
                      <h4 className="font-semibold text-card-foreground mb-2">
                        Call Recording
                      </h4>
                      <AudioPlayer 
                        audioUrl={selectedCall.recording_url}
                      />
                    </div>
                  ) : (
                    <div className="bg-muted/30 rounded-lg p-4 text-sm text-muted-foreground">
                      No recording available for this call
                    </div>
                  )}

                  {/* Summary */}
                  {selectedCall.summary && (
                    <div>
                      <h4 className="font-semibold text-card-foreground mb-2">
                        Summary
                      </h4>
                      <p className="text-sm text-muted-foreground bg-accent/30 rounded-lg p-4">
                        {selectedCall.summary}
                      </p>
                    </div>
                  )}

                  {/* Transcript */}
                  {selectedCall.transcript && (
                    <div>
                      <h4 className="font-semibold text-card-foreground mb-2">
                        Transcript
                      </h4>
                      <div className="bg-accent/30 rounded-lg p-4">
                        <pre className="text-sm text-muted-foreground whitespace-pre-wrap font-sans">
                          {selectedCall.transcript}
                        </pre>
                      </div>
                    </div>
                  )}

                  {/* Notification Status */}
                  {selectedCall.notification_preferences && (
                    <div>
                      <h4 className="font-semibold text-card-foreground mb-2">
                        Notifications
                      </h4>
                      <div className="flex flex-wrap gap-2">
                        {selectedCall.notification_preferences.email_sent && (
                          <Badge variant="outline" className="bg-success/10 text-success">
                            Email Sent
                          </Badge>
                        )}
                        {selectedCall.notification_preferences.whatsapp_sent && (
                          <Badge variant="outline" className="bg-success/10 text-success">
                            WhatsApp Sent
                          </Badge>
                        )}
                        {!selectedCall.notification_preferences.email_sent &&
                          !selectedCall.notification_preferences.whatsapp_sent && (
                            <span className="text-sm text-muted-foreground">
                              No notifications sent
                            </span>
                          )}
                      </div>
                    </div>
                  )}
                </div>
              </ScrollArea>
            )}
          </DialogContent>
        </Dialog>
      </div>
    </DashboardLayout>
  );
}

