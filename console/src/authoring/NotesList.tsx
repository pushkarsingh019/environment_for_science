import type { DraftNote } from "../types";

/** Staged descriptive notes; renders nothing when the draft holds none. */
export function NotesList({ notes }: { notes: DraftNote[] }) {
  if (notes.length === 0) return null;
  return (
    <ul aria-label="Staged descriptive notes" className="draft-notes">
      {notes.map((note) => (
        <li className="draft-note" data-testid={`draft-note-${note.filename}`} key={note.id}>
          <strong>{note.filename}</strong>
          <span className="note-tag">Unverified descriptive input</span>
          <p>{note.content}</p>
          <small>Cannot control a run.</small>
        </li>
      ))}
    </ul>
  );
}
