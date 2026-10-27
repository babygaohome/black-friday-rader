export const TOPICS = ["price.updated", "stock.updated", "deal.created", "alert.triggered", "scanner.status"] as const;
export type Topic = (typeof TOPICS)[number];

export interface RealtimeMessage {
  event: string;
  data: Record<string, any>;
  ts?: string;
}

export type ConnectionState = "connecting" | "open" | "closed";

interface SocketLike {
  onopen: ((ev: unknown) => void) | null;
  onmessage: ((ev: { data: string }) => void) | null;
  onclose: ((ev: { code: number }) => void) | null;
  onerror: ((ev: unknown) => void) | null;
  close(): void;
}
type SocketFactory = (url: string) => SocketLike;

/** Auto-reconnecting WebSocket client. Backs off 1s, 2s, 4s ... up to 30s; auth failures (4401) stop it. */
export class RealtimeClient {
  private socket: SocketLike | null = null;
  private attempt = 0;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private stopped = false;

  constructor(
    private url: () => string,
    private onMessage: (m: RealtimeMessage) => void,
    private onState: (s: ConnectionState) => void = () => {},
    private factory: SocketFactory = (u) => new WebSocket(u) as unknown as SocketLike,
  ) {}

  static delay(attempt: number): number {
    return Math.min(30_000, 1000 * 2 ** attempt);
  }

  start(): void {
    this.stopped = false;
    this.connect();
  }

  stop(): void {
    this.stopped = true;
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
    this.socket?.close();
    this.socket = null;
    this.onState("closed");
  }

  private connect(): void {
    this.onState("connecting");
    const socket = this.factory(this.url());
    this.socket = socket;
    socket.onopen = () => {
      this.attempt = 0;
      this.onState("open");
    };
    socket.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data) as RealtimeMessage;
        if (msg.event === "connected" || msg.event === "pong" || msg.event === "subscribed") return;
        this.onMessage(msg);
      } catch {
        /* ignore malformed frames */
      }
    };
    socket.onclose = (ev) => {
      this.socket = null;
      this.onState("closed");
      if (this.stopped || ev.code === 4401 || ev.code === 4400) return;
      this.timer = setTimeout(() => this.connect(), RealtimeClient.delay(this.attempt++));
    };
    socket.onerror = () => socket.close();
  }
}
