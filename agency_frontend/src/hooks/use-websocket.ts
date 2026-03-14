import { useEffect, useRef, useState, useCallback } from 'react';
import { getWebSocketUrl } from '@/lib/api';
import type { WebSocketMessage, CallInProgressData, CallCompletedData, CallAudioReadyData, CallFailedData, ConversationMessageData } from '@/lib/types';

interface WebSocketOptions {
  onCallInProgress?: (data: CallInProgressData) => void;
  onCallCompleted?: (data: CallCompletedData) => void;
  onCallAudioReady?: (data: CallAudioReadyData) => void;
  onCallFailed?: (data: CallFailedData) => void;
  onConversationMessage?: (data: ConversationMessageData) => void;
  onConnect?: () => void;
  onDisconnect?: () => void;
  onError?: (error: Event) => void;
  reconnectInterval?: number;
  maxReconnectAttempts?: number;
}

// Singleton WebSocket manager to prevent multiple connections
class WebSocketManager {
  private static instance: WebSocketManager | null = null;
  private ws: WebSocket | null = null;
  private reconnectAttempts = 0;
  private reconnectTimeout: NodeJS.Timeout | null = null;
  private listeners: Set<(event: string, data: unknown) => void> = new Set();
  private connectionListeners: Set<(connected: boolean) => void> = new Set();
  private isConnecting = false;
  private maxReconnectAttempts = 10;
  private reconnectInterval = 3000;

  static getInstance(): WebSocketManager {
    if (!WebSocketManager.instance) {
      WebSocketManager.instance = new WebSocketManager();
    }
    return WebSocketManager.instance;
  }

  get isConnected(): boolean {
    return this.ws?.readyState === WebSocket.OPEN;
  }

  connect(): void {
    // Prevent multiple simultaneous connection attempts
    if (this.isConnecting || this.isConnected) {
      return;
    }

    this.isConnecting = true;

    try {
      const wsUrl = getWebSocketUrl();
      console.log('[WebSocket] Connecting to:', wsUrl);
      
      this.ws = new WebSocket(wsUrl);

      this.ws.onopen = () => {
        console.log('[WebSocket] Connected');
        this.isConnecting = false;
        this.reconnectAttempts = 0;
        this.notifyConnectionChange(true);
      };

      this.ws.onmessage = (event) => {
        try {
          const message: WebSocketMessage = JSON.parse(event.data);
          this.notifyListeners(message.event, message.data);
        } catch (error) {
          console.error('[WebSocket] Failed to parse message:', error);
        }
      };

      this.ws.onerror = (error) => {
        console.error('[WebSocket] Error:', error);
        this.isConnecting = false;
      };

      this.ws.onclose = () => {
        console.log('[WebSocket] Disconnected');
        this.isConnecting = false;
        this.ws = null;
        this.notifyConnectionChange(false);

        // Only reconnect if we have listeners
        if (this.listeners.size > 0 && this.reconnectAttempts < this.maxReconnectAttempts) {
          this.reconnectAttempts += 1;
          console.log(
            `[WebSocket] Reconnecting in ${this.reconnectInterval}ms (attempt ${this.reconnectAttempts}/${this.maxReconnectAttempts})`
          );
          
          this.reconnectTimeout = setTimeout(() => {
            this.connect();
          }, this.reconnectInterval);
        }
      };
    } catch (error) {
      console.error('[WebSocket] Failed to create connection:', error);
      this.isConnecting = false;
    }
  }

  disconnect(): void {
    if (this.reconnectTimeout) {
      clearTimeout(this.reconnectTimeout);
      this.reconnectTimeout = null;
    }
    
    this.reconnectAttempts = this.maxReconnectAttempts; // Prevent auto-reconnect
    
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
  }

