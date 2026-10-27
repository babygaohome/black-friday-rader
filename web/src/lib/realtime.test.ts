import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { RealtimeClient, type ConnectionState } from "./realtime";

class FakeSocket {
  static all: FakeSocket[] = [];
  onopen: ((e: unknown) => void) | null = null;
  onmessage: ((e: { data: string }) => void) | null = null;
  onclose: ((e: { code: number }) => void) | null = null;
  onerror: ((e: unknown) => void) | null = null;
  closed = false;
  constructor(public url: string) {
    FakeSocket.all.push(this);
  }
  close() {
    this.closed = true;
  }
}

function setup() {
  const messages: unknown[] = [];
  const states: ConnectionState[] = [];
  const client = new RealtimeClient(
    () => "ws://x/ws",
    (m) => messages.push(m),
    (s) => states.push(s),
    (u) => new FakeSocket(u),
  );
  return { client, messages, states };
}

beforeEach(() => {
  FakeSocket.all = [];
  vi.useFakeTimers();
});
afterEach(() => vi.useRealTimers());

describe("RealtimeClient", () => {
  it("delivers events but swallows control frames and junk", () => {
    const { client, messages, states } = setup();
    client.start();
    const s = FakeSocket.all[0];
    s.onopen?.({});
    s.onmessage?.({ data: JSON.stringify({ event: "connected", data: {} }) });
    s.onmessage?.({ data: JSON.stringify({ event: "pong" }) });
    s.onmessage?.({ data: "not json" });
    s.onmessage?.({ data: JSON.stringify({ event: "price.updated", data: { price: 399 } }) });
    expect(messages).toEqual([{ event: "price.updated", data: { price: 399 } }]);
    expect(states).toEqual(["connecting", "open"]);
  });

  it("reconnects with exponential backoff and resets after a successful open", () => {
    const { client } = setup();
    client.start();
    FakeSocket.all[0].onclose?.({ code: 1006 });
    vi.advanceTimersByTime(999);
    expect(FakeSocket.all).toHaveLength(1);
    vi.advanceTimersByTime(1);
    expect(FakeSocket.all).toHaveLength(2);

    FakeSocket.all[1].onclose?.({ code: 1006 });
    vi.advanceTimersByTime(1999);
    expect(FakeSocket.all).toHaveLength(2);
    vi.advanceTimersByTime(1);
    expect(FakeSocket.all).toHaveLength(3);

    FakeSocket.all[2].onopen?.({});
    FakeSocket.all[2].onclose?.({ code: 1006 });
    vi.advanceTimersByTime(1000); // back to the first delay
    expect(FakeSocket.all).toHaveLength(4);
  });

  it("caps the delay at 30 seconds", () => {
    expect(RealtimeClient.delay(0)).toBe(1000);
    expect(RealtimeClient.delay(3)).toBe(8000);
    expect(RealtimeClient.delay(20)).toBe(30_000);
  });

  it("does not retry after an auth rejection or an explicit stop", () => {
    const a = setup();
    a.client.start();
    FakeSocket.all[0].onclose?.({ code: 4401 });
    vi.advanceTimersByTime(60_000);
    expect(FakeSocket.all).toHaveLength(1);

    const b = setup();
    b.client.start();
    const sock = FakeSocket.all[1];
    b.client.stop();
    expect(sock.closed).toBe(true);
    sock.onclose?.({ code: 1000 });
    vi.advanceTimersByTime(60_000);
    expect(FakeSocket.all).toHaveLength(2);
  });
});
