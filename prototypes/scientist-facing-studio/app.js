/* THROWAWAY PROTOTYPE — a deliberately simple scientist console. No APIs or persistence. */
(() => {
  "use strict";

  const variants = [
    { key: "A", name: "Apparatus console" },
    { key: "B", name: "Procedure table" },
    { key: "C", name: "Run console" },
  ];

  const data = {
    eeg: {
      short: "EEG readiness",
      title: "Auditory-localisation EEG readiness",
      mode: "Simulated apparatus",
      warning: "Simulation only — not medical guidance and not connected to physical instruments.",
      scenario: "One test flash produces two onset markers",
      terminal: "Ready for mock acquisition",
      apparatus: [
        ["32-site scalp cap", "FC3, FC4, FT7, FT8 · FCz ref · A1 ground"],
        ["S-Box → PZ5 → RZ6", "1017 Hz · 0.1–30 Hz · 50 Hz notch"],
        ["Presentation", "PsychoPy → HX3 → headphones"],
        ["Onset marker", "Lower-right flash → LM393 → NE555 → RZ6"],
        ["Response box", "Occurrence + button identity via PP24 / RZ6"],
        ["Recording room", "Sound-shielded · not electrically shielded"],
      ],
      steps: [
        { name: "Montage", observe: "Required sites, reference and ground", decide: "If a required role is missing, stop", action: "Load the seeded montage", check: "FC3/4, FT7/8, FCz and A1 match" },
        { name: "Signal", observe: "Traces, spectra and channel relationships", decide: "Local noise or shared noise?", action: "Inspect one site or reference/ground", check: "Fresh stable window; no flatline or clipping" },
        { name: "Onset", observe: "Flash and resulting marker count", decide: "If count is not one, hold", action: "Inspect simulated refractory route; retest", check: "One fresh flash creates one marker" },
        { name: "Responses", observe: "Occurrence and button identity", decide: "If they disagree, hold", action: "Test all four simulated buttons", check: "All four mappings agree" },
        { name: "Gate", observe: "Newest signal, timing and response evidence", decide: "Begin, recover once, or abort", action: "Start mock acquisition or preserve trace", check: "Every passing result follows the latest change" },
      ],
      proposal: {
        title: "Require fresh marker evidence",
        text: "After any onset-route change, only a new test flash can satisfy the one-flash/one-marker check.",
        check: "Marker evidence was collected after the latest onset-route change.",
      },
      importSample: "Operator note: the lower-right display patch drives the optical onset detector. A trigger-route change is incomplete until a fresh test flash has been reviewed.",
      run: [
        ["Observe", "One flash produced two markers 8 ms apart."],
        ["Inspect", "Refractory-timer route is bypassed."],
        ["Act", "Enable the simulated route; do not alter EEG channels."],
        ["Retest", "Fresh flash produces exactly one marker."],
        ["Check", "Newest timing evidence passes."],
      ],
    },
    mesoscope: {
      short: "Mesoscope handoff",
      title: "Four-region mesoscope handoff",
      mode: "Sealed synthetic rehearsal",
      warning: "SYNTHETIC DATA · NO HARDWARE CONNECTION · NOT LASER OR ANIMAL GUIDANCE.",
      scenario: "Four tiles complete; auxiliary event duplicated",
      terminal: "Quarantined — duplicate auxiliary marker",
      apparatus: [
        ["Independent safety gate", "Closed · view-only · no reset action"],
        ["Sealed apparatus profile", "Optical and detector settings locked"],
        ["Signed plan", "4R-HANDOFF-v1 · R1–R4 · Z-A / Z-B"],
        ["Synthetic phantom", "Cached 5 mm context · no biological meaning"],
        ["Two detector cards", "Ready · both planned channels saved"],
        ["Mock package", "TIFF-like frames · events · motion rows · checksums"],
      ],
      steps: [
        { name: "Scope", observe: "Simulation identity, watermark and seal", decide: "If any identity is absent, stop", action: "Read provenance only", check: "Synthetic, sealed and loopback-only agree" },
        { name: "Preflight", observe: "Interlock and view-only component states", decide: "If a hard gate blocks, hold", action: "Inspect and escalate; do not tune", check: "All required statuses are non-blocking" },
        { name: "Plan", observe: "Cached survey, R1–R4 and Z-A/Z-B", decide: "If identity or output slot is missing, hold", action: "Validate signed plan 4R-HANDOFF-v1", check: "Four regions map one-to-one to outputs" },
        { name: "Mock Grab", observe: "Tiles, trigger ribbon and frame identities", decide: "If runtime evidence diverges, abort or review", action: "Arm one mock Grab and observe", check: "Frames, regions and saved channels agree" },
        { name: "Review", observe: "Manifest, events, motion rows and checksums", decide: "Any mismatch means quarantine", action: "Verify or quarantine only the mock package", check: "Every expected record appears exactly once" },
      ],
      proposal: {
        title: "Show event-count agreement",
        text: "Before MOCK PACKAGE VERIFIED, compare expected and recorded auxiliary-event counts. Any mismatch quarantines the package.",
        check: "Expected and recorded auxiliary-event counts agree exactly.",
      },
      importSample: "Handoff note: signed plan 4R-HANDOFF-v1 expects R1/R2 at Z-A and R3/R4 at Z-B. Both synthetic channels are saved. This note cannot configure hardware.",
      run: [
        ["Inspect", "Sealed gates and signed plan pass."],
        ["Observe", "R1–R4 and both synthetic channels are complete."],
        ["Compare", "Expected one auxiliary event; recorded two."],
        ["Act", "Quarantine the complete-looking mock package."],
        ["Check", "Correct disposition; verification remains blocked."],
      ],
    },
  };

  const ui = { env: "eeg", selectedStep: 2, overlay: null, importText: "", importName: "Pasted note", priorFocus: null, checkNav: false };
  const freshState = () => ({ revision: 0, proposal: { eeg: "open", mesoscope: "open" }, imports: { eeg: [], mesoscope: [] }, run: { eeg: -1, mesoscope: -1 }, last: "Seed loaded" });
  let state = freshState();
  let undoStack = [];
  let redoStack = [];
  let toastTimer;

  const header = document.querySelector("#prototype-header");
  const root = document.querySelector("#variant-root");
  const footer = document.querySelector("#prototype-footer");
  const switcher = document.querySelector("#variant-switcher");
  const overlay = document.querySelector("#overlay-root");
  const toast = document.querySelector("#toast");
  const announcer = document.querySelector("#announcer");

  const current = () => data[ui.env];
  const copy = (value) => JSON.parse(JSON.stringify(value));
  const esc = (value) => String(value).replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#039;");

  function currentVariant() {
    const key = new URLSearchParams(location.search).get("variant");
    return variants.some((item) => item.key === key) ? key : "A";
  }

  function checks() {
    const list = current().steps.map((step) => step.check);
    if (state.proposal[ui.env] === "applied") list.push(current().proposal.check);
    return list;
  }

  function runStatus() {
    const index = state.run[ui.env];
    if (index < 0) return "Not run";
    if (index === current().run.length - 1) return current().terminal;
    return `Step ${index + 1} of ${current().run.length}`;
  }

  function mutate(label, callback, editsDraft = false) {
    undoStack.push(copy(state));
    redoStack = [];
    callback(state);
    if (editsDraft && state.run[ui.env] >= 0) state.run[ui.env] = -1;
    state.revision += 1;
    state.last = label;
    render();
    showToast(`${label} · memory only`);
  }

  function undo() {
    if (!undoStack.length) return;
    redoStack.push(copy(state));
    state = undoStack.pop();
    render();
    showToast("Undid last change");
  }

  function redo() {
    if (!redoStack.length) return;
    undoStack.push(copy(state));
    state = redoStack.pop();
    render();
    showToast("Redid change");
  }

  function showToast(message) {
    clearTimeout(toastTimer);
    toast.textContent = message;
    toast.classList.add("show");
    announcer.textContent = message;
    toastTimer = setTimeout(() => toast.classList.remove("show"), 1800);
  }

  function setVariant(key) {
    const params = new URLSearchParams(location.search);
    params.set("variant", key);
    history.replaceState({}, "", `${location.pathname}?${params}${location.hash}`);
    render();
  }

  function cycle(direction) {
    const index = variants.findIndex((item) => item.key === currentVariant());
    setVariant(variants[(index + direction + variants.length) % variants.length].key);
  }

  function renderHeader() {
    header.innerHTML = `
      <div class="brand"><span class="brand-mark">E</span><span>Environment Studio</span><span class="throwaway">prototype</span></div>
      <div class="env-switch" role="group" aria-label="Seed environment">
        <button type="button" data-action="env" data-env="eeg" aria-pressed="${ui.env === "eeg"}">EEG</button>
        <button type="button" data-action="env" data-env="mesoscope" aria-pressed="${ui.env === "mesoscope"}">Mesoscope</button>
      </div>
      <div class="header-spacer"></div>
      <span class="memory-label">State ${state.revision} · memory only</span>
      <div class="header-actions">
        <button class="btn" type="button" data-action="import">Import note</button>
        <button class="icon-btn" type="button" data-action="undo" aria-label="Undo" ${undoStack.length ? "" : "disabled"}>↶</button>
        <button class="icon-btn" type="button" data-action="redo" aria-label="Redo" ${redoStack.length ? "" : "disabled"}>↷</button>
      </div>`;
  }

  function renderSwitcher() {
    const key = currentVariant();
    const index = variants.findIndex((item) => item.key === key);
    switcher.innerHTML = `<button type="button" data-action="prev" aria-label="Previous variant">←</button><div class="switcher-copy"><small>${index + 1} / 3 · console variants</small><strong>${key} — ${variants[index].name}</strong></div><button type="button" data-action="next" aria-label="Next variant">→</button>`;
  }

  function sidebar(active) {
    return `<aside class="sidebar">
      <div class="side-head">Environment</div>
      ${[["apparatus","▦","Apparatus","A",""],["procedure","☷","Procedure","B",""],["evidence","⌁","Observations & actions","C",""],["checks","✓","Checks","C","checks"]].map(([key,icon,label,variant,focus]) => `<button class="nav-row ${active === key ? "active" : ""}" type="button" data-action="goto" data-variant="${variant}" data-focus="${focus}"><span class="nav-icon">${icon}</span>${label}</button>`).join("")}
      <div class="side-head">Sources</div>
      <button class="nav-row" type="button" data-action="import"><span class="nav-icon">＋</span>Manual import <span style="margin-left:auto;color:var(--faint)">${state.imports[ui.env].length}</span></button>
      <div class="side-note"><strong>${esc(current().mode)}</strong>${esc(current().warning)}</div>
    </aside>`;
  }

  function workspaceHead(section) {
    return `<div class="workspace-head"><div><div class="breadcrumb">${section} / ${esc(current().short)}</div><h1>${esc(current().title)}</h1><p class="workspace-sub">Drafted in scientist language. No code, wiring editor or physical controls.</p></div><span class="mode-badge">${esc(current().mode)}</span></div><div class="safety-line">${esc(current().warning)}</div>`;
  }

  function eegVisual() {
    return `<div class="visual"><svg viewBox="0 0 760 310" role="img" aria-label="Simulated EEG traces and onset markers">
      <rect width="760" height="310" fill="#f7f7f5"/><g stroke="#e6e6e6" stroke-width="1">${[70,120,170,220].map(y=>`<line x1="70" y1="${y}" x2="730" y2="${y}"/>`).join("")}</g>
      <g fill="#615d59" font-family="system-ui" font-size="11"><text x="22" y="73">FC3</text><text x="22" y="123">FC4</text><text x="22" y="173">FT7</text><text x="22" y="223">FT8</text></g>
      <g fill="none" stroke-width="2"><path stroke="#0075de" d="M70 68 ${wave(68,660,0)}"/><path stroke="#31302e" d="M70 118 ${wave(118,660,13)}"/><path stroke="#9a6700" d="M70 168 ${wave(168,660,25)}"/><path stroke="#9a6700" d="M266 168 L276 144 L284 190 L294 151 L304 168"/><path stroke="#777" d="M70 218 ${wave(218,660,7)}"/></g>
      <line x1="70" y1="267" x2="730" y2="267" stroke="#d4d4d4"/><g font-family="system-ui" font-size="9"><text x="70" y="289" fill="#615d59">EVENT LANE</text><text x="451" y="289" fill="#9a6700">FLASH</text><text x="505" y="289" fill="#b42318">2 MARKERS</text></g><line x1="470" y1="257" x2="470" y2="277" stroke="#9a6700" stroke-width="3"/><line x1="515" y1="257" x2="515" y2="277" stroke="#b42318" stroke-width="3"/><line x1="528" y1="257" x2="528" y2="277" stroke="#b42318" stroke-width="3"/>
    </svg><span class="watermark">SYNTHETIC EEG · EEG-017</span></div>`;
  }

  function wave(y, width, phase) {
    let out = "";
    for (let x = 0; x <= width; x += 10) out += ` L${70 + x} ${y + Math.sin((x + phase) / 18) * 9}`;
    return out;
  }

  function mesoVisual() {
    return `<div class="visual"><svg viewBox="0 0 760 310" role="img" aria-label="Cached synthetic mesoscope survey with four signed regions">
      <rect width="760" height="310" fill="#f7f7f5"/><rect x="26" y="24" width="420" height="250" rx="6" fill="#e8ece9" stroke="#d4d4d4"/>
      <g fill="none" stroke="#7b8d82"><path d="M48 244 C105 180 116 195 171 126 C212 75 261 101 295 39 M171 126 C196 165 220 190 247 244 M268 136 C320 110 348 72 420 54 M303 143 C350 171 365 230 427 247" stroke-width="5" opacity=".35"/><path d="M48 244 C105 180 116 195 171 126 C212 75 261 101 295 39 M171 126 C196 165 220 190 247 244 M268 136 C320 110 348 72 420 54 M303 143 C350 171 365 230 427 247" stroke-width="1.5"/></g>
      <g fill="none" stroke="#0075de" stroke-width="2"><rect x="88" y="70" width="66" height="66"/><rect x="317" y="57" width="66" height="66"/><rect x="155" y="183" width="66" height="66"/><rect x="343" y="177" width="66" height="66"/></g>
      <g fill="#0075de" font-family="system-ui" font-size="9"><text x="92" y="83">R1 · Z-A</text><text x="321" y="70">R2 · Z-A</text><text x="159" y="196">R3 · Z-B</text><text x="347" y="190">R4 · Z-B</text></g>
      ${[0,1,2,3].map(i=>`<g transform="translate(${478+(i%2)*128} ${24+Math.floor(i/2)*127})"><rect width="112" height="112" rx="5" fill="#e5ebe7" stroke="#d4d4d4"/>${Array.from({length:10},(_,n)=>`<circle cx="${14+(n*29+i*11)%84}" cy="${20+(n*19+i*7)%75}" r="${3+n%4}" fill="none" stroke="#627a6c"/>`).join("")}<text x="7" y="13" fill="#0075de" font-family="system-ui" font-size="8">R${i+1} · ${i<2?"Z-A":"Z-B"}</text></g>`).join("")}
      <text x="26" y="294" fill="#615d59" font-family="system-ui" font-size="9">SIGNED PLAN 4R-HANDOFF-v1</text><text x="266" y="294" fill="#b42318" font-family="system-ui" font-size="9">EXPECTED AUX 1 · RECORDED 2</text>
    </svg><span class="watermark">SYNTHETIC · SEALED · MESO-021</span></div>`;
  }

  const visual = () => ui.env === "eeg" ? eegVisual() : mesoVisual();

  function eegReferenceVisual(kind) {
    const hardware = kind === "hardware";
    return `<figure class="literal-visual"><img src="assets/${hardware ? "eeg-hardware-crop.png" : "eeg-room-topology-crop.png"}" alt="${hardware ? "Reference photograph showing the RZ6 processor, PZ5 preamplifier and 32-channel S-Box" : "Reference apparatus diagram showing the participant, sound chamber, monitor, PZ5, S-Box, RZ6 and experimenter computer"}"><figcaption><b>${hardware ? "Literal apparatus reference" : "Literal room topology"}</b><span>Source: supplied thesis figure · used as visual context, not a control surface</span></figcaption></figure>`;
  }

  function apparatusVisual(kind) {
    return ui.env === "eeg" ? eegReferenceVisual(kind) : mesoVisual();
  }

  function contract() {
    const step = current().steps[ui.selectedStep];
    return `<div class="contract-row"><div class="contract-cell"><b>Observe</b><span>${esc(step.observe)}</span></div><div class="contract-cell"><b>If / decide</b><span>${esc(step.decide)}</span></div><div class="contract-cell"><b>Action</b><span>${esc(step.action)}</span></div><div class="contract-cell"><b>Pass when</b><span>${esc(step.check)}</span></div></div>`;
  }

  function stepStrip() {
    return `<div class="step-strip">${current().steps.map((step,index)=>`<button class="step ${ui.selectedStep===index?"active":""}" type="button" data-action="step" data-index="${index}"><small>0${index+1}</small><strong>${esc(step.name)}</strong></button>`).join("")}</div>`;
  }

  function assistantPanel() {
    const status = state.proposal[ui.env];
    const actions = status === "open" ? `<button class="primary-btn" type="button" data-action="apply">Apply edit</button><button class="btn" type="button" data-action="dismiss">Dismiss</button>` : `<span class="status-badge ${status === "applied" ? "good" : ""}">${status}</span><button class="btn" type="button" data-action="reopen">${status === "applied" ? "Revert" : "Restore"}</button>`;
    return `<section class="panel assistant-panel"><div class="panel-head"><div class="assistant-title"><span class="assistant-avatar">A</span><div><h2>Authoring assistant</h2><p>Draft only · absent from test runs</p></div></div></div><div class="proposal"><span class="panel-label">Proposed edit</span><h3>${esc(current().proposal.title)}</h3><p>${esc(current().proposal.text)}</p><div class="proposal-change">${esc(current().proposal.check)}</div><div class="button-row">${actions}</div></div></section>`;
  }

  function policyPanel(compact = false) {
    const index = state.run[ui.env];
    return `<section class="panel policy-panel"><div class="panel-head"><div><h2>Policy-agent test run</h2><p>Frozen Environment · all permitted simulated actions</p></div><span class="status-badge ${index === current().run.length-1 ? "good" : ""}">${esc(runStatus())}</span></div><div class="run-summary"><span class="panel-label">Scenario</span><strong>${esc(current().scenario)}</strong><p>Authoring assistant is not in this run. A draft edit resets it.</p><div class="button-row"><button class="primary-btn" type="button" data-action="run-next" ${index===current().run.length-1?"disabled":""}>${index<0?"Start test":"Next"}</button><button class="btn" type="button" data-action="run-all" ${index===current().run.length-1?"disabled":""}>Run all</button><button class="btn" type="button" data-action="run-reset" ${index<0?"disabled":""}>Reset</button></div></div>${compact?"":`<div class="run-trace">${current().run.map((line,i)=>`<div class="run-line ${index>=i?"reached":""}"><b>${esc(line[0])}</b><span>${esc(line[1])}</span></div>`).join("")}</div>`}</section>`;
  }

  function stateBar() {
    return `<div class="state-bar"><span><strong>${current().apparatus.length}</strong> apparatus parts</span><span><strong>${current().steps.length}</strong> procedure steps</span><span><strong>${checks().length}</strong> exact checks</span><span><strong>${state.imports[ui.env].length}</strong> imports</span><span>Assistant: <strong>${state.proposal[ui.env]}</strong></span><span>Test: <strong>${esc(runStatus())}</strong></span><button class="link-btn" type="button" data-action="state">View state</button></div>`;
  }

  function componentList() {
    return `<div class="component-list">${current().apparatus.map(item=>`<div class="component"><b>${esc(item[0])}</b><span>${esc(item[1])}</span></div>`).join("")}</div>`;
  }

  function spatialCanvas() {
    if (ui.env !== "eeg") {
      return `<section class="panel"><div class="panel-head"><div><h2>Sealed synthetic apparatus</h2><p>Four-region handoff</p></div><span class="status-badge warn">Synthetic only</span></div><div class="panel-body">${mesoVisual()}</div></section>`;
    }
    return `<section class="spatial-canvas" aria-label="Spatial EEG apparatus canvas">
      <div class="canvas-toolbar"><span><b>Sound chamber</b> · spatial view</span><span class="status-badge good">Simulation</span></div>
      <div class="lab-scene">
        <div class="floor-plane" aria-hidden="true"></div>
        <div class="room-plane" aria-hidden="true"><span>Sound chamber</span></div>
        <svg class="scene-links" viewBox="0 0 1000 590" preserveAspectRatio="none" aria-hidden="true">
          <path class="link data" d="M735 218 C675 240 625 268 575 312"/>
          <path class="link data" d="M575 312 C520 365 500 402 485 452"/>
          <path class="link control" d="M485 452 C365 485 290 495 225 510"/>
          <path class="link stimulus" d="M260 190 C410 155 610 135 795 150"/>
          <path class="link timing" d="M260 210 C420 240 590 215 785 180"/>
          <circle cx="735" cy="218" r="5"/><circle cx="575" cy="312" r="5"/><circle cx="485" cy="452" r="5"/>
        </svg>

        <div class="scene-node node-display" title="Participant display and lower-right onset patch">
          <div class="monitor-device"><div class="monitor-screen"><span></span></div><i></i></div><label>Display</label>
        </div>
        <div class="scene-node node-participant"><img src="assets/participant-line.png" alt="Participant"><label>Participant</label></div>
        <div class="scene-node node-headphones" title="DT-770 Pro headphones"><div class="headphone-device">◖<span></span>◗</div><label>Headphones</label></div>
        <div class="scene-node node-pz5"><img src="assets/device-pz5.png" alt="PZ5 neurodigitizer"><label>PZ5</label></div>
        <div class="scene-node node-sbox"><img src="assets/device-sbox.png" alt="32-channel S-Box"><label>32-ch S-Box</label></div>
        <div class="scene-node node-rz6"><img src="assets/device-rz6.png" alt="RZ6 processor"><label>RZ6</label></div>
        <div class="scene-node node-computer"><div class="computer-device"><div>EEG</div></div><label>Computer</label></div>
        <div class="scene-node node-experimenter"><img src="assets/experimenter-line.png" alt="Experimenter"><label>Experimenter</label></div>
        <div class="scene-node node-response"><div class="response-device"><i></i><i></i><i></i><i></i></div><label>Response</label></div>

        <div class="scene-key"><span><i class="key-data"></i>EEG</span><span><i class="key-stimulus"></i>stimulus</span><span><i class="key-timing"></i>marker</span></div>
      </div>
    </section>`;
  }

  function canvasDock() {
    const proposal = state.proposal[ui.env];
    const runIndex = state.run[ui.env];
    return `<div class="canvas-dock">
      <div class="dock-group authoring-dock"><span class="assistant-avatar">A</span><span><b>Authoring assistant</b><small>${proposal === "open" ? "1 suggested edit" : proposal}</small></span>${proposal === "open" ? `<button class="btn" type="button" data-action="apply">Apply</button>` : `<button class="btn" type="button" data-action="reopen">Revert</button>`}</div>
      <div class="dock-divider"><span>separate</span></div>
      <div class="dock-group policy-dock"><span class="policy-dot"></span><span><b>Policy test</b><small>${esc(runStatus())}</small></span><button class="primary-btn" type="button" data-action="run-next" ${runIndex === current().run.length - 1 ? "disabled" : ""}>${runIndex < 0 ? "Start" : "Next"}</button><button class="btn" type="button" data-action="run-reset" ${runIndex < 0 ? "disabled" : ""}>Reset</button></div>
      <div class="dock-stats"><span>${current().apparatus.length} parts</span><span>${current().steps.length} steps</span><span>${checks().length} checks</span></div>
    </div>`;
  }

  function renderA() {
    return `<div class="console variant-a">${sidebar("apparatus")}<section class="workspace spatial-workspace">
      <div class="spatial-head"><div><div class="breadcrumb">EEG apparatus / canvas</div><h1>${esc(current().title)}</h1></div><div class="button-row"><button class="btn" type="button" data-action="goto" data-variant="B">Procedure</button><button class="btn" type="button" data-action="goto" data-variant="C">Run view</button></div></div>
      ${spatialCanvas()}${canvasDock()}
    </section></div>`;
  }

  function renderB() {
    return `<div class="console variant-b">${sidebar("procedure")}<section class="workspace">${workspaceHead("Procedure")}
      <div class="b-layout"><div class="b-main"><section class="panel"><div class="panel-head"><div><h2>Apparatus context</h2><p>Only the structure needed to understand the procedure</p></div></div><div class="mini-visual">${apparatusVisual("topology")}<div class="apparatus-index">${current().apparatus.map(item=>`<div class="index-item"><b>${esc(item[0])}</b><span>${esc(item[1])}</span></div>`).join("")}</div></div></section>
      <section class="panel"><div class="panel-head"><div><h2>Adaptive procedure</h2><p>One row per scientific decision</p></div></div><table class="procedure-table"><thead><tr><th style="width:13%">Stage</th><th>Observe</th><th>If / decide</th><th>Action</th><th>Pass when</th></tr></thead><tbody>${current().steps.map((step,index)=>`<tr class="${ui.selectedStep===index?"selected":""}"><td><button type="button" data-action="step" data-index="${index}">${esc(step.name)}</button></td><td>${esc(step.observe)}</td><td>${esc(step.decide)}</td><td>${esc(step.action)}</td><td>${esc(step.check)}</td></tr>`).join("")}</tbody></table></section></div>
      <aside class="b-aside">${assistantPanel()}<section class="panel"><div class="panel-head"><div><h2>Draft inputs</h2><p>Manual, local and reversible</p></div><button class="btn" type="button" data-action="import">Import</button></div><div class="source-row"><span class="source-dot"></span><span>Seeded apparatus model</span></div><div class="source-row"><span class="source-dot"></span><span>${state.imports[ui.env].length} manually imported note(s)</span></div></section><div class="role-separator">separate run boundary</div>${policyPanel(false)}</aside></div>${stateBar()}</section></div>`;
  }

  function renderC() {
    const runIndex = state.run[ui.env];
    return `<div class="console variant-c">${sidebar(ui.checkNav ? "checks" : "evidence")}<section class="workspace">${workspaceHead("Test run")}
      <div class="c-layout"><div class="c-main"><section class="panel stage"><div class="panel-head"><div><h2>Policy-agent run</h2><p>Frozen Environment · Authoring assistant absent</p></div><span class="status-badge ${runIndex===current().run.length-1?"good":"warn"}">${esc(runStatus())}</span></div><div class="panel-body">${visual()}</div><div class="timeline">${current().run.map((item,index)=>`<div class="timeline-item ${runIndex>=index?"reached":""}"><div class="timeline-dot"></div><b>${esc(item[0])}</b><br>${esc(item[1])}</div>`).join("")}</div><div class="run-summary"><div class="button-row"><button class="primary-btn" type="button" data-action="run-next" ${runIndex===current().run.length-1?"disabled":""}>${runIndex<0?"Start test":"Next evidence"}</button><button class="btn" type="button" data-action="run-all" ${runIndex===current().run.length-1?"disabled":""}>Run all</button><button class="btn" type="button" data-action="run-reset" ${runIndex<0?"disabled":""}>Reset</button></div></div></section>${stepStrip()}${contract()}</div>
      <aside class="c-aside"><section class="panel" id="exact-checks"><div class="panel-head"><div><h2>Exact checks</h2><p>Deterministic, scientist-readable</p></div></div>${checks().map(check=>`<div class="check-row"><span class="check-icon">○</span><span>${esc(check)}</span></div>`).join("")}</section><div class="role-separator">authoring workspace</div>${assistantPanel()}<section class="panel"><div class="panel-head"><div><h2>Apparatus</h2><p>${current().apparatus.length} grouped parts</p></div><button class="btn" type="button" data-action="import">Import note</button></div>${current().apparatus.slice(0,3).map(item=>`<div class="source-row"><span class="source-dot"></span><span><b>${esc(item[0])}</b><br>${esc(item[1])}</span></div>`).join("")}</section></aside></div>${stateBar()}</section></div>`;
  }

  function renderOverlay() {
    if (ui.overlay === "import") {
      overlay.innerHTML = `<div class="overlay" data-action="close"><section class="dialog" data-dialog role="dialog" aria-modal="true" aria-labelledby="import-title"><div class="dialog-head"><div><h2 id="import-title">Import a lab note</h2><p>Local text only. Nothing is uploaded or treated as truth automatically.</p></div><button class="icon-btn" type="button" data-action="close">×</button></div><div class="dialog-body"><div class="import-note">Descriptive input only; it cannot control a physical apparatus${ui.env==="mesoscope"?" or configure optics/detectors":""}.</div><input id="import-file" type="file" accept=".txt,.md,.json,text/plain" aria-label="Choose text note"><textarea id="import-text" placeholder="Paste an apparatus note or procedure outline…">${esc(ui.importText)}</textarea><div class="dialog-actions"><button class="btn" type="button" data-action="sample">Load sample</button><button class="btn" type="button" data-action="close">Cancel</button><button class="primary-btn" type="button" data-action="save-import">Add to draft</button></div></div></section></div>`;
    } else if (ui.overlay === "state") {
      overlay.innerHTML = `<div class="overlay" data-action="close"><section class="dialog" data-dialog role="dialog" aria-modal="true" aria-labelledby="state-title"><div class="dialog-head"><div><h2 id="state-title">Current in-memory state</h2><p>${esc(state.last)} · cleared on reload</p></div><button class="icon-btn" type="button" data-action="close">×</button></div><div class="dialog-body"><ul class="state-list"><li><b>Environment:</b> ${esc(current().title)}</li><li><b>Apparatus:</b> ${current().apparatus.map(x=>esc(x[0])).join(" · ")}</li><li><b>Procedure:</b> ${current().steps.map(x=>esc(x.name)).join(" → ")}</li><li><b>Checks:</b> ${checks().length}</li><li><b>Manual imports:</b> ${state.imports[ui.env].length}</li><li><b>Authoring-assistant edit:</b> ${esc(state.proposal[ui.env])}</li><li><b>Policy-agent test:</b> ${esc(runStatus())}</li></ul></div></section></div>`;
    } else overlay.innerHTML = "";
  }

  function render() {
    renderHeader();
    renderSwitcher();
    const key = currentVariant();
    document.body.dataset.variant = key;
    document.title = `${key} · ${variants.find(item=>item.key===key).name} — scientist console prototype`;
    root.innerHTML = key === "A" ? renderA() : key === "B" ? renderB() : renderC();
    footer.innerHTML = "";
    renderOverlay();
  }

  function openOverlay(type) {
    ui.priorFocus = document.activeElement;
    ui.overlay = type;
    if (type === "import") { ui.importText = ""; ui.importName = "Pasted note"; }
    renderOverlay();
    requestAnimationFrame(() => overlay.querySelector(type === "import" ? "#import-text" : "[data-action='close']")?.focus());
  }

  function closeOverlay() { ui.overlay = null; renderOverlay(); ui.priorFocus?.focus?.(); }

  function handle(target) {
    const action = target.dataset.action;
    if (action === "prev") cycle(-1);
    else if (action === "next") cycle(1);
    else if (action === "env") { ui.env = target.dataset.env; ui.selectedStep = 2; render(); }
    else if (action === "goto") {
      ui.checkNav = target.dataset.focus === "checks";
      setVariant(target.dataset.variant);
      if (ui.checkNav) requestAnimationFrame(() => document.querySelector("#exact-checks")?.scrollIntoView({ block: "start" }));
    }
    else if (action === "step") { ui.selectedStep = Number(target.dataset.index); render(); }
    else if (action === "undo") undo();
    else if (action === "redo") redo();
    else if (action === "import") openOverlay("import");
    else if (action === "state") openOverlay("state");
    else if (action === "close") closeOverlay();
    else if (action === "sample") { ui.importText = current().importSample; ui.importName = `${current().short} note`; document.querySelector("#import-text").value = ui.importText; }
    else if (action === "save-import") {
      const text = document.querySelector("#import-text")?.value.trim().slice(0,8000);
      if (!text) { showToast("Add text first"); return; }
      ui.overlay = null;
      mutate("Imported lab note", draft => draft.imports[ui.env].push({ name: ui.importName, text }), true);
    }
    else if (action === "apply") mutate("Applied Authoring-assistant edit", draft => { draft.proposal[ui.env] = "applied"; }, true);
    else if (action === "dismiss") mutate("Dismissed Authoring-assistant edit", draft => { draft.proposal[ui.env] = "dismissed"; });
    else if (action === "reopen") mutate("Restored Authoring-assistant edit", draft => { draft.proposal[ui.env] = "open"; }, state.proposal[ui.env] === "applied");
    else if (action === "run-next") mutate("Advanced mocked Policy-agent run", draft => { draft.run[ui.env] = Math.min(draft.run[ui.env] + 1, current().run.length - 1); });
    else if (action === "run-all") mutate("Completed mocked Policy-agent run", draft => { draft.run[ui.env] = current().run.length - 1; });
    else if (action === "run-reset") mutate("Reset mocked Policy-agent run", draft => { draft.run[ui.env] = -1; });
  }

  document.addEventListener("click", event => {
    const target = event.target.closest("[data-action]");
    if (!target) return;
    if (target.classList.contains("overlay") && event.target !== target) return;
    event.preventDefault();
    handle(target);
  });
  document.addEventListener("input", event => { if (event.target.id === "import-text") ui.importText = event.target.value; });
  document.addEventListener("change", event => {
    if (event.target.id !== "import-file" || !event.target.files?.[0]) return;
    const file = event.target.files[0];
    const reader = new FileReader();
    reader.onload = () => { ui.importName = file.name; ui.importText = String(reader.result || "").slice(0,8000); document.querySelector("#import-text").value = ui.importText; };
    reader.readAsText(file);
  });
  document.addEventListener("keydown", event => {
    if (event.key === "Escape" && ui.overlay) { event.preventDefault(); closeOverlay(); return; }
    if (ui.overlay || !["ArrowLeft","ArrowRight"].includes(event.key)) return;
    const tag = event.target.tagName?.toLowerCase();
    if (["input","textarea","select"].includes(tag) || event.target.isContentEditable) return;
    event.preventDefault(); cycle(event.key === "ArrowLeft" ? -1 : 1);
  });
  addEventListener("popstate", render);
  render();
})();
