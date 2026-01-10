import { useState, useEffect, useRef } from "react";
import { History, User, Phone, Clock, FileText, Play, Pause, Volume2, VolumeX, RefreshCw } from "lucide-react";
import { DashboardLayout } from "@/components/layout/DashboardLayout";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useCalls, useCall } from "@/hooks/use-calls";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { ScrollArea } from "@/components/ui/scroll-area";

const PAGE_SIZE = 20;

// Custom Audio Player Component
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
    <div className="bg-muted/30 rounded-lg p-4 space-y-3">
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

function formatTime(dateString: string): string {
  const date = new Date(dateString);
  return date.toLocaleTimeString("en-US", {
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
  });
}

function formatDate(dateString: string): string {
  const date = new Date(dateString);
  return date.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

function formatDuration(seconds: number): string {
  if (seconds === 0) return "0:00";
  const mins = Math.floor(seconds / 60);
  const secs = seconds % 60;
  return `${mins}:${secs.toString().padStart(2, "0")}`;
}

export default function CallHistory() {
  const [page, setPage] = useState(1);
  const [selectedCallId, setSelectedCallId] = useState<string | null>(null);
  
  const { data: callsData, isLoading, error, refetch, isFetching } = useCalls(page, PAGE_SIZE);
  const { data: selectedCallData } = useCall(selectedCallId || "");
  const selectedCall = selectedCallData || (selectedCallId ? callsData?.items.find(c => c.call_id === selectedCallId) : null) || null;

  const totalPages = callsData ? Math.ceil(callsData.total / PAGE_SIZE) : 1;

  return (
    <DashboardLayout>
      <div className="max-w-7xl">
        <header className="mb-8">
          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-3xl font-bold text-foreground">Call History</h1>
              <p className="text-muted-foreground mt-2">
                View all inbound calls and conversations
              </p>
            </div>
            <Button onClick={() => refetch()} disabled={isFetching} variant="outline">
              <RefreshCw className={`h-4 w-4 mr-2 ${isFetching ? "animate-spin" : ""}`} />
              Refresh
            </Button>
          </div>
        </header>

        {error && (
          <div className="mb-4 p-4 bg-destructive/10 text-destructive rounded-lg">
            Error loading calls: {error instanceof Error ? error.message : "Unknown error"}
          </div>
        )}

        <Card>
          <CardHeader>
            <CardTitle>All Calls</CardTitle>
          </CardHeader>
          <CardContent>
            {isLoading ? (
              <div className="space-y-4">
                {[...Array(5)].map((_, i) => (
                  <Skeleton key={i} className="h-24 w-full" />
                ))}
              </div>
            ) : callsData?.items.length === 0 ? (
              <div className="text-center py-12 text-muted-foreground">
                <History className="h-12 w-12 mx-auto mb-4 opacity-50" />
                <p>No calls found</p>
              </div>
            ) : (
              <div className="space-y-4">
                {callsData?.items.map((call) => (
                  <Card
                    key={call.call_id}
                    className="cursor-pointer hover:shadow-md transition-shadow"
                    onClick={() => setSelectedCallId(call.call_id)}
                  >
                    <CardContent className="p-6">
                      <div className="flex items-start justify-between">
                        <div className="flex-1">
                          <div className="flex items-center gap-3 mb-3">
                            <span className="text-sm font-mono text-muted-foreground">
                              {call.call_id}
                            </span>
                            <span className="text-sm text-muted-foreground">
                              {formatDate(call.call_timestamp)} at {formatTime(call.call_timestamp)}
                            </span>
                            <Badge variant="outline">
                              {formatDuration(call.duration_sec)}
                            </Badge>
                          </div>
                          
                          <div className="space-y-2">
                            {call.caller_name && (
                              <div className="flex items-center gap-2">
                                <User className="h-4 w-4 text-muted-foreground" />
                                <span className="font-medium">{call.caller_name}</span>
                              </div>
                            )}
                            {call.caller_phone && (
                              <div className="flex items-center gap-2">
                                <Phone className="h-4 w-4 text-muted-foreground" />
                                <span className="text-sm text-muted-foreground">{call.caller_phone}</span>
                              </div>
                            )}
                          </div>

                          {call.summary && (
                            <div className="mt-3">
                              <p className="text-sm text-muted-foreground line-clamp-2">
                                {call.summary}
                              </p>
                            </div>
                          )}

                          {call.order_id && (
                            <div className="mt-3">
                              <Badge variant="secondary">Order: {call.order_id}</Badge>
                            </div>
                          )}
                          
                          {call.sentiment && (
                            <div className="mt-3">
                              <Badge 
                                variant="outline"
                                className={
                                  call.sentiment === "positive" ? "border-green-500 text-green-700" :
                                  call.sentiment === "negative" ? "border-red-500 text-red-700" :
                                  "border-gray-500 text-gray-700"
                                }
                              >
                                {call.sentiment}
                              </Badge>
                            </div>
                          )}
                          
                          {call.recording_url && (
                            <div className="mt-3">
                              <div className="text-xs text-muted-foreground mb-1">Recording Available</div>
                            </div>
                          )}
                        </div>
                      </div>
                    </CardContent>
                  </Card>
                ))}
              </div>
            )}

            {/* Pagination */}
            {totalPages > 1 && (
              <div className="flex items-center justify-center gap-2 mt-6">
                <Button
                  variant="outline"
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  disabled={page === 1}
                >
                  Previous
                </Button>
                <span className="text-sm text-muted-foreground">
                  Page {page} of {totalPages}
                </span>
                <Button
                  variant="outline"
                  onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                  disabled={page === totalPages}
                >
                  Next
                </Button>
              </div>
            )}
          </CardContent>
        </Card>

        {/* Call Detail Dialog */}
        {selectedCall && (
          <Dialog open={!!selectedCallId} onOpenChange={() => setSelectedCallId(null)}>
            <DialogContent className="max-w-3xl max-h-[80vh]">
              <DialogHeader>
                <DialogTitle>Call Details - {selectedCall.call_id}</DialogTitle>
              </DialogHeader>
              <ScrollArea className="max-h-[60vh] pr-4">
                <div className="space-y-6">
                  <div>
                    <h3 className="font-medium mb-2">Call Information</h3>
                    <div className="space-y-2 text-sm">
                      <div className="flex items-center gap-2">
                        <Clock className="h-4 w-4 text-muted-foreground" />
                        <span>
                          {formatDate(selectedCall.call_timestamp)} at {formatTime(selectedCall.call_timestamp)}
                        </span>
                      </div>
                      <div className="flex items-center gap-2">
                        <Clock className="h-4 w-4 text-muted-foreground" />
                        <span>Duration: {formatDuration(selectedCall.duration_sec)}</span>
                      </div>
                      {selectedCall.caller_name && (
                        <div className="flex items-center gap-2">
                          <User className="h-4 w-4 text-muted-foreground" />
                          <span>{selectedCall.caller_name}</span>
                        </div>
                      )}
                      {selectedCall.caller_phone && (
                        <div className="flex items-center gap-2">
                          <Phone className="h-4 w-4 text-muted-foreground" />
                          <span>{selectedCall.caller_phone}</span>
                        </div>
                      )}
                      {selectedCall.order_id && (
                        <div>
                          <Badge>Order ID: {selectedCall.order_id}</Badge>
                        </div>
                      )}
                      {selectedCall.sentiment && (
                        <div>
                          <Badge 
                            variant="outline"
                            className={
                              selectedCall.sentiment === "positive" ? "border-green-500 text-green-700" :
                              selectedCall.sentiment === "negative" ? "border-red-500 text-red-700" :
                              "border-gray-500 text-gray-700"
                            }
                          >
                            Sentiment: {selectedCall.sentiment}
                          </Badge>
                        </div>
                      )}
                    </div>
                  </div>

                  {/* Call Recording Audio Player */}
                  {selectedCall.recording_url ? (
                    <div>
                      <h3 className="font-medium mb-2 flex items-center gap-2">
                        <Volume2 className="h-4 w-4" />
                        Call Recording
                      </h3>
                      <AudioPlayer audioUrl={selectedCall.recording_url} />
                    </div>
                  ) : (
                    <div className="bg-muted/30 rounded-lg p-4 text-sm text-muted-foreground">
                      No recording available for this call
                    </div>
                  )}

                  {selectedCall.summary && (
                    <div>
                      <h3 className="font-medium mb-2">Summary</h3>
                      <p className="text-sm text-muted-foreground">{selectedCall.summary}</p>
                    </div>
                  )}

                  {selectedCall.transcript && (
                    <div>
                      <h3 className="font-medium mb-2 flex items-center gap-2">
                        <FileText className="h-4 w-4" />
                        Transcript
                      </h3>
                      <div className="bg-muted p-4 rounded-lg">
                        <pre className="text-sm whitespace-pre-wrap font-sans">
                          {selectedCall.transcript}
                        </pre>
                      </div>
                    </div>
                  )}
                </div>
              </ScrollArea>
            </DialogContent>
          </Dialog>
        )}
      </div>
    </DashboardLayout>
  );
}