  addListener(callback: (event: string, data: unknown) => void): () => void {
    this.listeners.add(callback);
    
    // Connect if this is the first listener
    if (this.listeners.size === 1 && !this.isConnected && !this.isConnecting) {
      this.reconnectAttempts = 0; // Reset reconnect attempts
      this.connect();
    }
    
    // Return cleanup function
    return () => {
      this.listeners.delete(callback);
      
      // Disconnect if no more listeners (optional - keep connection for performance)
      // if (this.listeners.size === 0) {
      //   this.disconnect();
      // }
    };
  }

  addConnectionListener(callback: (connected: boolean) => void): () => void {
    this.connectionListeners.add(callback);
    // Immediately notify of current state
    callback(this.isConnected);
    
    return () => {
      this.connectionListeners.delete(callback);
    };
  }

  private notifyListeners(event: string, data: unknown): void {
    this.listeners.forEach((listener) => {
      try {
        listener(event, data);
      } catch (error) {
        console.error('[WebSocket] Listener error:', error);
      }
    });
  }

  private notifyConnectionChange(connected: boolean): void {
    this.connectionListeners.forEach((listener) => {
      try {
        listener(connected);
      } catch (error) {
        console.error('[WebSocket] Connection listener error:', error);
      }
    });
  }
}

export function useDashboardWebSocket(options: WebSocketOptions = {}) {
  const {
    onCallInProgress,
    onCallCompleted,
    onCallAudioReady,
    onCallFailed,
    onConversationMessage,
    onConnect,
    onDisconnect,
  } = options;

  const [isConnected, setIsConnected] = useState(false);
  
  // Store callbacks in refs to avoid re-subscriptions
  const callbacksRef = useRef({
    onCallInProgress,
    onCallCompleted,
    onCallAudioReady,
    onCallFailed,
    onConversationMessage,
    onConnect,
    onDisconnect,
  });

  // Update refs when callbacks change
  useEffect(() => {
    callbacksRef.current = {
      onCallInProgress,
      onCallCompleted,
      onCallAudioReady,
      onCallFailed,
      onConversationMessage,
      onConnect,
      onDisconnect,
    };
  }, [onCallInProgress, onCallCompleted, onCallAudioReady, onCallFailed, onConversationMessage, onConnect, onDisconnect]);

  useEffect(() => {
    const manager = WebSocketManager.getInstance();

    // Add message listener
    const removeMessageListener = manager.addListener((event, data) => {
      const callbacks = callbacksRef.current;
      
      switch (event) {
        case 'call_in_progress':
          callbacks.onCallInProgress?.(data as CallInProgressData);
          break;
        case 'call_completed':
          callbacks.onCallCompleted?.(data as CallCompletedData);
          break;
        case 'call_audio_ready':
          callbacks.onCallAudioReady?.(data as CallAudioReadyData);
          break;
        case 'call_failed':
          callbacks.onCallFailed?.(data as CallFailedData);
          break;
        case 'conversation_message':
          callbacks.onConversationMessage?.(data as ConversationMessageData);
          break;
        default:
          console.log('[WebSocket] Unknown event:', event);
      }
    });

    // Add connection listener
    const removeConnectionListener = manager.addConnectionListener((connected) => {
      setIsConnected(connected);
      const callbacks = callbacksRef.current;
      if (connected) {
        callbacks.onConnect?.();
      } else {
        callbacks.onDisconnect?.();
      }
    });

    // Cleanup
    return () => {
      removeMessageListener();
      removeConnectionListener();
    };
  }, []); // Empty dependency array - only run once

  const reconnect = useCallback(() => {
    const manager = WebSocketManager.getInstance();
    manager.disconnect();
    manager.connect();
  }, []);

  const disconnect = useCallback(() => {
    WebSocketManager.getInstance().disconnect();
  }, []);

  return {
    isConnected,
    reconnect,
    disconnect,
  };
}

// Simplified hook that just returns connection status
export function useWebSocketStatus() {
  const [isConnected, setIsConnected] = useState(false);

  useEffect(() => {
    const manager = WebSocketManager.getInstance();
    const removeListener = manager.addConnectionListener(setIsConnected);
    
    return () => {
      removeListener();
    };
  }, []);

  return isConnected;
}
