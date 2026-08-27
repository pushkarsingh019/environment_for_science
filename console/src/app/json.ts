import type { JsonObject, JsonValue } from "../types";

function isJsonObject(value: unknown): value is JsonObject {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** Non-null, non-array object; otherwise null. */
export function asObject(value: unknown): JsonObject | null {
  return isJsonObject(value) ? value : null;
}

/** Array input reduced to its object items; anything else yields an empty list. */
export function asObjects(value: unknown): JsonObject[] {
  if (!Array.isArray(value)) return [];
  const items: unknown[] = value;
  return items.filter(isJsonObject);
}

/** Non-blank string, otherwise the fallback. */
export function text(value: unknown, fallback = "Unavailable"): string {
  return typeof value === "string" && value.trim() !== "" ? value : fallback;
}

export function finiteNumber(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

export function booleanValue(value: unknown): boolean | undefined {
  return typeof value === "boolean" ? value : undefined;
}

export function stringList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  const items: unknown[] = value;
  return items.filter((item): item is string => typeof item === "string");
}

export function numberList(value: unknown): number[] {
  if (!Array.isArray(value)) return [];
  const items: unknown[] = value;
  return items.filter((item): item is number => typeof item === "number" && Number.isFinite(item));
}

export function jsonPretty(value: JsonValue): string {
  return JSON.stringify(value, null, 2);
}
