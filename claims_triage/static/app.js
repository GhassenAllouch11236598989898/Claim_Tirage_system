/**
 * Autonomous Multi-Agent Insurance Claims Triage System
 * Interactive Dashboard Logic - Dual Mode (FastAPI Backend + Offline Simulation)
 */

const SCENARIOS = [
  {
    id: "auto-minor",
    label: "Minor Auto",
    outcome: "pass",
    claimant: "Sarah Jenkins",
    policy: "POL-2024-8849",
    amount: 1200,
    limit: 50000,
    desc: "Low-speed parking lot collision. Minor dent and paint scuff on rear bumper. No injuries.",
    support: "Police report #49281, repair estimate $1,180.",
    sim: {
      classifier: { category: "auto", sub_category: "low_speed_collision", confidence: 0.98, reasoning: "Parking lot vehicle collision with cosmetic bumper damage only.", tokens: 412, latency: 0.38, anomaly: "⚠️ Potential" },
      severity:   { severity: "low", estimated_payout: 1180, confidence: 0.96, risk_factors: ["Minor cosmetic damage"], reasoning: "Claimed $1,200 is within standard minor repair thresholds.", tokens: 489, latency: 0.44, anomaly: "⚠️ Potential" },
      reviewer:   { overall_confidence: 0.95, recommendation: "approve_auto", flags: [], requires_human_review: false, reasoning: "High confidence across all agents. Straightforward claim.", tokens: 580, latency: 0.51, anomaly: "-" },
      human_gate: { routed_to_human: false, reason: "All checks passed — auto-approved", auto_decision: "approve", final_payout: 1180, tokens: 0, latency: 0.05, anomaly: "-" }
    }
  },
  {
    id: "prop-water",
    label: "Water Damage (Burst Pipe)",
    outcome: "pass",
    claimant: "Robert Martinez",
    policy: "HOM-7721-094",
    amount: 8500,
    limit: 300000,
    desc: "Copper pipe burst overnight. Water leaked through ceiling, damaging drywall and hardwood flooring.",
    support: "Plumber invoice $850, restoration estimate $7,650.",
    sim: {
      classifier: { category: "property", sub_category: "water_damage", confidence: 0.97, reasoning: "Residential water damage from plumbing failure.", tokens: 395, latency: 0.35, anomaly: "⚠️ Potential" },
      severity:   { severity: "low", estimated_payout: 8500, confidence: 0.91, risk_factors: ["Potential subfloor moisture"], reasoning: "Standard water mitigation costs well within policy limit.", tokens: 460, latency: 0.41, anomaly: "⚠️ Potential" },
      reviewer:   { overall_confidence: 0.92, recommendation: "approve_auto", flags: [], requires_human_review: false, reasoning: "Licensed contractor docs provided. Meets auto-approval criteria.", tokens: 530, latency: 0.49, anomaly: "-" },
      human_gate: { routed_to_human: false, reason: "All checks passed — auto-approved", auto_decision: "approve", final_payout: 8500, tokens: 0, latency: 0.04, anomaly: "-" }
    }
  },
  {
    id: "multi-collision",
    label: "Highway Multi-Collision",
    outcome: "escalate",
    claimant: "Elena Rostova",
    policy: "AUT-9912-340",
    amount: 125000,
    limit: 250000,
    desc: "Four-vehicle chain pileup on highway. Engine fire, driver concussion, passenger fractured clavicle.",
    support: "Highway patrol logs, EMT records, towing invoices.",
    sim: {
      classifier: { category: "auto", sub_category: "multi_vehicle", confidence: 0.94, reasoning: "Multi-car collision with bodily injuries and vehicle fire.", tokens: 430, latency: 0.42, anomaly: "⚠️ Potential" },
      severity:   { severity: "high", estimated_payout: 125000, confidence: 0.88, risk_factors: ["Comparative negligence", "Bodily injury", "Total loss"], reasoning: "Six-figure exposure combining vehicle loss and medical treatment.", tokens: 512, latency: 0.47, anomaly: "⚠️ Potential" },
      reviewer:   { overall_confidence: 0.79, recommendation: "needs_human_review", flags: ["Multiple carriers involved", "Disputed fault"], requires_human_review: true, reasoning: "Inter-carrier subrogation required for fault apportionment.", tokens: 615, latency: 0.58, anomaly: "⚠️ High risk" },
      human_gate: { routed_to_human: true, reason: "Severity HIGH; Confidence 0.79 < 0.8; Reviewer flagged", tokens: 0, latency: 0.05, anomaly: "⚠️ Pending Review" }
    }
  },
  {
    id: "injury-severe",
    label: "Catastrophic Spinal Injury",
    outcome: "escalate",
    claimant: "David Henderson",
    policy: "MED-5501-831",
    amount: 750000,
    limit: 1000000,
    desc: "Scaffolding collapse resulting in lumbar fractures, spinal surgery, and ICU hospitalization.",
    support: "Hospital records, surgeon reports, OSHA report #19-482.",
    sim: {
      classifier: { category: "injury", sub_category: "catastrophic_bodily", confidence: 0.99, reasoning: "Severe spinal trauma requiring surgical intervention.", tokens: 440, latency: 0.40, anomaly: "⚠️ Potential" },
      severity:   { severity: "high", estimated_payout: 750000, confidence: 0.94, risk_factors: ["Litigation risk", "Long-term rehab", "OSHA investigation"], reasoning: "Life-altering injuries with six-figure medical expenses.", tokens: 530, latency: 0.49, anomaly: "⚠️ Potential" },
      reviewer:   { overall_confidence: 0.76, recommendation: "needs_human_review", flags: ["OSHA investigation pending", "Multi-party liability"], requires_human_review: true, reasoning: "High-exposure case requires senior adjuster review.", tokens: 620, latency: 0.59, anomaly: "⚠️ High risk" },
      human_gate: { routed_to_human: true, reason: "Severity HIGH; Confidence 0.76 < 0.8; Reviewer flagged", tokens: 0, latency: 0.06, anomaly: "⚠️ Pending Review" }
    }
  },
  {
    id: "prop-fire",
    label: "Commercial Warehouse Fire",
    outcome: "escalate",
    claimant: "Apex Logistics LLC",
    policy: "COM-1049-772",
    amount: 350000,
    limit: 500000,
    desc: "Electrical failure in battery storage caused structural fire. Total racking and inventory destruction.",
    support: "Fire Marshal report, inventory telemetry records.",
    sim: {
      classifier: { category: "property", sub_category: "commercial_fire", confidence: 0.99, reasoning: "Major commercial fire with electrical origin causing wholesale destruction.", tokens: 450, latency: 0.43, anomaly: "⚠️ Potential" },
      severity:   { severity: "high", estimated_payout: 350000, confidence: 0.92, risk_factors: ["Arson clearance needed", "High-value inventory audit"], reasoning: "Extensive damage approaching policy limit.", tokens: 520, latency: 0.48, anomaly: "⚠️ Potential" },
      reviewer:   { overall_confidence: 0.77, recommendation: "needs_human_review", flags: ["Cause determination pending"], requires_human_review: true, reasoning: "Commercial loss requires forensic accounting signoff.", tokens: 610, latency: 0.57, anomaly: "⚠️ High risk" },
      human_gate: { routed_to_human: true, reason: "Severity HIGH; Confidence 0.77 < 0.8; Reviewer flagged", tokens: 0, latency: 0.05, anomaly: "⚠️ Pending Review" }
    }
  }
];

