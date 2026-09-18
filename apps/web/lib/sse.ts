import type { components } from "@operator/contracts";
export type MissionEvent = components["schemas"]["EventView"];

// Retains partial frames across transport chunks, including split CRLF separators.
export class EventDecoder {
  private buffer = "";
  push(chunk: string): MissionEvent[] {
    this.buffer = (this.buffer + chunk).replace(/\r\n/g, "\n");
    if (this.buffer.length > 1_000_000)
      throw new Error("Event frame exceeds the size limit");
    const blocks = this.buffer.split("\n\n");
    this.buffer = blocks.pop() || "";
    const events: MissionEvent[] = [];
    for (const block of blocks) {
      if (!block.split("\n").includes("event: mission")) continue;
      const data = block
        .split("\n")
        .filter((line) => line.startsWith("data:"))
        .map((line) => line.slice(5).trimStart())
        .join("\n");
      const event = JSON.parse(data) as MissionEvent;
      if (
        !event ||
        !Number.isInteger(event.sequence) ||
        event.sequence < 1 ||
        typeof event.mission_id !== "string" ||
        typeof event.type !== "string"
      ) {
        throw new Error("Invalid mission event");
      }
      events.push(event);
    }
    return events;
  }
}

export function mergeEvents(
  previous: MissionEvent[],
  incoming: MissionEvent[],
): MissionEvent[] {
  const bySequence = new Map(previous.map((event) => [event.sequence, event]));
  incoming.forEach((event) => {
    if (!bySequence.has(event.sequence)) bySequence.set(event.sequence, event);
  });
  return [...bySequence.values()].sort((a, b) => a.sequence - b.sequence);
}
