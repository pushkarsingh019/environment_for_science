import { useEffect, useMemo, useState } from "react";
import type { FormEvent } from "react";
import type {
  ActionPresentation,
  JsonObject,
  JsonValue,
} from "../types";

const GROUPS: Array<{
  id: ActionPresentation["group"];
  label: string;
}> = [
  { id: "inspect", label: "Inspect" },
  { id: "collect", label: "Collect evidence" },
  { id: "remediate", label: "Remediate" },
  { id: "decide", label: "Decide" },
];

function asObject(value: JsonValue | undefined): JsonObject | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value
    : null;
}

function labelFor(name: string, schema: JsonObject): string {
  const title = schema.title;
  if (typeof title === "string" && title.trim()) return title;
  return name.replaceAll("_", " ").replace(/^./, (letter) => letter.toUpperCase());
}

function enumValues(schema: JsonObject): string[] {
  return Array.isArray(schema.enum)
    ? schema.enum.filter((value): value is string => typeof value === "string")
    : [];
}

function argumentTestId(name: string): string {
  if (name === "evidence_id") return "action-evidence-reference";
  if (["site", "path", "source", "control"].includes(name)) return "action-target";
  return `action-argument-${name}`;
}

function parsedValue(value: string, schema: JsonObject): JsonValue {
  if (schema.type === "integer") return Number.parseInt(value, 10);
  if (schema.type === "number") return Number.parseFloat(value);
  if (schema.type === "boolean") return value === "true";
  return value;
}

export function RunActionComposer({
  actions,
  permittedActions,
  busy,
  resultSummary,
  suggestedValues = {},
  onAction,
}: {
  actions: ActionPresentation[];
  permittedActions: string[];
  busy: boolean;
  resultSummary: string;
  suggestedValues?: Record<string, string[]>;
  onAction: (type: string, arguments_: JsonObject) => void;
}) {
  const available = useMemo(
    () => actions.filter((action) => permittedActions.includes(action.type)),
    [actions, permittedActions],
  );
  const [selectedType, setSelectedType] = useState(available[0]?.type ?? "");
  const [values, setValues] = useState<Record<string, string>>({});

  useEffect(() => {
    if (!available.some((action) => action.type === selectedType)) {
      setSelectedType(available[0]?.type ?? "");
      setValues({});
    }
  }, [available, selectedType]);

  const selected = available.find((action) => action.type === selectedType) ?? null;
  const properties = selected ? asObject(selected.input_schema.properties) ?? {} : {};
  const required = selected && Array.isArray(selected.input_schema.required)
    ? selected.input_schema.required.filter(
        (value): value is string => typeof value === "string",
      )
    : [];
  const ready = required.every((name) => {
    const schema = asObject(properties[name]);
    const value = values[name] ?? "";
    const options = schema
      ? [...new Set([...enumValues(schema), ...(suggestedValues[name] ?? [])])]
      : [];
    return value.trim().length > 0 && (options.length === 0 || options.includes(value));
  });

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selected || !ready) return;
    const arguments_: JsonObject = {};
    for (const [name, rawSchema] of Object.entries(properties)) {
      const schema = asObject(rawSchema);
      const value = values[name];
      if (schema && value !== undefined && value !== "") {
        arguments_[name] = parsedValue(value, schema);
      }
    }
    onAction(selected.type, arguments_);
  }

  return (
    <form className="run-action-composer" onSubmit={submit}>
      <label htmlFor="run-action-picker">Simulated action</label>
      <select
        data-testid="action-picker"
        disabled={busy || available.length === 0}
        id="run-action-picker"
        onChange={(event) => {
          setSelectedType(event.target.value);
          setValues({});
        }}
        value={selectedType}
      >
        {GROUPS.map((group) => {
          const grouped = available.filter((action) => action.group === group.id);
          return grouped.length > 0 ? (
            <optgroup key={group.id} label={group.label}>
              {grouped.map((action) => (
                <option key={action.type} value={action.type}>
                  {action.title}
                </option>
              ))}
            </optgroup>
          ) : null;
        })}
      </select>

      {Object.entries(properties).map(([name, rawSchema]) => {
        const schema = asObject(rawSchema);
        if (!schema) return null;
        const options = [
          ...new Set([...enumValues(schema), ...(suggestedValues[name] ?? [])]),
        ];
        const label = labelFor(name, schema);
        const id = `run-action-${name}`;
        return (
          <div className="run-action-argument" key={name}>
            <label htmlFor={id}>{label}</label>
            {options.length > 0 ? (
              <select
                data-testid={argumentTestId(name)}
                disabled={busy}
                id={id}
                onChange={(event) =>
                  setValues((current) => ({ ...current, [name]: event.target.value }))
                }
                required={required.includes(name)}
                value={values[name] ?? ""}
              >
                <option value="">Select {label.toLocaleLowerCase()}</option>
                {options.map((option) => (
                  <option key={option} value={option}>{option}</option>
                ))}
              </select>
            ) : (
              <input
                data-testid={argumentTestId(name)}
                disabled={busy}
                id={id}
                onChange={(event) =>
                  setValues((current) => ({ ...current, [name]: event.target.value }))
                }
                required={required.includes(name)}
                type={schema.type === "integer" || schema.type === "number" ? "number" : "text"}
                value={values[name] ?? ""}
              />
            )}
          </div>
        );
      })}

      {selected && <p className="action-description">{selected.description}</p>}
      <button
        className="primary-button compact-button"
        data-testid="apply-run-action"
        disabled={busy || !selected || !ready}
        type="submit"
      >
        Apply simulated action
      </button>
      <p aria-live="polite" className="action-result" data-testid="action-result">
        {resultSummary}
      </p>
    </form>
  );
}