// ── Application State ────────────────────────────────────────────────────────
const state = {
  currentScenario: SCENARIOS[0],
  processing: false,
  activeInspectorAgent: "classifier",
  outputs: {},
  totalTokens: 1894,
  isLiveBackend: false
};

// ── Initialization ──────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
  renderScenariosModal();
  checkBackendHealth();
  
  // Render default state matching user reference screenshot
  initDefaultDisplay();

  // Dynamic SVG curve adjustment on resize
  window.addEventListener("resize", () => {
    updateSvgCurves();
  });
});

// ── Render Default Matching Screenshot ──────────────────────────────────────
function initDefaultDisplay() {
  document.getElementById("current-pipeline-label").textContent = "DAG pipeline";
  setDagStatus("Pending", "amber");
  
  const tokEl = document.getElementById("metric-tokens-val");
  if (tokEl) tokEl.textContent = "1,894";

  // Initial table matching user image exactly
  renderInitialTelemetryTable();

  // Setup curves
  setTimeout(updateSvgCurves, 100);
}

function renderInitialTelemetryTable() {
  const tbody = document.getElementById("telemetry-tbody");
  if (!tbody) return;

  const rows = [
    { agent: "Agents activity, 1:09 PM", status: "Pending", statusClass: "pending", name: "Classifier", proc: "129 minutes", lat: "00:3s", anom: "⚠️ Potential", anomClass: "" },
    { agent: "Agents activity, 1:09 PM", status: "Pending", statusClass: "pending", name: "Severity Scorer", proc: "125 minutes", lat: "00:3s", anom: "⚠️ Potential", anomClass: "warning" },
    { agent: "Agents activity, 1:09 PM", status: "Gate", statusClass: "gate", name: "Reviewer QA", proc: "125 minutes", lat: "00:3s", anom: "-", anomClass: "" },
    { agent: "Agents activity, 1:09 PM", status: "Gate", statusClass: "gate", name: "Reviewer QA", proc: "104 minutes", lat: "00:3s", anom: "-", anomClass: "" },
    { agent: "Agents activity, 1:09 PM", status: "Pending", statusClass: "amber-pending", name: "Classifier", proc: "183 minutes", lat: "00:3s", anom: "⚠️ Potential", anomClass: "" }
  ];

  tbody.innerHTML = rows.map(r => `
    <tr>
      <td>${r.agent}</td>
      <td><span class="pill-tag ${r.statusClass}">${r.status}</span></td>
      <td><b>${r.name}</b></td>
      <td>${r.proc}</td>
      <td>${r.lat}</td>
      <td>${r.anom === '-' ? '-' : `<span class="anomaly-alert ${r.anomClass}">${r.anom}</span>`}</td>
    </tr>
  `).join("");
}

