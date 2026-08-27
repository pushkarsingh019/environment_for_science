import { useRef } from "react";
import type { ChangeEvent } from "react";
import { NOTE_FILE_INPUT_ID } from "../app/studioTypes";

const MAX_NOTE_BYTES = 100_000;

interface NoteImportProps {
  busy: boolean;
  onStageNote: (filename: string, content: string) => void;
  onError: (message: string) => void;
}

/** Top-bar note import: reads one local .txt file in the browser and stages filename plus text. */
export function NoteImport({ busy, onStageNote, onError }: NoteImportProps) {
  const inputRef = useRef<HTMLInputElement>(null);

  async function stageNote(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    if (!file.name.toLowerCase().endsWith(".txt")) {
      onError("Choose a local .txt note. Other file types are not read.");
      return;
    }
    if (file.size > MAX_NOTE_BYTES) {
      onError("Choose a text note no larger than 100,000 bytes.");
      return;
    }
    const content = await file.text();
    if (!content.trim() || content.includes("\0")) {
      onError("Choose a non-empty plain-text note without null characters.");
      return;
    }
    onStageNote(file.name, content);
  }

  return (
    <span className="note-import">
      <button
        className="secondary-button"
        disabled={busy}
        onClick={() => inputRef.current?.click()}
        type="button"
      >
        Import note
      </button>
      <input
        accept=".txt,text/plain"
        className="sr-only-input"
        data-testid="note-file"
        disabled={busy}
        id={NOTE_FILE_INPUT_ID}
        onChange={(event) => void stageNote(event)}
        ref={inputRef}
        tabIndex={-1}
        type="file"
      />
    </span>
  );
}
