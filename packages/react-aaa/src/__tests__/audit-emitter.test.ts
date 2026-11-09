import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { AuditEmitter } from '../audit/emitter.js';
import type { AuditEvent } from '../audit/event.js';

const ENDPOINT = 'https://audit.example.com/events';

const event: AuditEvent = {
  type: 'auth.login',
  outcome: 'success',
  actor: { sub: 'user-1' },
};

describe('AuditEmitter', () => {
  let fetchMock: ReturnType<typeof vi.fn>;
  let emitter: AuditEmitter | null = null;

  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-01-02T03:04:05.000Z'));
    fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 204 });
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    emitter?.destroy();
    emitter = null;
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  function sentBatch(call: number): Array<Record<string, unknown>> {
    return JSON.parse(fetchMock.mock.calls[call][1].body as string) as Array<Record<string, unknown>>;
  }

  it('stamps events without a timestamp with the current ISO-8601 time', async () => {
    emitter = new AuditEmitter(ENDPOINT, () => null);

    emitter.emit(event);
    await emitter.flush();

    expect(sentBatch(0)[0].timestamp).toBe('2026-01-02T03:04:05.000Z');
  });

  it('keeps a caller-supplied timestamp unchanged', async () => {
    emitter = new AuditEmitter(ENDPOINT, () => null);

    emitter.emit({ ...event, timestamp: '2025-12-31T00:00:00.000Z' });
    await emitter.flush();

    expect(sentBatch(0)[0].timestamp).toBe('2025-12-31T00:00:00.000Z');
  });

  it('POSTs the batch as JSON to the endpoint with a Bearer token', async () => {
    emitter = new AuditEmitter(ENDPOINT, () => 'tok-1');

    emitter.emit(event);
    await emitter.flush();

    const [url, init] = fetchMock.mock.calls[0] as [string, { method: string; headers: Record<string, string> }];
    expect(url).toBe(ENDPOINT);
    expect(init.method).toBe('POST');
    expect(init.headers['Content-Type']).toBe('application/json');
    expect(init.headers['Authorization']).toBe('Bearer tok-1');
    expect(sentBatch(0)).toHaveLength(1);
    expect(sentBatch(0)[0]).toMatchObject({ type: 'auth.login', outcome: 'success', actor: { sub: 'user-1' } });
  });

  it('omits the Authorization header when no token is available', async () => {
    emitter = new AuditEmitter(ENDPOINT, () => null);

    emitter.emit(event);
    await emitter.flush();

    const headers = (fetchMock.mock.calls[0][1] as { headers: Record<string, string> }).headers;
    expect(headers).not.toHaveProperty('Authorization');
  });

  it('auto-flushes as soon as the configured batch size is reached', () => {
    emitter = new AuditEmitter(ENDPOINT, () => null, { batchSize: 2, flushIntervalMs: 60_000 });

    emitter.emit(event);
    expect(fetchMock).not.toHaveBeenCalled();

    emitter.emit({ ...event, type: 'auth.logout' });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(sentBatch(0).map((e) => e.type)).toEqual(['auth.login', 'auth.logout']);
  });

  it('uses a default batch size of 10', () => {
    emitter = new AuditEmitter(ENDPOINT, () => null, { flushIntervalMs: 60_000 });

    for (let i = 0; i < 9; i++) {
      emitter.emit(event);
    }
    expect(fetchMock).not.toHaveBeenCalled();

    emitter.emit(event);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(sentBatch(0)).toHaveLength(10);
  });

  it('flushes queued events on the configured interval', () => {
    emitter = new AuditEmitter(ENDPOINT, () => null, { flushIntervalMs: 1000 });

    emitter.emit(event);
    vi.advanceTimersByTime(999);
    expect(fetchMock).not.toHaveBeenCalled();

    vi.advanceTimersByTime(1);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(sentBatch(0)).toHaveLength(1);
  });

  it('does not call fetch when the queue is empty', async () => {
    emitter = new AuditEmitter(ENDPOINT, () => null);

    await emitter.flush();

    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('re-queues the batch on network failure and delivers it on the next flush', async () => {
    fetchMock
      .mockRejectedValueOnce(new TypeError('network down'))
      .mockResolvedValueOnce({ ok: true, status: 204 });
    emitter = new AuditEmitter(ENDPOINT, () => null);

    emitter.emit(event);
    emitter.emit({ ...event, type: 'auth.logout' });
    await expect(emitter.flush()).resolves.toBeUndefined();
    await emitter.flush();

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(sentBatch(0).map((e) => e.type)).toEqual(['auth.login', 'auth.logout']);
    expect(sentBatch(1)).toEqual(sentBatch(0));
  });

  it('stops the interval flush after destroy and is safe to destroy twice', () => {
    emitter = new AuditEmitter(ENDPOINT, () => null, { flushIntervalMs: 1000 });

    emitter.emit(event);
    emitter.destroy();
    emitter.destroy();
    vi.advanceTimersByTime(10_000);

    expect(fetchMock).not.toHaveBeenCalled();
  });
});