// ── Dynamic SVG Connection Paths ────────────────────────────────────────────
function updateSvgCurves() {
  const canvas = document.getElementById("dag-canvas");
  const n1 = document.getElementById("node-classifier");
  const n2 = document.getElementById("node-severity");
  const n3 = document.getElementById("node-reviewer");
  const n4 = document.getElementById("node-human_gate");

  if (!canvas || !n1 || !n2 || !n3 || !n4) return;

  const cRect = canvas.getBoundingClientRect();
  const r1 = n1.getBoundingClientRect();
  const r2 = n2.getBoundingClientRect();
  const r3 = n3.getBoundingClientRect();
  const r4 = n4.getBoundingClientRect();

  // Curve 1: Node 1 right to Node 2 left
  const p1x = r1.right - cRect.left;
  const p1y = r1.top + r1.height / 2 - cRect.top;
  const p2x = r2.left - cRect.left - 6;
  const p2y = r2.top + r2.height / 2 - cRect.top;
  const dx1 = p2x - p1x;

  const path1 = document.getElementById("path-1-2");
  if (path1) {
    path1.setAttribute("d", `M ${p1x} ${p1y} C ${p1x + dx1 * 0.45} ${p1y - 12}, ${p2x - dx1 * 0.45} ${p2y + 12}, ${p2x} ${p2y}`);
  }

  // Curve 2: Node 2 right to Node 3 left
  const p2rx = r2.right - cRect.left;
  const p2ry = r2.top + r2.height / 2 - cRect.top;
  const p3x = r3.left - cRect.left - 6;
  const p3y = r3.top + r3.height / 2 - cRect.top;
  const dx2 = p3x - p2rx;

  const path2 = document.getElementById("path-2-3");
  if (path2) {
    path2.setAttribute("d", `M ${p2rx} ${p2ry} C ${p2rx + dx2 * 0.45} ${p2ry - 12}, ${p3x - dx2 * 0.45} ${p3y + 12}, ${p3x} ${p3y}`);
  }

  // Curve 3a (Green upper branch): Node 3 right to Node 4 left
  const p3rx = r3.right - cRect.left;
  const p3ry = r3.top + r3.height / 2 - cRect.top;
  const p4x = r4.left - cRect.left - 6;
  const p4y = r4.top + r4.height / 2 - cRect.top;
  const dx3 = p4x - p3rx;

  const path3a = document.getElementById("path-3-4a");
  if (path3a) {
    path3a.setAttribute("d", `M ${p3rx} ${p3ry - 8} C ${p3rx + dx3 * 0.45} ${p3ry - 24}, ${p4x - dx3 * 0.45} ${p4y - 8}, ${p4x} ${p4y - 8}`);
  }

  // Curve 3b (Amber lower branch): Node 3 right to Node 4 left
  const path3b = document.getElementById("path-3-4b");
  if (path3b) {
    path3b.setAttribute("d", `M ${p3rx} ${p3ry + 8} C ${p3rx + dx3 * 0.45} ${p3ry + 24}, ${p4x - dx3 * 0.45} ${p4y + 8}, ${p4x} ${p4y + 8}`);
  }
}

