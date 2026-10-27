"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";

export default function Settings() {
  const { me } = useAuth();
  const [name, setName] = useState("");
  const [zone, setZone] = useState("");
  const [chat, setChat] = useState("");
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    if (me) {
      setName(me.display_name);
      setZone(me.timezone);
    }
  }, [me]);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setMessage(null);
    try {
      await api.patchMe({ display_name: name, timezone: zone, ...(chat.trim() ? { telegram_chat_id: chat.trim() } : {}) });
      setChat("");
      setMessage("Saved.");
    } catch (err) {
      setMessage((err as Error).message);
    }
  }

  return (
    <>
      <h1>Settings</h1>
      <form onSubmit={save} className="card auth">
        <label>
          Name
          <input value={name} onChange={(e) => setName(e.target.value)} />
        </label>
        <label>
          Timezone
          <input value={zone} onChange={(e) => setZone(e.target.value)} />
        </label>
        <label>
          Telegram chat id {me?.telegram_linked ? <span className="tag">linked</span> : <span className="muted small">(not linked)</span>}
          <input value={chat} onChange={(e) => setChat(e.target.value)} placeholder={me?.telegram_linked ? "Enter a new id to replace" : "Your Telegram chat id"} />
        </label>
        <button>Save</button>
        {message ? <p className="muted">{message}</p> : null}
      </form>
    </>
  );
}
