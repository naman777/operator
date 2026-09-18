"use client";
import { useEffect, useState } from "react";
import type { components } from "@operator/contracts";
import { request } from "./api";
import { EventDecoder, mergeEvents, type MissionEvent } from "./sse";
export type Run = components["schemas"]["RunView"];

export function useMissionRun(id: string, token: string, revision: number) {
  const [run, setRun] = useState<Run | null>(null);
  const [events, setEvents] = useState<MissionEvent[]>([]);
  const [connection, setConnection] = useState("Connecting");
  const [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    let after = 0;
    setEvents([]);
    setRun(null);
    setError("");
    async function refresh() {
      const value = await request<Run>(`/v1/missions/${id}/run`, token, {
        signal: controller.signal,
      });
      if (!controller.signal.aborted) setRun(value);
    }
    async function connect() {
      while (!controller.signal.aborted) {
        let reader: ReadableStreamDefaultReader<Uint8Array> | undefined;
        try {
          await refresh();
          const response = await fetch(`/api/v1/missions/${id}/stream`, {
            headers: {
              Authorization: `Bearer ${token}`,
              "Last-Event-ID": String(after),
            },
            cache: "no-store",
            signal: controller.signal,
          });
          if (!response.ok || !response.body)
            throw new Error(`Event stream unavailable (${response.status})`);
          if (!controller.signal.aborted) {
            setConnection("Live");
            setError("");
          }
          reader = response.body.getReader();
          const text = new TextDecoder();
          const decoder = new EventDecoder();
          while (!controller.signal.aborted) {
            const { value, done } = await reader.read();
            if (done) break;
            const batch = decoder
              .push(text.decode(value, { stream: true }))
              .filter((event) => event.mission_id === id);
            if (batch.length) {
              after = Math.max(after, ...batch.map((event) => event.sequence));
              setEvents((previous) => mergeEvents(previous, batch));
              await refresh();
            }
          }
          if (!controller.signal.aborted) setConnection("Synced");
        } catch (cause) {
          if (controller.signal.aborted) return;
          setConnection("Reconnecting");
          setError((cause as Error).message);
        } finally {
          await reader?.cancel().catch(() => {});
        }
        // Reconnect also after terminal runs so another tab's retry is discovered.
        await new Promise<void>((resolve) => {
          if (controller.signal.aborted) return resolve();
          const done = () => {
            clearTimeout(timer);
            controller.signal.removeEventListener("abort", done);
            resolve();
          };
          const timer = setTimeout(done, 2000);
          controller.signal.addEventListener("abort", done, { once: true });
        });
      }
    }
    void connect();
    return () => controller.abort();
  }, [id, token, revision]);
  return { run, events, connection, streamError: error };
}