// ── Render Scenarios Modal ──────────────────────────────────────────────────
function renderScenariosModal() {
  const container = document.getElementById("scenarios-modal-list");
  if (!container) return;

  container.innerHTML = SCENARIOS.map(s => `
    <div class="scenario-card-item" onclick="selectScenario('${s.id}')">
      <div class="sc-info">
        <h4>${s.label} ($${s.amount.toLocaleString()})</h4>
        <p>${s.desc.substring(0, 80)}...</p>
      </div>
      <span class="sc-badge ${s.outcome === 'pass' ? 'auto' : 'human'}">
        ${s.outcome === 'pass' ? 'Auto-Approve' : 'Human Gate'}
      </span>
    </div>
  `).join("");
}

// ── Modal Handlers ──────────────────────────────────────────────────────────
function openScenariosModal() {
  document.getElementById("modal-scenarios").classList.add("open");
}

function closeScenariosModal() {
  document.getElementById("modal-scenarios").classList.remove("open");
}

function openNewClaimModal() {
  document.getElementById("modal-new-claim").classList.add("open");
}

function closeNewClaimModal() {
  document.getElementById("modal-new-claim").classList.remove("open");
}

function scrollToTelemetry() {
  const elem = document.getElementById("telemetry-section");
  if (elem) elem.scrollIntoView({ behavior: "smooth" });
}

// ── Select and Run Scenario ─────────────────────────────────────────────────
function selectScenario(scenarioId) {
  const sc = SCENARIOS.find(s => s.id === scenarioId);
  if (!sc) return;
  closeScenariosModal();
  loadScenario(sc, true);
}

function rerunCurrentScenario() {
  if (state.currentScenario) {
    loadScenario(state.currentScenario, true);
  }
}

