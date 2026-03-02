import type { AuditEvent } from './event.js';

const DEFAULT_BATCH_SIZE = 10;
const DEFAULT_FLUSH_INTERVAL_MS = 5_000;

export type GetAccessToken = () => string | null;

export interface AuditEmitterOptions {
  batchSize?: number;
  flushIntervalMs?: number;
}

export class AuditEmitter {
  private readonly endpoint: string;
  private readonly getAccessToken: GetAccessToken;
  private readonly batchSize: number;
  private readonly flushIntervalMs: number;
  private queue: AuditEvent[] = [];
  private flushTimer: ReturnType<typeof setInterval> | null = null;

  constructor(endpoint: string, getAccessToken: GetAccessToken, options: AuditEmitterOptions = {}) {
    this.endpoint = endpoint;
    this.getAccessToken = getAccessToken;
    this.batchSize = options.batchSize ?? DEFAULT_BATCH_SIZE;
    this.flushIntervalMs = options.flushIntervalMs ?? DEFAULT_FLUSH_INTERVAL_MS;

    this.flushTimer = setInterval(() => {
      void this.flush();
    }, this.flushIntervalMs);
  }

  emit(event: AuditEvent): void {
    const enriched: AuditEvent = {
      ...event,
      timestamp: event.timestamp ?? new Date().toISOString(),
    };

    this.queue.push(enriched);

    if (this.queue.length >= this.batchSize) {
      void this.flush();
    }
  }

  async flush(): Promise<void> {
    if (this.queue.length === 0) {
      return;
    }

    const batch = this.queue.splice(0, this.queue.length);
    const token = this.getAccessToken();

    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
    };

    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
    }

    try {
      await fetch(this.endpoint, {
        method: 'POST',
        headers,
        body: JSON.stringify(batch),
      });
    } catch {
      // Re-queue on network failure to avoid losing events
      this.queue.unshift(...batch);
    }
  }

  destroy(): void {
    if (this.flushTimer !== null) {
      clearInterval(this.flushTimer);
      this.flushTimer = null;
    }
  }
}
