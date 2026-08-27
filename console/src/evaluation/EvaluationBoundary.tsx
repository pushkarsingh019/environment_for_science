/** Details-rail content for Evaluate mode. The only place "Policy agent" appears on this screen. */
export function EvaluationBoundary({
  environmentKind = "eeg",
}: {
  environmentKind?: "eeg" | "mesoscope";
}): JSX.Element {
  if (environmentKind === "mesoscope") {
    return (
      <div className="evaluation-boundary">
        <h3>Separate from EEG training</h3>
        <dl className="identity-list">
          <div><dt>Apparatus</dt><dd>Sealed synthetic mesoscope</dd></div>
          <div><dt>Track</dt><dd>Platform generality</dd></div>
          <div><dt>Evidence</dt><dd>Seeded offline fixtures</dd></div>
          <div><dt>Controls</dt><dd>No operational actions</dd></div>
        </dl>
      </div>
    );
  }
  return (
    <div className="evaluation-boundary">
      <h3>Fixed and private</h3>
      <dl className="identity-list">
        <div><dt>Role</dt><dd>Policy agent</dd></div>
        <div><dt>Split</dt><dd>32 development scenarios</dd></div>
        <div><dt>Model</dt><dd>Base Gemma E4B</dd></div>
        <div><dt>Mode</dt><dd>Local inference</dd></div>
      </dl>
      <p className="rail-note">
        Scientific failures remain evidence. Adapter and inference errors are counted
        separately and never converted into scores.
      </p>
    </div>
  );
}