async function loadScenario(sc, animate = true) {
  state.currentScenario = sc;
  document.getElementById("current-pipeline-label").textContent = `DAG: ${sc.label}`;

  // Hide human decision banner initially
  document.getElementById("human-decision-banner").style.display = "none";

  if (!animate) {
    state.outputs = sc.sim;
    updatePipelineUI(sc);
    updateTelemetryTable(sc);
    updateSvgCurves();
    return;
  }

  // Animated execution flow
  state.processing = true;
  setDagStatus("Running", "amber");

  // Step 1: Classifier
  highlightNode("node-classifier", true);
  setPathActive("path-1-2", true);
  await sleep(600);
  highlightNode("node-classifier", false, "Complete");

  // Step 2: Severity Scorer
  highlightNode("node-severity", true);
  setPathActive("path-2-3", true);
  await sleep(650);
  highlightNode("node-severity", false, "Complete");

  // Step 3: Reviewer QA
  highlightNode("node-reviewer", true);
  setPathActive("path-3-4a", true);
  setPathActive("path-3-4b", true);
  await sleep(700);
  highlightNode("node-reviewer", false, "Complete");

  // Step 4: Human Gate
  highlightNode("node-human_gate", true);
  await sleep(600);

  state.outputs = sc.sim;
  updatePipelineUI(sc);
  updateTelemetryTable(sc);
  updateSvgCurves();

  state.processing = false;
}

function setDagStatus(text, type) {
  const statusEl = document.getElementById("dag-global-status");
  const textEl = document.getElementById("dag-status-text");
  textEl.textContent = text;
  if (type === "approved") {
    statusEl.className = "dag-badge-status approved";
  } else {
    statusEl.className = "dag-badge-status";
  }
}

function highlightNode(nodeId, active, pillText = null) {
  const node = document.getElementById(nodeId);
  if (!node) return;
  if (active) {
    node.classList.add("active-step");
  } else {
    node.classList.remove("active-step");
  }
  if (pillText) {
    const pill = node.querySelector(".node-status-pill .txt");
    if (pill) pill.textContent = pillText;
  }
}

function setPathActive(pathId, active) {
  const path = document.getElementById(pathId);
  if (path) {
    if (active) path.classList.add("pulse");
    else path.classList.remove("pulse");
  }
}

function updatePipelineUI(sc) {
  const isEscalate = sc.outcome === "escalate";
  const gateNode = document.getElementById("node-human_gate");
  const gatePill = document.getElementById("status-pill-human_gate");

  if (isEscalate) {
    gateNode.className = "dag-node human-gate-node";
    gatePill.className = "node-status-pill";
    gatePill.style.background = "";
    gatePill.style.borderColor = "";
    gatePill.style.color = "";
    gatePill.innerHTML = `<span class="dot"></span><span class="txt">Pending</span>`;
    setDagStatus("Pending", "amber");

    // Show Human Decision Banner
    const banner = document.getElementById("human-decision-banner");
    const bannerTitle = document.getElementById("banner-title");
    const bannerDesc = document.getElementById("banner-desc");
    bannerTitle.textContent = `Human-in-the-Loop Review: ${sc.label} ($${sc.amount.toLocaleString()})`;
    bannerDesc.textContent = sc.sim.human_gate.reason;
    banner.style.display = "flex";
  } else {
    gateNode.className = "dag-node";
    gatePill.className = "node-status-pill";
    gatePill.style.background = "var(--green-50)";
    gatePill.style.borderColor = "var(--green-200)";
    gatePill.style.color = "var(--green-600)";
    gatePill.innerHTML = `<span class="dot"></span><span class="txt">Auto-Pass</span>`;
    setDagStatus("Approved", "approved");
  }

  // Update token count in metric card
  const totalToks = (sc.sim.classifier.tokens || 400) +
                    (sc.sim.severity.tokens || 500) +
                    (sc.sim.reviewer.tokens || 600);
  state.totalTokens = totalToks;
  animateCount("metric-tokens-val", totalToks, 600);
}

