import { describe, expect, it } from "vitest";
import { EventDecoder, mergeEvents, type MissionEvent } from "./sse";
const event = (sequence: number): MissionEvent => ({
  schema_version: "1.0",
  id: String(sequence),
  mission_id: "mission-1",
  sequence,
  type: "step.completed",
  payload: {},
  created_at: "2026-09-18T00:00:00Z",
});
const frame = (sequence: number) =>
  `id: ${sequence}\r\nevent: mission\r\ndata: ${JSON.stringify(event(sequence))}\r\n\r\n`;
describe("mission SSE", () => {
  it("handles every possible transport split including CRLF boundaries", () => {
    const source = frame(1) + frame(2);
    for (let split = 0; split <= source.length; split++) {
      const decoder = new EventDecoder();
      expect(
        [
          ...decoder.push(source.slice(0, split)),
          ...decoder.push(source.slice(split)),
        ].map((e) => e.sequence),
      ).toEqual([1, 2]);
    }
  });
  it("ignores heartbeat and terminal frames", () => {
    expect(
      new EventDecoder().push(": heartbeat\n\nevent: end\ndata: {}\n\n"),
    ).toEqual([]);
  });
  it("deduplicates replayed events and preserves sequence order", () => {
    expect(
      mergeEvents([event(2)], [event(3), event(1), event(2)]).map(
        (e) => e.sequence,
      ),
    ).toEqual([1, 2, 3]);
  });
  it("rejects invalid event payloads", () => {
    expect(() =>
      new EventDecoder().push('event: mission\ndata: {"sequence":0}\n\n'),
    ).toThrow("Invalid mission event");
  });
});
