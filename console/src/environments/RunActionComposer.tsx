import { useEffect, useMemo, useState } from "react";
import type { FormEvent } from "react";
import { asObject } from "../app/json";
import type { ActionPreference } from "../app/studioTypes";
import type { ActionPresentation, JsonObject, JsonValue } from "../types";

const GROUPS: Array<{ id: ActionPresentation["group"]; label: string }> = [
  { id: "inspect", label: "Inspect" },
  { id: "collect", label: "Collect evidence" },
  { id: "remediate", label: "Remediate" },
  { id: "decide", label: "Decide" },
];

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

function requiredNames(schema: JsonObject): string[] {
  return Array.isArray(schema.required)
    ? schema.required.filter((value): value is string => typeof value === "string")
    : [];
}

interface RunActionComposerProps {
  actions: ActionPresentation[];
  permittedActions: string[];
  busy: boolean;
  suggestedValues?: Record<string, string[]>;
  preferred?: ActionPreference | null;
  onPreferredConsumed?: () => void;
  onAction: (type: string, arguments_: JsonObject) => void;
}

interface ArgumentFieldProps {
  name: string;
  schema: JsonObject;
  options: string[];
  required: boolean;
  busy: boolean;
  value: string;
  onChange: (value: string) => void;
}

function ArgumentField({ name, schema, options, required, busy, value, onChange }: ArgumentFieldProps) {
  const label = labelFor(name, schema);
  const id = `run-action-${name}`;
  const numeric = schema.type === "integer" || schema.type === "number";
  return (
    <div className="run-action-argument">
      <label htmlFor={id}>{label}</label>
      {options.length > 0 ? (
        <select
          data-testid={argumentTestId(name)}
          disabled={busy}
          id={id}
          onChange={(event) => onChange(event.target.value)}
          required={required}
          value={value}
        >
          <option value="">Select {label.toLocaleLowerCase()}</option>
          {options.map((option) => (
            <option key={option} value={option}>
              {option}
            </option>
          ))}
        </select>
      ) : (
        <input
          data-testid={argumentTestId(name)}
          disabled={busy}
          id={id}
          onChange={(event) => onChange(event.target.value)}
          required={required}
          type={numeric ? "number" : "text"}
          value={value}
        />
      )}
    </div>
  );
}

/** Schema-driven action form: picker → argument fields → Apply, with nothing focusable between. */
export function RunActionComposer({
  actions,
  permittedActions,
  busy,
  suggestedValues = {},
  preferred = null,
  onPreferredConsumed,
  onAction,
}: RunActionComposerProps) {
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

  useEffect(() => {
    if (!preferred) return;
    if (available.some((action) => action.type === preferred.type)) {
      setSelectedType(preferred.type);
      setValues(preferred.values ?? {});
    }
    onPreferredConsumed?.();
  }, [preferred, available, onPreferredConsumed]);

  const selected = available.find((action) => action.type === selectedType) ?? null;
  const properties = selected ? (asObject(selected.input_schema.properties) ?? {}) : {};
  const required = selected ? requiredNames(selected.input_schema) : [];
  const optionsFor = (name: string, schema: JsonObject): string[] => [
    ...new Set([...enumValues(schema), ...(suggestedValues[name] ?? [])]),
  ];
  const ready = required.every((name) => {
    const schema = asObject(properties[name]);
    const value = values[name] ?? "";
    const options = schema ? optionsFor(name, schema) : [];
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
      <label className="sr-only" htmlFor="run-action-picker">
        Action
      </label>
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
        return (
          <ArgumentField
            busy={busy}
            key={name}
            name={name}
            onChange={(value) => setValues((current) => ({ ...current, [name]: value }))}
            options={optionsFor(name, schema)}
            required={required.includes(name)}
            schema={schema}
            value={values[name] ?? ""}
          />
        );
      })}

      <button
        className="secondary-button"
        data-testid="apply-run-action"
        disabled={busy || !selected || !ready}
        type="submit"
      >
        Apply
      </button>
      {selected && <small className="action-description">{selected.description}</small>}
    </form>
  );
}