function updateTelemetryTable(sc) {
  const tbody = document.getElementById("telemetry-tbody");
  if (!tbody) return;

  const now = new Date();
  const timeStr = now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

  const rows = [
    {
      agent: `Agents activity, ${timeStr}`,
      status: "Pending",
      statusClass: "pending",
      name: "Classifier",
      tokens: `${sc.sim.classifier.tokens || 129} tokens`,
      latency: `${sc.sim.classifier.latency || '0.3'}s`,
      anomaly: sc.sim.classifier.anomaly || "⚠️ Potential",
      anomalyClass: ""
    },
    {
      agent: `Agents activity, ${timeStr}`,
      status: "Pending",
      statusClass: "pending",
      name: "Severity Scorer",
      tokens: `${sc.sim.severity.tokens || 125} tokens`,
      latency: `${sc.sim.severity.latency || '0.4'}s`,
      anomaly: sc.sim.severity.anomaly || "⚠️ Potential",
      anomalyClass: "warning"
    },
    {
      agent: `Agents activity, ${timeStr}`,
      status: "Gate",
      statusClass: "gate",
      name: "Reviewer QA",
      tokens: `${sc.sim.reviewer.tokens || 125} tokens`,
      latency: `${sc.sim.reviewer.latency || '0.5'}s`,
      anomaly: sc.sim.reviewer.anomaly || "-",
      anomalyClass: ""
    },
    {
      agent: `Agents activity, ${timeStr}`,
      status: sc.outcome === "escalate" ? "Pending" : "Approved",
      statusClass: sc.outcome === "escalate" ? "amber-pending" : "pending",
      name: "Human Gate",
      tokens: `0 tokens`,
      latency: `0.05s`,
      anomaly: sc.outcome === "escalate" ? "⚠️ Review Required" : "-",
      anomalyClass: ""
    }
  ];

  tbody.innerHTML = rows.map(r => `
    <tr>
      <td>${r.agent}</td>
      <td><span class="pill-tag ${r.statusClass}">${r.status}</span></td>
      <td><b>${r.name}</b></td>
      <td>${r.tokens}</td>
      <td>${r.latency}</td>
      <td>
        ${r.anomaly === '-' ? '-' : `<span class="anomaly-alert ${r.anomalyClass}">${r.anomaly}</span>`}
      </td>
    </tr>
  `).join("");
}

// ── Human-in-the-Loop Action ────────────────────────────────────────────────
function handleHumanDecision(action) {
  const banner = document.getElementById("human-decision-banner");
  banner.style.display = "none";

  const gateNode = document.getElementById("node-human_gate");
  const gatePill = document.getElementById("status-pill-human_gate");

  if (action === "approve") {
    gateNode.className = "dag-node";
    gatePill.style.background = "var(--green-50)";
    gatePill.style.borderColor = "var(--green-200)";
    gatePill.style.color = "var(--green-600)";
    gatePill.innerHTML = `<span class="dot"></span><span class="txt">Approved</span>`;
    setDagStatus("Approved", "approved");
  } else {
    gateNode.className = "dag-node";
    gatePill.style.background = "var(--red-50)";
    gatePill.style.borderColor = "var(--red-200)";
    gatePill.style.color = "var(--red-600)";
    gatePill.innerHTML = `<span class="dot" style="background:var(--red-500)"></span><span class="txt">Rejected</span>`;
    setDagStatus("Rejected", "amber");
  }
}

// ── Node Inspector Drawer ───────────────────────────────────────────────────
function openNodeInspector(agentKey) {
  state.activeInspectorAgent = agentKey;
  const drawer = document.getElementById("inspector-drawer");
  const titleEl = document.getElementById("drawer-agent-title");
  const reasoningEl = document.getElementById("drawer-reasoning");
  const tokensEl = document.getElementById("drawer-tokens");
  const latencyEl = document.getElementById("drawer-latency");
  const jsonEl = document.getElementById("drawer-json");

  const sc = state.currentScenario;
  const agentData = (state.outputs && state.outputs[agentKey]) || (sc.sim && sc.sim[agentKey]) || {};

  const titles = {
    classifier: "Classifier Agent (LLM)",
    severity: "Severity Scorer Agent (LLM)",
    reviewer: "Reviewer QA Agent (LLM)",
    human_gate: "Human Gate Agent (Deterministic)"
  };

  titleEl.textContent = titles[agentKey] || agentKey;
  reasoningEl.textContent = agentData.reasoning || agentData.reason || "Analyzing claim parameters and policy coverage limits.";
  tokensEl.textContent = agentData.tokens || "0";
  latencyEl.textContent = agentData.latency ? `${agentData.latency}s` : "0.3s";
  jsonEl.textContent = JSON.stringify(agentData, null, 2);

  drawer.classList.add("open");
}

function closeInspectorDrawer() {
  document.getElementById("inspector-drawer").classList.remove("open");
}

// ── Custom Claim Form ───────────────────────────────────────────────────────
function handleCustomClaimSubmit(e) {
  e.preventDefault();
  closeNewClaimModal();

  const claimant = document.getElementById("f-claimant").value;
  const amount = parseFloat(document.getElementById("f-amount").value);
  const limit = parseFloat(document.getElementById("f-limit").value);
  const policy = document.getElementById("f-policy").value;
  const desc = document.getElementById("f-desc").value;
  const support = document.getElementById("f-evidence").value;

  const isHighValue = amount > 25000 || desc.toLowerCase().includes("injury") || desc.toLowerCase().includes("fire");

  const customScenario = {
    id: "custom-" + Date.now(),
    label: `Claim: ${claimant} ($${amount.toLocaleString()})`,
    outcome: isHighValue ? "escalate" : "pass",
    claimant,
    policy,
    amount,
    limit,
    desc,
    support,
    sim: {
      classifier: { category: desc.toLowerCase().includes("fire") ? "property" : "auto", confidence: 0.96, reasoning: `Analyzed claim for ${claimant}. Description: ${desc}`, tokens: 420, latency: 0.40, anomaly: "⚠️ Potential" },
      severity:   { severity: isHighValue ? "high" : "low", estimated_payout: amount, confidence: 0.92, risk_factors: isHighValue ? ["High claimed amount"] : [], reasoning: `Claimed amount $${amount} against policy limit $${limit}.`, tokens: 490, latency: 0.45, anomaly: isHighValue ? "⚠️ Risk" : "-" },
      reviewer:   { overall_confidence: isHighValue ? 0.78 : 0.94, recommendation: isHighValue ? "needs_human_review" : "approve_auto", flags: isHighValue ? ["Exceeds auto-approval limit"] : [], requires_human_review: isHighValue, reasoning: "Automated QA validation completed.", tokens: 590, latency: 0.52, anomaly: isHighValue ? "⚠️ Flagged" : "-" },
      human_gate: { routed_to_human: isHighValue, reason: isHighValue ? "Severity High or amount exceeds limit" : "Auto-approved", tokens: 0, latency: 0.05, anomaly: isHighValue ? "⚠️ Pending" : "-" }
    }
  };

  loadScenario(customScenario, true);
}

// ── Backend Health Check ────────────────────────────────────────────────────
async function checkBackendHealth() {
  const badge = document.getElementById("live-backend-badge");
  try {
    const res = await fetch("/health", { method: "GET", signal: AbortSignal.timeout(1500) });
    if (res.ok) {
      state.isLiveBackend = true;
      badge.innerHTML = `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"></polygon></svg><span>Live API</span><span style="font-size:10px;">⌵</span>`;
      return;
    }
  } catch (err) {
    state.isLiveBackend = false;
  }
}

// ── Helpers ─────────────────────────────────────────────────────────────────
function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

function animateCount(elementId, target, duration) {
  const el = document.getElementById(elementId);
  if (!el) return;
  const start = parseInt(el.textContent.replace(/,/g, "")) || 0;
  const diff = target - start;
  const startTime = performance.now();

  function update(now) {
    const progress = Math.min((now - startTime) / duration, 1);
    const current = Math.round(start + diff * progress);
    el.textContent = current.toLocaleString();
    if (progress < 1) requestAnimationFrame(update);
  }
  requestAnimationFrame(update);
}
