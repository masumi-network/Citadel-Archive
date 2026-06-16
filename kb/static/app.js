import * as THREE from "./vendor/three.module.min.js";

const state = {
  snapshot: null,
  nodes: new Map(),
  edges: [],
  selectedId: null,
  selectedEventId: null,
  paused: false,
  eventSource: null,
  role: null,
  githubSync: null,
  obsidianSources: null,
  accessSnapshot: null,
  settingsSnapshot: null,
  auditFilter: "all",
  graphMode: "live",
  realGraph: null,
  realGraphLoading: false,
  conflicts: [],
  conflictFilter: "open",
};

const canvas = document.getElementById("graphCanvas");
const systemStatus = document.querySelector(".system-status");
const connectionLabel = document.getElementById("connectionLabel");
const runtimeStatus = document.getElementById("runtimeStatus");
const sessionRole = document.getElementById("sessionRole");
const roleSummary = document.getElementById("roleSummary");
const accessMode = document.getElementById("accessMode");
const graphMeta = document.getElementById("graphMeta");
const selectedNode = document.getElementById("selectedNode");
const indexList = document.getElementById("indexList");
const eventList = document.getElementById("eventList");
const eventCount = document.getElementById("eventCount");
const eventInspector = document.getElementById("eventInspector");
const timelineFreshness = document.getElementById("timelineFreshness");
const timelineStatValues = {
  indexed: document.querySelector('[data-timeline-stat="indexed"]'),
  pending: document.querySelector('[data-timeline-stat="pending"]'),
  failed: document.querySelector('[data-timeline-stat="failed"]'),
  lastIndexed: document.querySelector('[data-timeline-stat="lastIndexed"]'),
};
const upgradeStatus = document.getElementById("upgradeStatus");
const meshAlert = document.getElementById("meshAlert");
const meshAlertText = document.getElementById("meshAlertText");
const canvasEmpty = document.getElementById("canvasEmpty");
const githubSyncStatus = document.getElementById("githubSyncStatus");
const syncLastChecked = document.getElementById("syncLastChecked");
const syncTrackedRepos = document.getElementById("syncTrackedRepos");
const githubSourceLink = document.getElementById("githubSourceLink");
const syncRunSummary = document.getElementById("syncRunSummary");
const syncResult = document.getElementById("syncResult");
const syncPostToChat = document.getElementById("syncPostToChat");
const googleChatTestButton = document.getElementById("googleChatTestButton");
const obsidianVaultCount = document.getElementById("obsidianVaultCount");
const obsidianDocumentCount = document.getElementById("obsidianDocumentCount");
const obsidianSourceStatus = document.getElementById("obsidianSourceStatus");
const obsidianSourceList = document.getElementById("obsidianSourceList");
const feedbackStatus = document.getElementById("feedbackStatus");
const feedbackResult = document.getElementById("feedbackResult");
const accessTokenStatus = document.getElementById("accessTokenStatus");
const accessPrincipalList = document.getElementById("accessPrincipalList");
const accessTokenList = document.getElementById("accessTokenList");
const accessAuditList = document.getElementById("accessAuditList");
const newAccessToken = document.getElementById("newAccessToken");
const dashboardCronStatus = document.getElementById("dashboardCronStatus");
const dashboardCronMeta = document.getElementById("dashboardCronMeta");
const dashboardIngestStatus = document.getElementById("dashboardIngestStatus");
const dashboardIngestionList = document.getElementById("dashboardIngestionList");
const dashboardMcpClients = document.getElementById("dashboardMcpClients");
const dashboardMcpMeta = document.getElementById("dashboardMcpMeta");
const dashboardMcpStatus = document.getElementById("dashboardMcpStatus");
const dashboardMcpList = document.getElementById("dashboardMcpList");
const dashboardRecentLearning = document.getElementById("dashboardRecentLearning");
const dashboardIndexSummary = document.getElementById("dashboardIndexSummary");
const dashboardOpenIssue = document.getElementById("dashboardOpenIssue");
const knowledgeStatus = document.getElementById("knowledgeStatus");
const knowledgeSourceCount = document.getElementById("knowledgeSourceCount");
const knowledgeSnapshotCount = document.getElementById("knowledgeSnapshotCount");
const knowledgeConflictCount = document.getElementById("knowledgeConflictCount");
const knowledgeRecordCount = document.getElementById("knowledgeRecordCount");
const knowledgeDigestStatus = document.getElementById("knowledgeDigestStatus");
const knowledgeDailyUpdate = document.getElementById("knowledgeDailyUpdate");
const knowledgeSourceList = document.getElementById("knowledgeSourceList");
const knowledgeIndexList = document.getElementById("knowledgeIndexList");
const knowledgeRecentList = document.getElementById("knowledgeRecentList");
const agentsStatus = document.getElementById("agentsStatus");
const agentsTokenList = document.getElementById("agentsTokenList");
const auditStatus = document.getElementById("auditStatus");
const auditAccessList = document.getElementById("auditAccessList");
const auditRuntimeList = document.getElementById("auditRuntimeList");
const auditFilterButtons = Array.from(document.querySelectorAll("[data-audit-filter]"));
const auditMcpSummary = document.getElementById("auditMcpSummary");
const auditAccessTitle = document.getElementById("auditAccessTitle");
const auditAccessSubtitle = document.getElementById("auditAccessSubtitle");
const settingsStatus = document.getElementById("settingsStatus");
const settingsHealthGrid = document.getElementById("settingsHealthGrid");
const settingsMirrorList = document.getElementById("settingsMirrorList");
const conflictsStatus = document.getElementById("conflictsStatus");
const conflictsList = document.getElementById("conflictsList");
const conflictNavBadge = document.getElementById("conflictNavBadge");
const conflictFilterButtons = Array.from(document.querySelectorAll("[data-conflict-filter]"));
const graphModeButtons = Array.from(document.querySelectorAll("[data-graph-mode]"));
const realGraphEmpty = document.getElementById("realGraphEmpty");
const toastStack = document.getElementById("toastStack");
const searchResultStatus = document.getElementById("searchResultStatus");
const pageButtons = Array.from(document.querySelectorAll("[data-page-target]"));
const pages = Array.from(document.querySelectorAll("[data-page]"));
const roleOrder = { reader: 1, writer: 2, admin: 3 };
const reducedMotionQuery = window.matchMedia("(prefers-reduced-motion: reduce)");
const sensitiveDetailPattern = /(token|secret|password|authorization|body|content|text|query)$/i;

const graph = {
  scene: null,
  camera: null,
  renderer: null,
  root: null,
  nodeGroup: null,
  edgeGroup: null,
  labelGroup: null,
  raycaster: new THREE.Raycaster(),
  pointer: new THREE.Vector2(),
  nodeMeshes: new Map(),
  nodeObjects: new Map(),
  nodeLabelSprites: new Map(),
  width: 1,
  height: 1,
  yaw: -0.34,
  pitch: -0.12,
  distance: 720,
  targetYaw: -0.34,
  targetPitch: -0.12,
  targetDistance: 720,
  pointerDown: false,
  pointerMoved: false,
  lastPointerX: 0,
  lastPointerY: 0,
  pendingNode: null,
  reducedMotion: reducedMotionQuery.matches,
  viewInitialized: false,
  animationFrame: null,
};

const colors = {
  dataset: "#a882ff",
  document: "#cfcfcf",
  tag: "#8f8f8f",
  index: "#7dd4c0",
  query: "#d6cf94",
  feedback: "#e8615f",
  upgrade: "#6ecb8d",
  source: "#7dd4c0",
  repository: "#8f6ee8",
};

const realGraphPalette = ["#a882ff", "#c4b1ff", "#8f6ee8", "#7dd4c0", "#cfcfcf", "#9a9a9a"];

function typeColor(type) {
  return realGraphPalette[Math.floor(hashUnit(String(type || "node")) * realGraphPalette.length) % realGraphPalette.length];
}

function activeGraphData() {
  if (state.graphMode === "knowledge") {
    return state.realGraph || { nodes: new Map(), edges: [] };
  }
  return { nodes: state.nodes, edges: state.edges };
}

function api(path, options = {}) {
  return fetch(path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
  }).then(async (response) => {
    const text = await response.text();
    const data = text ? JSON.parse(text) : null;
    if (!response.ok) {
      const message = data?.detail || data?.message || "Request failed";
      throw new Error(message);
    }
    return data;
  });
}

function setBusy(button, busy, label) {
  button.disabled = busy;
  button.setAttribute("aria-busy", busy ? "true" : "false");
  if (label) {
    button.textContent = busy ? label.loading : label.idle;
  }
}

function setConnectionState(stateName, label) {
  connectionLabel.textContent = label;
  runtimeStatus.textContent = label;
  runtimeStatus.className = `status-chip status-${stateName}`;
  systemStatus.dataset.state = stateName;
}

function canUse(requiredRole = "reader") {
  if (!state.role) return false;
  return roleOrder[state.role] >= roleOrder[requiredRole];
}

function roleLabel(role) {
  if (role === "admin") return "Admin";
  if (role === "writer") return "Read write";
  return "Read only";
}

function applyAccessControls() {
  const label = state.role ? roleLabel(state.role) : "Locked";
  sessionRole.textContent = label;
  sessionRole.className = `status-chip ${state.role ? "status-enabled" : "status-error"}`;
  roleSummary.textContent = state.role
    ? `${label} vault access`
    : "No vault session";
  accessMode.textContent = label;
  accessMode.className = sessionRole.className;

  document.querySelectorAll("[data-min-role]").forEach((element) => {
    const allowed = canUse(element.dataset.minRole);
    if (element.classList.contains("nav-link")) {
      element.disabled = !allowed;
      return;
    }
    if (element.matches("form, fieldset")) {
      element.querySelectorAll("button, input, textarea, select").forEach((control) => {
        control.disabled = !allowed;
      });
      return;
    }
    if (element.matches("button, input, textarea, select")) {
      element.disabled = !allowed;
      return;
    }
    if (!element.matches("[data-page]")) {
      element.hidden = !allowed;
    }
  });

  renderDashboardMcpSession();
  renderConflicts();
}

function renderDashboardMcpSession() {
  if (!dashboardMcpStatus || !dashboardMcpList) return;
  const label = state.role ? roleLabel(state.role) : "Locked";
  dashboardMcpStatus.textContent = state.role ? "Authorized" : "Locked";
  dashboardMcpStatus.className = `status-chip ${state.role ? "status-enabled" : "status-error"}`;
  if (dashboardMcpClients && !canUse("admin")) {
    dashboardMcpClients.textContent = state.role ? label : "Locked";
    dashboardMcpMeta.textContent = state.role ? "current session" : "login required";
  }
  dashboardMcpList.innerHTML = `
    <div class="entity-item">
      <div>
        <strong>Current session</strong>
        <p>${escapeHtml(label)} vault access${state.role ? " through cookie or bearer token" : ""}</p>
      </div>
      <span class="status-chip ${state.role ? "status-enabled" : "status-error"}">${escapeHtml(state.role || "none")}</span>
    </div>
  `;
}

async function loadSession() {
  try {
    const session = await api("/api/session");
    state.role = session.role;
    applyAccessControls();
  } catch {
    window.location.assign("/login");
    throw new Error("Session required");
  }
}

function initialPage() {
  const hash = window.location.hash.replace("#", "");
  if (pages.some((page) => page.dataset.page === hash)) return hash;
  return state.role === "admin" ? "overview" : "search";
}

function setPage(name) {
  const targetPage = pages.find((page) => page.dataset.page === name);
  const requiredRole = targetPage?.dataset.minRole || "reader";
  const allowed = targetPage && canUse(requiredRole);
  const resolvedName = allowed ? name : "locked";

  pages.forEach((page) => {
    page.hidden = page.dataset.page !== resolvedName;
    page.classList.toggle("page-active", page.dataset.page === resolvedName);
  });
  pageButtons.forEach((button) => {
    button.classList.toggle("active", button.dataset.pageTarget === name && allowed);
  });
  if (allowed && window.location.hash !== `#${name}`) {
    window.history.replaceState(null, "", `#${name}`);
  }
  resizeCanvas();
  if (state.snapshot) mergeGraph(state.snapshot);
  if (resolvedName === "access") {
    loadAccess();
  }
  if (resolvedName === "agents" || resolvedName === "audit") {
    loadAccess();
  }
  if (resolvedName === "settings") {
    loadSettings();
  }
  if (resolvedName === "conflicts") {
    loadConflicts();
  }
}

function initializeNavigation() {
  pageButtons.forEach((button) => {
    button.addEventListener("click", () => setPage(button.dataset.pageTarget));
  });
  window.addEventListener("hashchange", () => setPage(initialPage()));
}

function resizeCanvas() {
  const rect = canvas.getBoundingClientRect();
  graph.width = Math.max(1, rect.width);
  graph.height = Math.max(1, rect.height);
  if (!graph.renderer || !graph.camera) return;
  graph.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  graph.renderer.setSize(graph.width, graph.height, false);
  graph.camera.aspect = graph.width / graph.height;
  graph.camera.updateProjectionMatrix();
  fitGraphDistance();
  renderGraphScene();
}

function mergeGraph(snapshot) {
  state.snapshot = snapshot;
  const layout = layoutNodes(snapshot.nodes);
  const nextIds = new Set();

  snapshot.nodes.forEach((node) => {
    nextIds.add(node.id);
    const existing = state.nodes.get(node.id);
    const position = layout.get(node.id) || { x: 0, y: 0, z: 0 };
    if (existing) {
      Object.assign(existing, node, position);
      return;
    }
    state.nodes.set(node.id, {
      ...node,
      ...position,
    });
  });

  for (const id of state.nodes.keys()) {
    if (!nextIds.has(id)) {
      state.nodes.delete(id);
    }
  }

  state.edges = snapshot.edges;
  if (state.graphMode === "live") {
    buildGraphScene();
    if (!graph.viewInitialized) {
      resetGraphView();
      graph.viewInitialized = true;
    }
  }
  renderSnapshot(snapshot);
  if (state.graphMode === "live") {
    selectNode(state.nodes.get(state.selectedId) || null);
  }
}

function renderSnapshot(snapshot) {
  meshAlert.hidden = true;
  canvasEmpty.hidden = state.graphMode !== "live" || snapshot.nodes.length > 4;
  updateGraphMeta();
  document.getElementById("statNodes").textContent = snapshot.stats.nodes;
  document.getElementById("statEdges").textContent = snapshot.stats.edges;
  document.getElementById("statDocuments").textContent = snapshot.stats.documents;
  document.getElementById("statSearches").textContent = snapshot.stats.searches;
  document.getElementById("statFeedback").textContent = snapshot.stats.feedback;
  document.getElementById("statUpgrades").textContent = snapshot.stats.upgrades;
  document.getElementById("statErrors").textContent = snapshot.stats.errors;
  if (knowledgeStatus) {
    const errorCount = Number(snapshot.stats.errors || 0);
    knowledgeStatus.textContent = errorCount ? "Review" : "Current";
    knowledgeStatus.className = `status-chip ${errorCount ? "status-error" : "status-enabled"}`;
  }
  if (knowledgeSnapshotCount) {
    knowledgeSnapshotCount.textContent = String(snapshot.stats.documents || 0);
  }
  eventCount.textContent = String(snapshot.events.length);
  renderDashboardIndexes(snapshot.indexes);
  renderDashboardRecentEvent(snapshot.events);
  renderDashboardOpenIssue(snapshot);
  renderTimelineStats(snapshot);
  renderTimeline(snapshot);

  indexList.innerHTML = "";
  if (!snapshot.indexes.length) {
    indexList.append(emptyState("No indexes", "The runtime has not reported index status yet."));
  } else {
    snapshot.indexes.forEach((index) => {
      const item = document.createElement("div");
      item.className = "index-item";
      item.innerHTML = `
        <div>
          <div class="index-name">${escapeHtml(index.name)}</div>
          <div class="index-meta">${escapeHtml(index.records)} records</div>
        </div>
        <span class="status-chip status-${escapeHtml(index.status)}">${escapeHtml(index.status)}</span>
      `;
      indexList.append(item);
    });
  }

}

function renderTimelineStats(snapshot) {
  const stats = snapshot.stats || {};
  const events = snapshot.events || [];
  if (eventCount) eventCount.textContent = String(events.length);
  if (timelineStatValues.indexed) {
    timelineStatValues.indexed.textContent = String(stats.indexed_chunks || 0);
  }
  if (timelineStatValues.pending) {
    timelineStatValues.pending.textContent = String(stats.pending_chunks || 0);
  }
  if (timelineStatValues.failed) {
    timelineStatValues.failed.textContent = String(stats.failed_chunks || 0);
  }
  if (timelineStatValues.lastIndexed) {
    timelineStatValues.lastIndexed.textContent = stats.last_indexed_at
      ? formatDate(stats.last_indexed_at)
      : "waiting";
  }
  if (timelineFreshness) {
    const failed = Number(stats.failed_chunks || 0) + Number(stats.errors || 0);
    timelineFreshness.textContent = failed ? "Review" : events.length ? "Live" : "Waiting";
    timelineFreshness.className = `status-chip ${failed ? "status-error" : events.length ? "status-enabled" : "status-standby"}`;
  }
}

function renderTimeline(snapshot) {
  if (!eventList) return;
  const events = snapshot.events || [];
  const selectedExists = events.some((event) => event.id === state.selectedEventId);
  if (!selectedExists) {
    state.selectedEventId = events[0]?.id || null;
  }

  eventList.innerHTML = "";
  if (!events.length) {
    eventList.append(emptyListItem("No events yet", "Run a sync or save a vault note."));
    renderEventInspector(null);
    return;
  }

  events.slice(0, 40).forEach((event) => {
    eventList.append(timelineEventItem(event));
  });
  renderEventInspector(events.find((event) => event.id === state.selectedEventId) || events[0]);
}

function timelineEventItem(event) {
  const item = document.createElement("li");
  item.className = "timeline-event";
  const timeline = timelineEnvelope(event);
  const selected = event.id === state.selectedEventId;
  const statusClass = timelineStatusClass(event, timeline);
  const metrics = formatMetrics(timeline.metrics);
  const meta = [timeline.dataset, timeline.source, metrics].filter(Boolean).join(" - ");
  const button = document.createElement("button");
  button.type = "button";
  button.className = `event-item timeline-event-button${selected ? " is-selected" : ""}`;
  button.setAttribute("aria-pressed", selected ? "true" : "false");
  button.innerHTML = `
    <span class="timeline-dot ${statusClass}" aria-hidden="true"></span>
    <span class="timeline-event-main">
      <span class="event-row">
        <span class="event-type">${escapeHtml(humanizeToken(timeline.kind))}</span>
        <time class="event-time">${escapeHtml(formatDate(event.created_at))}</time>
      </span>
      <span class="event-message">${escapeHtml(event.message || humanizeToken(event.type))}</span>
      <span class="event-details">${escapeHtml(meta || formatDetails(event.details || {}))}</span>
    </span>
    <span class="status-chip ${statusClass}">${escapeHtml(timeline.status || event.type)}</span>
  `;
  button.addEventListener("click", () => selectTimelineEvent(event));
  item.append(button);
  return item;
}

function selectTimelineEvent(event) {
  state.selectedEventId = event.id;
  focusGraphForEvent(event);
  if (state.snapshot) {
    renderTimeline(state.snapshot);
  }
}

function renderEventInspector(event) {
  if (!eventInspector) return;
  if (!event) {
    eventInspector.innerHTML = `
      <div class="empty-state compact-empty">
        <strong>No event selected</strong>
        <p>New knowledge activity will appear here.</p>
      </div>
    `;
    return;
  }

  const timeline = timelineEnvelope(event);
  const details = event.details || {};
  const relatedNode = relatedNodeForEvent(event);
  const detailText = formatDetails(details) || "none";
  const metricText = formatMetrics(timeline.metrics) || "none";
  eventInspector.innerHTML = `
    <div class="inspector-summary">
      <span class="status-chip ${timelineStatusClass(event, timeline)}">${escapeHtml(timeline.status || event.type)}</span>
      <strong>${escapeHtml(event.message || humanizeToken(event.type))}</strong>
      <p>${escapeHtml(humanizeToken(timeline.kind))} - ${escapeHtml(formatDate(event.created_at))}</p>
    </div>
    <dl class="inspector-grid">
      <div><dt>Dataset</dt><dd>${escapeHtml(timeline.dataset || "unknown")}</dd></div>
      <div><dt>Source</dt><dd>${escapeHtml(timeline.source || "runtime")}</dd></div>
      <div><dt>Event id</dt><dd>${escapeHtml(String(event.id))}</dd></div>
      <div><dt>Metrics</dt><dd>${escapeHtml(metricText)}</dd></div>
    </dl>
    <div class="inspector-section">
      <h4>Graph focus</h4>
      <p>${escapeHtml(relatedNode ? `${relatedNode.label} - ${relatedNode.type}` : "No graph node matched")}</p>
    </div>
    <div class="inspector-section">
      <h4>Details</h4>
      <p>${escapeHtml(detailText)}</p>
    </div>
  `;
}

function timelineEnvelope(event) {
  if (event.timeline) return event.timeline;
  const details = event.details || {};
  return {
    kind: event.type || "event",
    status: event.type === "error" ? "failed" : details.status || "recorded",
    dataset: details.dataset || details.org || details.vault_id || null,
    source: details.source || details.operation || "runtime",
    metrics: {},
  };
}

function timelineStatusClass(event, timeline = timelineEnvelope(event)) {
  const status = String(timeline.status || event.type || "").toLowerCase();
  if (event.type === "error" || status === "failed") return "status-error";
  if (["pending", "detected", "rejected"].includes(status)) return "status-standby";
  return "status-enabled";
}

function focusGraphForEvent(event) {
  const node = relatedNodeForEvent(event);
  if (node) {
    selectNode(node);
  }
  return node;
}

function relatedNodeForEvent(event) {
  const details = event.details || {};
  const timeline = timelineEnvelope(event);
  const dataset = timeline.dataset || details.dataset;
  if (dataset) {
    const datasetNode = findGraphNode((node) => {
      return node.type === "dataset" && (node.metadata?.dataset === dataset || node.label === dataset);
    });
    if (datasetNode) return datasetNode;
  }
  if (details.vault_id) {
    const vaultNode = findGraphNode((node) => node.metadata?.vault_id === details.vault_id);
    if (vaultNode) return vaultNode;
  }
  if (details.org) {
    const org = String(details.org).toLowerCase();
    const sourceNode = findGraphNode((node) => {
      const label = String(node.label || "").toLowerCase();
      const url = String(node.metadata?.url || "").toLowerCase();
      return node.type === "source" && (label.includes(org) || url.includes(org));
    });
    if (sourceNode) return sourceNode;
  }
  return null;
}

function findGraphNode(predicate) {
  for (const node of state.nodes.values()) {
    if (predicate(node)) return node;
  }
  return null;
}

function formatMetrics(metrics = {}) {
  return Object.entries(metrics)
    .filter(([, value]) => value !== null && value !== undefined)
    .map(([key, value]) => `${humanizeToken(key)}: ${value}`)
    .join(" | ");
}

function humanizeToken(value) {
  return String(value || "")
    .replace(/[_-]+/g, " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function renderDashboardIndexes(indexes = []) {
  if (!dashboardIndexSummary) return;
  dashboardIndexSummary.innerHTML = "";
  renderKnowledgeIndexes(indexes);
  if (!indexes.length) {
    dashboardIndexSummary.append(emptyState("No indexes", "Index status has not reported yet."));
    return;
  }
  indexes.slice(0, 4).forEach((index) => {
    const item = document.createElement("div");
    item.className = "entity-item";
    item.innerHTML = `
      <div>
        <strong>${escapeHtml(index.name)}</strong>
        <p>${escapeHtml(index.records)} records</p>
      </div>
      <span class="status-chip status-${escapeHtml(index.status)}">${escapeHtml(index.status)}</span>
    `;
    dashboardIndexSummary.append(item);
  });
}

function renderDashboardRecentEvent(events = []) {
  if (!dashboardRecentLearning) return;
  renderKnowledgeRecentEvents(events);
  renderAuditRuntimeEvents(events);
  const latest = events[0];
  if (!latest) {
    dashboardRecentLearning.className = "empty-state compact-empty";
    dashboardRecentLearning.innerHTML = `
      <strong>No events yet</strong>
      <p>Run sync, save a note, or search to teach the vault.</p>
    `;
    return;
  }
  dashboardRecentLearning.className = "dashboard-event-card";
  dashboardRecentLearning.innerHTML = `
    <strong>${escapeHtml(latest.message)}</strong>
    <p>${escapeHtml(latest.type)} - ${escapeHtml(formatDate(latest.created_at))}</p>
    <p>${escapeHtml(formatDetails(latest.details || {}))}</p>
  `;
}

function renderKnowledgeIndexes(indexes = []) {
  if (!knowledgeIndexList) return;
  knowledgeIndexList.innerHTML = "";
  const recordCount = indexes.reduce((total, index) => total + Number(index.records || 0), 0);
  if (knowledgeRecordCount) knowledgeRecordCount.textContent = String(recordCount);
  if (!indexes.length) {
    knowledgeIndexList.append(emptyState("No index status", "The retrieval indexes have not reported yet."));
    return;
  }
  indexes.forEach((index) => {
    const item = document.createElement("div");
    item.className = "entity-item";
    item.innerHTML = `
      <div>
        <strong>${escapeHtml(index.name)}</strong>
        <p>${escapeHtml(index.description || "Knowledge retrieval index")}</p>
      </div>
      <span class="status-chip status-${escapeHtml(index.status)}">${escapeHtml(index.records)} records</span>
    `;
    knowledgeIndexList.append(item);
  });
}

function renderKnowledgeRecentEvents(events = []) {
  if (!knowledgeRecentList) return;
  knowledgeRecentList.innerHTML = "";
  if (!events.length) {
    knowledgeRecentList.append(emptyState("No vault events", "Search, ingest, sync, and feedback events will appear here."));
    return;
  }
  events.slice(0, 5).forEach((event) => {
    const item = document.createElement("div");
    item.className = "entity-item";
    item.innerHTML = `
      <div>
        <strong>${escapeHtml(event.message || event.type)}</strong>
        <p>${escapeHtml(event.type)} - ${escapeHtml(formatDate(event.created_at))}</p>
      </div>
      <span class="status-chip ${event.type === "error" ? "status-error" : "status-enabled"}">${escapeHtml(event.type)}</span>
    `;
    knowledgeRecentList.append(item);
  });
}

function renderAuditRuntimeEvents(events = []) {
  if (!auditRuntimeList) return;
  auditRuntimeList.innerHTML = "";
  if (!events.length) {
    auditRuntimeList.append(emptyListItem("No runtime events", "Vault operations will appear after activity."));
    return;
  }
  events.slice(0, 20).forEach((event) => {
    auditRuntimeList.append(
      eventListItem({
        type: event.type,
        created_at: event.created_at,
        message: event.message,
        details: event.details,
        success: event.type !== "error",
      }),
    );
  });
}

function renderDashboardOpenIssue(snapshot) {
  if (!dashboardOpenIssue) return;
  const errorCount = Number(snapshot.stats.errors || 0);
  const hasEvents = Boolean(snapshot.events.length);
  if (errorCount > 0) {
    dashboardOpenIssue.className = "dashboard-event-card issue-card";
    dashboardOpenIssue.innerHTML = `
      <strong>${escapeHtml(errorCount)} runtime error${errorCount === 1 ? "" : "s"}</strong>
      <p>Open the events page to inspect failed operations.</p>
    `;
    return;
  }
  if (!hasEvents) {
    dashboardOpenIssue.className = "empty-state compact-empty";
    dashboardOpenIssue.innerHTML = `
      <strong>No activity yet</strong>
      <p>Run source sync to start building the shared vault graph.</p>
    `;
    return;
  }
  dashboardOpenIssue.className = "dashboard-event-card";
  dashboardOpenIssue.innerHTML = `
    <strong>No blocking issues</strong>
    <p>Vault updates are flowing. Keep an eye on weak source links and token scope holds.</p>
  `;
}

function emptyState(title, body) {
  const item = document.createElement("div");
  item.className = "empty-state";
  item.innerHTML = `<strong>${escapeHtml(title)}</strong><p>${escapeHtml(body)}</p>`;
  return item;
}

function setSearchStatus(label, statusClass = "") {
  if (!searchResultStatus) return;
  searchResultStatus.textContent = label;
  searchResultStatus.className = `status-chip ${statusClass}`.trim();
}

function searchLoadingState() {
  const fragment = document.createDocumentFragment();
  for (let index = 0; index < 3; index += 1) {
    const item = document.createElement("div");
    item.className = "result-item result-skeleton";
    item.innerHTML = `
      <div class="skeleton-line short"></div>
      <div class="skeleton-line"></div>
      <div class="skeleton-line medium"></div>
      <div class="skeleton-grid">
        <span></span><span></span><span></span>
      </div>
    `;
    fragment.append(item);
  }
  return fragment;
}

function searchErrorState(message) {
  const item = document.createElement("div");
  item.className = "empty-state issue-card search-error-state";
  item.innerHTML = `
    <strong>Search failed</strong>
    <p>${escapeHtml(message || "The vault could not complete this search.")}</p>
    <button class="secondary-button compact-button" type="button" data-search-retry>Retry</button>
  `;
  return item;
}

function searchEmptyState(response = {}) {
  const item = emptyState(
    "No source-linked results",
    response.note || "Try a broader query, choose a dataset, or add source material."
  );
  if (Array.isArray(response.known_datasets) && response.known_datasets.length) {
    const datasets = document.createElement("p");
    datasets.className = "known-datasets";
    datasets.textContent = `Known datasets: ${response.known_datasets.join(", ")}`;
    item.append(datasets);
  }
  const actions = document.createElement("div");
  actions.className = "empty-actions";
  actions.innerHTML = `
    <button class="secondary-button compact-button" data-page-target="sources" type="button">Review sources</button>
    <button class="secondary-button compact-button" data-page-target="ingest" data-min-role="writer" type="button">Add note</button>
  `;
  actions.querySelectorAll("[data-page-target]").forEach((button) => {
    if (button.dataset.minRole && !canUse(button.dataset.minRole)) {
      button.disabled = true;
    }
    button.addEventListener("click", () => setPage(button.dataset.pageTarget));
  });
  item.append(actions);
  return item;
}

function emptyListItem(title, body) {
  const item = document.createElement("li");
  item.className = "event-item empty-event";
  item.innerHTML = `<strong>${escapeHtml(title)}</strong><p>${escapeHtml(body)}</p>`;
  return item;
}

function eventListItem(event) {
  const item = document.createElement("li");
  const isMcp = isMcpAuditEvent(event);
  item.className = `event-item${isMcp ? " mcp-event" : ""}`;
  const detail = event.detail || event.details || {};
  const eventLabel = event.action || event.type || "event";
  const status = event.success === false ? "failed" : event.success === true ? "ok" : detail.status || "";
  item.innerHTML = `
    <div class="event-row">
      <span class="event-type">${escapeHtml(eventLabel)}</span>
      <time class="event-time">${escapeHtml(formatDate(event.created_at))}</time>
    </div>
    ${status ? `<span class="status-chip ${event.success === false ? "status-error" : "status-enabled"}">${escapeHtml(status)}</span>` : ""}
    <div class="event-message">${escapeHtml(event.actor_name || event.message || "System")}</div>
    <div class="event-details">${escapeHtml(formatDetails(detail))}</div>
  `;
  if (event.success === false) {
    item.classList.add("issue-card");
  }
  return item;
}

function formatDetails(details = {}) {
  return Object.entries(details)
    .filter(([, value]) => value !== null && value !== undefined && value !== "")
    .map(([key, value]) => {
      const rendered = sensitiveDetailPattern.test(key)
        ? "[redacted]"
        : Array.isArray(value)
          ? value.join(", ")
          : value;
      return `${key}: ${rendered}`;
    })
    .join(" | ");
}

function isMcpAuditEvent(event) {
  return Boolean(event?.action?.startsWith("mcp.") || event?.detail?.surface === "mcp");
}

function filteredAuditEvents(events = []) {
  if (state.auditFilter === "mcp") return events.filter(isMcpAuditEvent);
  if (state.auditFilter === "access") return events.filter((event) => !isMcpAuditEvent(event));
  if (state.auditFilter === "failures") return events.filter((event) => event.success === false);
  return events;
}

function renderAuditFilterState(events = []) {
  const filtered = filteredAuditEvents(events);
  const mcpEvents = events.filter(isMcpAuditEvent);
  const mcpFailures = mcpEvents.filter((event) => event.success === false);
  const mcpActors = new Set(mcpEvents.map((event) => event.actor_id || event.actor_name).filter(Boolean));

  auditFilterButtons.forEach((button) => {
    const active = button.dataset.auditFilter === state.auditFilter;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", active ? "true" : "false");
  });

  if (auditMcpSummary) {
    auditMcpSummary.innerHTML = `
      <div><dt>MCP events</dt><dd>${escapeHtml(mcpEvents.length)}</dd></div>
      <div><dt>Failures</dt><dd>${escapeHtml(mcpFailures.length)}</dd></div>
      <div><dt>Actors</dt><dd>${escapeHtml(mcpActors.size)}</dd></div>
    `;
  }

  if (auditAccessTitle && auditAccessSubtitle) {
    const labels = {
      all: ["Agent And Access Actions", `${filtered.length} recent audit events`],
      mcp: ["MCP Tool Calls", `${filtered.length} agent tool events`],
      access: ["Access And Admin Actions", `${filtered.length} non-MCP audit events`],
      failures: ["Failed Actions", `${filtered.length} failed audit events`],
    };
    const [title, subtitle] = labels[state.auditFilter] || labels.all;
    auditAccessTitle.textContent = title;
    auditAccessSubtitle.textContent = subtitle;
  }

  return filtered;
}

function findFeedbackId(value) {
  if (!value || typeof value !== "object") return null;
  const directKeys = [
    "qa_id",
    "qaId",
    "question_answer_id",
    "questionAnswerId",
    "answer_id",
    "answerId",
  ];
  for (const key of directKeys) {
    const candidate = value[key];
    if (typeof candidate === "string" && candidate.trim()) {
      return candidate.trim();
    }
  }
  for (const key of ["metadata", "payload", "result"]) {
    const candidate = findFeedbackId(value[key]);
    if (candidate) return candidate;
  }
  return null;
}

function compactText(value, maxLength = 520) {
  if (value === null || value === undefined || value === "") return "";
  const text = typeof value === "string" ? value : JSON.stringify(value, null, 2);
  const normalized = text.replace(/\s+/g, " ").trim();
  if (normalized.length <= maxLength) return normalized;
  return `${normalized.slice(0, maxLength - 1)}…`;
}

function resultEnvelope(result) {
  return result && typeof result === "object" && result._citadel
    ? result._citadel
    : {};
}

function resultProvenance(result) {
  const provenance = resultEnvelope(result).provenance;
  return provenance && typeof provenance === "object" ? provenance : {};
}

function resultTitle(result, index) {
  const provenance = resultProvenance(result);
  return (
    provenance.title ||
    result?.title ||
    result?.name ||
    result?.id ||
    `Result ${index + 1}`
  );
}

function resultSummary(result) {
  const body =
    result?.content ??
    result?.body ??
    result?.text ??
    result?.summary ??
    result?.answer ??
    result?.result;
  return compactText(body || result);
}

function resultMetaRows(result) {
  const envelope = resultEnvelope(result);
  const provenance = resultProvenance(result);
  return [
    ["Dataset", envelope.dataset || result?.dataset],
    ["Source", provenance.source || result?.source],
    ["Path", provenance.path],
    ["Session", provenance.session_id],
    ["Hash", envelope.content_sha256 ? envelope.content_sha256.slice(0, 12) : null],
  ].filter(([, value]) => value !== null && value !== undefined && value !== "");
}

function safeDocumentEndpoint(result) {
  const envelope = resultEnvelope(result);
  const endpoint = envelope.document_endpoint;
  if (
    envelope.retrieval?.document_drilldown_available === true &&
    typeof endpoint === "string" &&
    endpoint.startsWith("/api/documents/")
  ) {
    return endpoint;
  }
  return null;
}

function safeExternalUrl(value) {
  if (typeof value !== "string" || !value.trim()) return null;
  try {
    const url = new URL(value);
    return ["http:", "https:"].includes(url.protocol) ? url.href : null;
  } catch {
    return null;
  }
}

function resultBodyText(result) {
  const body =
    result?.body ??
    result?.content ??
    result?.text ??
    result?.summary ??
    result?.answer ??
    result?.result;
  return compactText(body || result, 1200);
}

function documentPreviewMarkup(document) {
  const metadata = document?.metadata && typeof document.metadata === "object" ? document.metadata : {};
  const title = document?.title || document?.path || document?.id || "Source document";
  const body = compactText(document?.body || document?.content || "No document body returned.", 1800);
  const rows = [
    ["Source", document?.source || document?.source_type],
    ["Dataset", document?.dataset],
    ["Path", document?.path || document?.normalized_path],
    ["Revision", document?.current_rev || document?.rev],
    ["Checked", metadata.checked_at || metadata.digest_at || document?.updated_at],
  ].filter(([, value]) => value !== null && value !== undefined && value !== "");
  return `
    <div class="document-preview-card">
      <div class="document-preview-heading">
        <strong>${escapeHtml(title)}</strong>
        <span class="status-chip status-enabled">Source preview</span>
      </div>
      ${
        rows.length
          ? `<dl class="result-provenance document-preview-meta">${rows
              .map(
                ([label, value]) => `
                  <div>
                    <dt>${escapeHtml(label)}</dt>
                    <dd>${escapeHtml(value)}</dd>
                  </div>
                `
              )
              .join("")}</dl>`
          : ""
      }
      <pre class="result-body document-preview-body">${escapeHtml(body)}</pre>
    </div>
  `;
}

async function loadDocumentPreview(button, endpoint, panel) {
  const idleLabel = button.textContent;
  setBusy(button, true, { idle: idleLabel, loading: "Loading source" });
  panel.hidden = false;
  panel.innerHTML = `<div class="empty-state compact-empty"><strong>Loading source</strong><p>Fetching the supporting document.</p></div>`;
  try {
    const response = await api(endpoint);
    panel.innerHTML = documentPreviewMarkup(response.document || response);
  } catch (error) {
    panel.innerHTML = `
      <div class="empty-state issue-card compact-empty">
        <strong>Could not load source</strong>
        <p>${escapeHtml(error.message || "Try again in a moment.")}</p>
      </div>
    `;
  } finally {
    setBusy(button, false, { idle: idleLabel, loading: "Loading source" });
  }
}

function fillFeedbackForm(qaId, score = "1") {
  const form = document.getElementById("feedbackForm");
  const qaInput = form.querySelector("[name='qaId']");
  qaInput.value = qaId;
  qaInput.setAttribute("aria-invalid", "false");
  const scoreInput = form.querySelector(`[name='score'][value='${score}']`);
  if (scoreInput) scoreInput.checked = true;
  form.querySelector("[name='text']").focus();
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function formatDate(value) {
  if (!value) return "Never";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function formatBytes(value) {
  const bytes = Number(value || 0);
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function initializeGraph() {
  graph.scene = new THREE.Scene();
  graph.scene.background = new THREE.Color(0x1e1e1e);
  graph.scene.fog = new THREE.Fog(0x1e1e1e, 780, 1900);

  graph.camera = new THREE.PerspectiveCamera(38, 1, 1, 2800);
  graph.camera.position.set(0, 0, graph.distance);

  graph.renderer = new THREE.WebGLRenderer({
    canvas,
    antialias: true,
    alpha: false,
    preserveDrawingBuffer: true,
    powerPreference: "high-performance",
  });
  graph.renderer.outputColorSpace = THREE.SRGBColorSpace;
  graph.renderer.toneMapping = THREE.ACESFilmicToneMapping;
  graph.renderer.toneMappingExposure = 1.05;
  graph.renderer.setClearColor(0x1e1e1e, 1);

  graph.root = new THREE.Group();
  graph.root.rotation.order = "YXZ";
  graph.scene.add(graph.root);

  graph.scene.add(new THREE.AmbientLight(0xffffff, 0.34));
  const hemisphereLight = new THREE.HemisphereLight(0xd8ccff, 0x1e1e1e, 0.92);
  graph.scene.add(hemisphereLight);
  const keyLight = new THREE.DirectionalLight(0xf4f1ff, 1.8);
  keyLight.position.set(320, 460, 540);
  graph.scene.add(keyLight);
  const fillLight = new THREE.PointLight(0xa882ff, 0.95, 1100);
  fillLight.position.set(-420, -120, 420);
  graph.scene.add(fillLight);
  const rimLight = new THREE.DirectionalLight(0x53dfdd, 0.7);
  rimLight.position.set(-520, 260, -320);
  graph.scene.add(rimLight);

  graph.root.add(createSceneBase());

  graph.edgeGroup = new THREE.Group();
  graph.nodeGroup = new THREE.Group();
  graph.labelGroup = new THREE.Group();
  graph.root.add(graph.edgeGroup, graph.nodeGroup, graph.labelGroup);
}

function createSceneBase() {
  const base = new THREE.Group();
  base.position.y = -194;
  base.position.z = -16;

  const grid = new THREE.GridHelper(980, 18, 0xa882ff, 0x3f3f3f);
  for (const material of Array.isArray(grid.material) ? grid.material : [grid.material]) {
    material.transparent = true;
    material.opacity = 0.105;
    material.depthWrite = false;
  }
  base.add(grid);

  const rings = [
    { radius: 185, opacity: 0.2, color: 0xa882ff },
    { radius: 300, opacity: 0.12, color: 0x4a4a4a },
    { radius: 425, opacity: 0.08, color: 0x4a4a4a },
  ];
  rings.forEach((ring) => {
    const geometry = new THREE.TorusGeometry(ring.radius, 0.9, 6, 128);
    const material = new THREE.MeshBasicMaterial({
      color: ring.color,
      transparent: true,
      opacity: ring.opacity,
      depthWrite: false,
    });
    const mesh = new THREE.Mesh(geometry, material);
    mesh.rotation.x = Math.PI / 2;
    base.add(mesh);
  });

  return base;
}

function layoutNodes(nodes) {
  const groups = new Map();
  for (const node of nodes) {
    const type = node.type || "other";
    groups.set(type, [...(groups.get(type) || []), node]);
  }

  const positions = new Map();
  const density = clamp(Math.sqrt(Math.max(nodes.length, 10) / 18), 0.95, 1.48);
  const layouts = {
    dataset: { radius: 0, y: 0, yScale: 0, z: 0, zScale: 0, start: 0 },
    index: { radius: 248, y: -4, yScale: 0.44, z: 0, zScale: 60, start: -Math.PI / 4 },
    source: { radius: 360, y: -118, yScale: 0.42, z: 10, zScale: 92, start: -0.16 },
    repository: { radius: 438, y: -148, yScale: 0.4, z: 18, zScale: 132, start: 0.1 },
    document: { radius: 386, y: 118, yScale: 0.46, z: -10, zScale: 118, start: Math.PI * 0.62 },
    tag: { radius: 486, y: 160, yScale: 0.38, z: -22, zScale: 146, start: Math.PI * 0.86 },
    query: { radius: 430, y: 16, yScale: 0.44, z: 0, zScale: 126, start: -0.05 },
    feedback: { radius: 436, y: 132, yScale: 0.42, z: 14, zScale: 112, start: Math.PI * 0.16 },
    upgrade: { radius: 334, y: 76, yScale: 0.46, z: 16, zScale: 82, start: -Math.PI * 0.45 },
    other: { radius: 460, y: 0, yScale: 0.42, z: 0, zScale: 132, start: Math.PI * 0.35 },
  };

  for (const [type, group] of groups.entries()) {
    const layout = layouts[type] || layouts.other;
    const sorted = [...group].sort(compareNodes);

    if (type === "dataset") {
      const offset = (sorted.length - 1) / 2;
      sorted.forEach((node, index) => {
        positions.set(node.id, {
          x: (index - offset) * 96,
          y: layout.y,
          z: layout.z,
        });
      });
      continue;
    }

    const scale = graphLayoutScale();
    const radius = layout.radius * density * scale;
    const step = (Math.PI * 2) / Math.max(sorted.length, 1);
    sorted.forEach((node, index) => {
      const seed = hashUnit(node.id);
      const angle = layout.start + step * index + (seed - 0.5) * 0.22;
      const lane = ((index % 3) - 1) * 14 * scale;
      positions.set(node.id, {
        x: Math.cos(angle) * (radius + lane),
        y: layout.y + Math.sin(angle) * radius * layout.yScale,
        z: layout.z + Math.sin(angle * 1.7 + seed * Math.PI) * layout.zScale * scale,
      });
    });
  }

  return positions;
}

function buildGraphScene() {
  if (!graph.nodeGroup || !graph.edgeGroup || !graph.labelGroup) return;

  clearGroup(graph.edgeGroup);
  clearGroup(graph.nodeGroup);
  clearGroup(graph.labelGroup);
  graph.nodeMeshes.clear();
  graph.nodeObjects.clear();
  graph.nodeLabelSprites.clear();

  const graphData = activeGraphData();
  const edgePositions = [];
  for (const edge of graphData.edges) {
    const source = graphData.nodes.get(edge.source);
    const target = graphData.nodes.get(edge.target);
    if (!source || !target) continue;
    edgePositions.push(source.x, source.y, source.z, target.x, target.y, target.z);
  }

  if (edgePositions.length) {
    const edgeGeometry = new THREE.BufferGeometry();
    edgeGeometry.setAttribute("position", new THREE.Float32BufferAttribute(edgePositions, 3));
    const edgeMaterial = new THREE.LineBasicMaterial({
      color: state.graphMode === "knowledge" ? 0x7a6aa8 : 0x6b6b78,
      transparent: true,
      opacity: 0.34,
      depthWrite: false,
    });
    graph.edgeGroup.add(new THREE.LineSegments(edgeGeometry, edgeMaterial));
  }

  const nodes = Array.from(graphData.nodes.values()).sort(compareNodes);
  nodes.forEach((node) => {
    const radius = nodeRadius(node);
    const color = new THREE.Color(
      state.graphMode === "knowledge"
        ? typeColor(node.type)
        : colors[node.type] || "#b5bdc9",
    );
    const { object, mesh } = createNodeObject(node, radius, color);
    object.position.set(node.x, node.y, node.z);
    graph.nodeObjects.set(node.id, object);
    graph.nodeMeshes.set(node.id, mesh);
    graph.nodeGroup.add(object);

    if (shouldShowNodeLabel(node)) {
      const label = createLabelSprite(node, radius);
      label.position.copy(labelPosition(node, radius));
      graph.nodeLabelSprites.set(node.id, label);
      graph.labelGroup.add(label);
    }
  });

  updateNodeSelection();
  renderGraphScene();
}

function clearGroup(group) {
  group.traverse((object) => {
    if (object === group) return;
    if (object.geometry) object.geometry.dispose();
    const materials = Array.isArray(object.material) ? object.material : [object.material];
    for (const material of materials.filter(Boolean)) {
      if (material.map) material.map.dispose();
      material.dispose();
    }
  });
  group.clear();
}

function createNodeObject(node, radius, color) {
  const object = new THREE.Group();
  const geometry = nodeGeometry(node, radius);
  const material = new THREE.MeshStandardMaterial({
    color,
    emissive: color,
    emissiveIntensity: node.type === "dataset" ? 0.18 : 0.1,
    roughness: node.type === "dataset" ? 0.38 : 0.5,
    metalness: node.type === "index" ? 0.24 : 0.12,
  });
  const mesh = new THREE.Mesh(geometry, material);
  mesh.userData.nodeId = node.id;
  object.add(mesh);

  const outline = new THREE.LineSegments(
    new THREE.EdgesGeometry(geometry, 24),
    new THREE.LineBasicMaterial({
      color: 0xf2f4f7,
      transparent: true,
      opacity: node.type === "dataset" ? 0.24 : 0.16,
      depthWrite: false,
    }),
  );
  outline.scale.setScalar(1.045);
  object.add(outline);

  addNodeHalo(object, node, radius, color);
  return { object, mesh };
}

function addNodeHalo(object, node, radius, color) {
  const ringMaterial = new THREE.MeshBasicMaterial({
    color,
    transparent: true,
    opacity: node.type === "dataset" ? 0.34 : 0.18,
    depthWrite: false,
  });
  const ring = new THREE.Mesh(
    new THREE.TorusGeometry(radius * (node.type === "dataset" ? 1.84 : 1.54), 0.9, 6, 72),
    ringMaterial,
  );
  ring.rotation.x = Math.PI / 2;
  ring.userData.selectionAccent = true;
  object.add(ring);

  if (node.type === "dataset") {
    const tiltedRing = new THREE.Mesh(
      new THREE.TorusGeometry(radius * 1.42, 0.75, 6, 72),
      ringMaterial.clone(),
    );
    tiltedRing.rotation.set(Math.PI / 2.8, Math.PI / 5.8, 0);
    tiltedRing.userData.selectionAccent = true;
    object.add(tiltedRing);

    const shell = new THREE.Mesh(
      new THREE.SphereGeometry(radius * 1.45, 32, 20),
      new THREE.MeshBasicMaterial({
        color,
        transparent: true,
        opacity: 0.11,
        wireframe: true,
        depthWrite: false,
      }),
    );
    object.add(shell);
  }
}

function nodeGeometry(node, radius) {
  if (node.type === "index") {
    return new THREE.DodecahedronGeometry(radius, 0);
  }
  if (node.type === "source" || node.type === "repository") {
    return new THREE.IcosahedronGeometry(radius, 1);
  }
  return new THREE.SphereGeometry(radius, 28, 18);
}

function nodeRadius(node) {
  const base = Number(node.size || 24);
  if (node.type === "dataset") return clamp(base * 0.44, 18, 26);
  if (node.type === "index") return clamp(base * 0.36, 12, 18);
  return clamp(base * 0.42, 9, 24);
}

function graphLayoutScale() {
  if (graph.width < 560) return 0.82;
  if (graph.width < 900) return 0.88;
  return 1;
}

function shouldShowNodeLabel(node) {
  if (state.graphMode === "knowledge") {
    if (graph.width < 560) return false;
    const total = state.realGraph?.nodes?.size || 0;
    if (total <= 48) return true;
    return Number(node.metadata?.links || 0) >= 2;
  }
  return graph.width >= 560 || node.type === "dataset";
}

function createLabelSprite(node, radius) {
  const labelLength = graph.width < 560 ? 16 : node.type === "repository" ? 18 : 22;
  const label = truncate(String(node.label || node.id), labelLength);
  const labelCanvas = document.createElement("canvas");
  const context = labelCanvas.getContext("2d");
  const scale = 2;
  const fontSize = graph.width < 560 ? 15 : 17;
  const labelHeight = graph.width < 560 ? 34 : 38;
  context.font = `650 ${fontSize}px Inter, system-ui, sans-serif`;
  const textWidth = Math.min(context.measureText(label).width, graph.width < 560 ? 160 : 240);
  const width = Math.ceil(textWidth + 40);
  const height = labelHeight;
  labelCanvas.width = width * scale;
  labelCanvas.height = height * scale;
  context.scale(scale, scale);
  context.font = `650 ${fontSize}px Inter, system-ui, sans-serif`;
  context.textBaseline = "middle";

  roundedRect(context, 0.5, 0.5, width - 1, height - 1, 8);
  context.fillStyle = "rgba(30, 30, 30, 0.86)";
  context.fill();
  context.strokeStyle = "rgba(186, 186, 186, 0.24)";
  context.stroke();

  context.beginPath();
  context.arc(16, height / 2, 3.5, 0, Math.PI * 2);
  context.fillStyle =
    state.graphMode === "knowledge" ? typeColor(node.type) : colors[node.type] || "#b5bdc9";
  context.fill();
  context.fillStyle = "#eff0f7";
  context.fillText(label, 27, height / 2, width - 36);

  const texture = new THREE.CanvasTexture(labelCanvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.minFilter = THREE.LinearFilter;
  texture.magFilter = THREE.LinearFilter;
  const material = new THREE.SpriteMaterial({
    map: texture,
    transparent: true,
    opacity: 0.78,
    depthTest: false,
    depthWrite: false,
  });
  const sprite = new THREE.Sprite(material);
  const labelScale = clamp(radius * 1.7, 24, 34);
  sprite.scale.set((width / height) * labelScale, labelScale, 1);
  return sprite;
}

function labelPosition(node, radius) {
  const position = new THREE.Vector3(node.x, node.y, node.z);
  if (node.type === "dataset") {
    return position.add(new THREE.Vector3(0, radius + 44, 12));
  }

  const outward = new THREE.Vector3(node.x, node.y * 1.45, node.z * 0.45);
  if (outward.lengthSq() < 1) {
    outward.set(0, 1, 0);
  }
  outward.normalize();
  return position.add(outward.multiplyScalar(radius + 44));
}

function roundedRect(context, x, y, width, height, radius) {
  context.beginPath();
  context.moveTo(x + radius, y);
  context.arcTo(x + width, y, x + width, y + height, radius);
  context.arcTo(x + width, y + height, x, y + height, radius);
  context.arcTo(x, y + height, x, y, radius);
  context.arcTo(x, y, x + width, y, radius);
  context.closePath();
}

function updateNodeSelection() {
  for (const [id, mesh] of graph.nodeMeshes.entries()) {
    const selected = id === state.selectedId;
    const object = graph.nodeObjects.get(id);
    if (object) object.scale.setScalar(selected ? 1.16 : 1);
    mesh.material.emissiveIntensity = selected ? 0.36 : 0.1;
    mesh.parent?.traverse((child) => {
      if (child.userData.selectionAccent && child.material) {
        child.material.opacity = selected ? 0.48 : id.startsWith("dataset:") ? 0.34 : 0.18;
      }
    });
  }
  for (const [id, sprite] of graph.nodeLabelSprites.entries()) {
    sprite.material.opacity = id === state.selectedId ? 0.98 : 0.78;
  }
  renderGraphScene();
}

function renderGraphScene() {
  if (!graph.renderer || !graph.camera || !graph.root) return;
  animateNodeObjects();
  const damping = graph.reducedMotion ? 1 : 0.14;
  graph.yaw += (graph.targetYaw - graph.yaw) * damping;
  graph.pitch += (graph.targetPitch - graph.pitch) * damping;
  graph.distance += (graph.targetDistance - graph.distance) * damping;
  graph.root.position.y = graph.width < 560 ? 56 : 70;
  graph.root.rotation.set(graph.pitch, graph.yaw, 0);
  graph.camera.position.set(0, 0, graph.distance);
  graph.camera.lookAt(0, graph.width < 560 ? -24 : -16, 0);
  graph.renderer.render(graph.scene, graph.camera);
}

function animateNodeObjects() {
  if (graph.reducedMotion || state.paused || graph.pointerDown) return;
  const now = performance.now() * 0.001;
  for (const [id, object] of graph.nodeObjects.entries()) {
    const seed = hashUnit(id);
    object.rotation.y = now * (0.12 + seed * 0.06) + seed * Math.PI;
    object.rotation.x = Math.sin(now * 0.32 + seed * Math.PI * 2) * 0.035;
  }
}

function animateGraph() {
  renderGraphScene();
  graph.animationFrame = window.requestAnimationFrame(animateGraph);
}

function resetGraphView() {
  graph.targetYaw = -0.34;
  graph.targetPitch = graph.width < 560 ? -0.1 : -0.12;
  graph.targetDistance = defaultGraphDistance();
  graph.yaw = graph.targetYaw;
  graph.pitch = graph.targetPitch;
  graph.distance = graph.targetDistance;
  renderGraphScene();
}

function fitGraphDistance() {
  const min = graph.width < 560 ? 720 : 620;
  const max = graph.width < 560 ? 1440 : 1180;
  graph.targetDistance = clamp(graph.targetDistance, min, max);
  graph.distance = clamp(graph.distance, min, max);
}

function defaultGraphDistance() {
  const nodeCount = Math.max(activeGraphData().nodes.size, 5);
  const density = clamp(Math.sqrt(nodeCount / 16), 1, 1.42);
  const viewportScale = graph.width < 560 ? 1.08 : graph.width < 900 ? 1.12 : 1;
  return clamp(
    720 * density * viewportScale,
    graph.width < 560 ? 780 : 650,
    graph.width < 560 ? 1380 : 1120,
  );
}

function compareNodes(a, b) {
  const order = {
    dataset: 0,
    index: 1,
    source: 2,
    repository: 3,
    document: 4,
    tag: 5,
    query: 6,
    feedback: 7,
    upgrade: 8,
  };
  const typeDelta = (order[a.type] ?? 99) - (order[b.type] ?? 99);
  if (typeDelta) return typeDelta;
  return String(a.label || a.id).localeCompare(String(b.label || b.id));
}

function hashUnit(value) {
  let hash = 2166136261;
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return (hash >>> 0) / 4294967295;
}

function setRaycasterPointer(event) {
  const rect = canvas.getBoundingClientRect();
  graph.pointer.x = ((event.clientX - rect.left) / Math.max(rect.width, 1)) * 2 - 1;
  graph.pointer.y = -(((event.clientY - rect.top) / Math.max(rect.height, 1)) * 2 - 1);
}

function nearestNode(event) {
  if (!graph.camera || !graph.root) return null;
  setRaycasterPointer(event);
  graph.root.updateMatrixWorld(true);
  graph.raycaster.setFromCamera(graph.pointer, graph.camera);
  const intersections = graph.raycaster.intersectObjects(Array.from(graph.nodeMeshes.values()), false);
  const hit = intersections[0]?.object;
  return hit ? activeGraphData().nodes.get(hit.userData.nodeId) || null : null;
}

function clamp(value, min, max) {
  return Math.min(Math.max(value, min), max);
}

function truncate(value, length) {
  return value.length > length ? `${value.slice(0, length - 1)}.` : value;
}

function selectNode(node) {
  state.selectedId = node?.id || null;
  if (!node) {
    selectedNode.textContent = "Select a note or node to inspect its links.";
    updateNodeSelection();
    return;
  }
  selectedNode.innerHTML = `
    <div>
      <strong>${escapeHtml(node.label)}</strong>
      <span>${escapeHtml(node.type)} - ${escapeHtml(node.status)}</span>
    </div>
    <p>${escapeHtml(formatDetails(node.metadata || {}))}</p>
  `;
  updateNodeSelection();
}

async function loadMesh(showConnection = true) {
  try {
    const snapshot = await api("/api/mesh");
    mergeGraph(snapshot);
    if (showConnection) {
      setConnectionState("enabled", "Live");
    }
  } catch (error) {
    setConnectionState("error", "Offline");
    meshAlert.hidden = false;
    meshAlertText.textContent = error.message || "Try refreshing the vault.";
    console.error(error);
  }
}

function showToast(message, kind = "info") {
  if (!toastStack) return;
  const toast = document.createElement("div");
  toast.className = `toast toast-${kind}`;
  toast.textContent = message;
  toastStack.append(toast);
  window.setTimeout(() => {
    toast.classList.add("toast-leaving");
    window.setTimeout(() => toast.remove(), 200);
  }, 4200);
}

function updateGraphMeta(message) {
  if (message) {
    graphMeta.textContent = message;
    return;
  }
  if (state.graphMode === "knowledge") {
    const payload = state.realGraph?.payload;
    if (!payload) {
      graphMeta.textContent = "Loading knowledge graph";
      return;
    }
    const shown = state.realGraph.nodes.size;
    const truncated = payload.truncated ? ` of ${payload.total_nodes}` : "";
    graphMeta.textContent = `Cognee graph - ${shown}${truncated} nodes - ${state.realGraph.edges.length} edges`;
    return;
  }
  if (state.snapshot) {
    graphMeta.textContent = `${state.snapshot.default_dataset} - rev ${state.snapshot.revision} - ${formatDate(state.snapshot.generated_at)}`;
  } else {
    graphMeta.textContent = "Waiting for snapshot";
  }
}

function updateRealGraphEmpty() {
  if (!realGraphEmpty) return;
  const payload = state.realGraph?.payload;
  const show = state.graphMode === "knowledge" && Boolean(payload) && !state.realGraph.nodes.size;
  realGraphEmpty.hidden = !show;
  if (show) {
    const text = realGraphEmpty.querySelector("p");
    if (text) {
      text.textContent = payload.fallback
        ? "Cognee has not produced graph data yet. Ingest notes or run source sync, then check back."
        : "The knowledge graph is empty. Ingest notes or run source sync, then check back.";
    }
  }
}

function shapeRealGraph(payload) {
  const degree = new Map();
  const rawEdges = Array.isArray(payload.edges) ? payload.edges : [];
  rawEdges.forEach((edge) => {
    degree.set(edge.source, (degree.get(edge.source) || 0) + 1);
    degree.set(edge.target, (degree.get(edge.target) || 0) + 1);
  });

  const nodes = new Map();
  const list = Array.isArray(payload.nodes) ? payload.nodes : [];
  const count = Math.max(list.length, 1);
  const radius = clamp(170 + Math.sqrt(count) * 26, 210, 470);
  const golden = Math.PI * (3 - Math.sqrt(5));
  list.forEach((node, index) => {
    const t = count === 1 ? 0.5 : index / (count - 1);
    const y = 1 - t * 2;
    const ring = Math.sqrt(Math.max(0, 1 - y * y));
    const angle = golden * index;
    const links = degree.get(node.id) || 0;
    nodes.set(node.id, {
      id: node.id,
      label: node.label || node.id,
      type: node.type || "node",
      status: "linked",
      size: clamp(26 + links * 5, 24, 58),
      metadata: { type: node.type || "node", links },
      x: Math.cos(angle) * ring * radius,
      y: y * radius * 0.72,
      z: Math.sin(angle) * ring * radius,
    });
  });

  return {
    nodes,
    edges: rawEdges.filter((edge) => nodes.has(edge.source) && nodes.has(edge.target)),
    payload,
  };
}

async function loadKnowledgeGraph(force = false) {
  if (state.realGraphLoading) return;
  if (state.realGraph && !force) {
    buildGraphScene();
    resetGraphView();
    updateGraphMeta();
    updateRealGraphEmpty();
    return;
  }
  state.realGraphLoading = true;
  updateGraphMeta("Loading knowledge graph");
  try {
    const payload = await api("/api/mesh/graph");
    state.realGraph = shapeRealGraph(payload);
    if (state.graphMode === "knowledge") {
      buildGraphScene();
      resetGraphView();
      updateGraphMeta();
      updateRealGraphEmpty();
    }
  } catch (error) {
    showToast(`Could not load the knowledge graph: ${error.message}`, "error");
    if (state.graphMode === "knowledge") {
      updateGraphMeta("Knowledge graph unavailable");
    }
  } finally {
    state.realGraphLoading = false;
  }
}

function setGraphMode(mode) {
  if (state.graphMode === mode) return;
  state.graphMode = mode;
  graphModeButtons.forEach((button) => {
    const active = button.dataset.graphMode === mode;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", active ? "true" : "false");
  });
  state.selectedId = null;
  selectedNode.textContent = "Select a note or node to inspect its links.";
  if (mode === "knowledge") {
    canvasEmpty.hidden = true;
    buildGraphScene();
    updateGraphMeta();
    updateRealGraphEmpty();
    loadKnowledgeGraph();
    return;
  }
  realGraphEmpty.hidden = true;
  buildGraphScene();
  resetGraphView();
  updateGraphMeta();
  canvasEmpty.hidden = !state.snapshot || state.snapshot.nodes.length > 4;
}

function conflictSideMarkup(label, side = {}) {
  return `
    <div class="conflict-side">
      <div class="conflict-side-head">
        <span class="conflict-side-label">${escapeHtml(label)}</span>
        <time class="event-time">${escapeHtml(side.timestamp ? formatDate(side.timestamp) : "no timestamp")}</time>
      </div>
      <p class="conflict-source">${escapeHtml(side.source || "unknown source")}</p>
      <pre class="conflict-excerpt">${escapeHtml(side.excerpt || "(empty excerpt)")}</pre>
    </div>
  `;
}

function updateConflictBadge(openCount) {
  if (!conflictNavBadge) return;
  conflictNavBadge.textContent = String(openCount);
  conflictNavBadge.hidden = !openCount;
  if (knowledgeConflictCount) knowledgeConflictCount.textContent = String(openCount);
}

function renderConflicts() {
  if (!conflictsList) return;
  conflictFilterButtons.forEach((button) => {
    const active = button.dataset.conflictFilter === state.conflictFilter;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", active ? "true" : "false");
  });
  conflictsList.innerHTML = "";
  if (!state.conflicts.length) {
    const labels = {
      open: ["No open conflicts", "Disagreements between sources will appear here for review."],
      resolved: ["No resolved conflicts yet", "Resolved conflicts keep their resolution note for the audit trail."],
      all: ["No conflicts recorded", "Disagreements between sources will appear here for review."],
    };
    const [title, body] = labels[state.conflictFilter] || labels.all;
    conflictsList.append(emptyState(title, body));
    return;
  }
  const canResolve = canUse("writer");
  state.conflicts.forEach((conflict) => {
    const open = conflict.status === "open";
    const card = document.createElement("article");
    card.className = `conflict-card${open ? " conflict-open" : ""}`;
    card.innerHTML = `
      <div class="conflict-head">
        <div class="conflict-head-meta">
          <span class="conflict-kind">${escapeHtml(conflict.kind || "conflict")}</span>
          <span class="conflict-id">${escapeHtml(conflict.id || "")}</span>
        </div>
        <div class="conflict-head-meta">
          <time class="event-time">${escapeHtml(formatDate(conflict.detected_at))}</time>
          <span class="status-chip ${open ? "status-standby" : "status-enabled"}">${escapeHtml(conflict.status || "open")}</span>
        </div>
      </div>
      <p class="conflict-summary">${escapeHtml(conflict.summary || "Conflicting knowledge detected.")}</p>
      <div class="conflict-sides">
        ${conflictSideMarkup("Side A", conflict.side_a)}
        ${conflictSideMarkup("Side B", conflict.side_b)}
      </div>
    `;
    if (open) {
      const form = document.createElement("form");
      form.className = "conflict-resolve";
      const input = document.createElement("input");
      input.type = "text";
      input.name = "resolutionNote";
      input.placeholder = "Resolution note (which side wins, and why)";
      input.autocomplete = "off";
      input.required = true;
      input.maxLength = 400;
      input.disabled = !canResolve;
      input.setAttribute("aria-label", "Resolution note");
      const button = document.createElement("button");
      button.type = "submit";
      button.className = "primary-button";
      button.textContent = "Resolve";
      button.disabled = !canResolve;
      if (!canResolve) {
        button.title = "Writer access required";
      }
      form.append(input, button);
      form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const note = input.value.trim();
        if (!note) {
          input.focus();
          return;
        }
        setBusy(button, true, { idle: "Resolve", loading: "Resolving" });
        try {
          await api(`/api/conflicts/${encodeURIComponent(conflict.id)}/resolve`, {
            method: "POST",
            body: JSON.stringify({ resolution_note: note }),
          });
          showToast("Conflict resolved.", "success");
          await loadConflicts();
        } catch (error) {
          showToast(`Could not resolve conflict: ${error.message}`, "error");
          setBusy(button, false, { idle: "Resolve", loading: "Resolving" });
        }
      });
      card.append(form);
    } else {
      const resolution = document.createElement("div");
      resolution.className = "conflict-resolution";
      resolution.innerHTML = `
        <strong>Resolved</strong>
        <span>${escapeHtml(conflict.resolution_note || "No resolution note.")}</span>
        <span>${escapeHtml(conflict.resolved_by || "unknown")} - ${escapeHtml(formatDate(conflict.resolved_at))}</span>
      `;
      card.append(resolution);
    }
    conflictsList.append(card);
  });
}

async function loadConflicts() {
  if (!conflictsList) return;
  if (conflictsStatus) {
    conflictsStatus.textContent = "Loading";
    conflictsStatus.className = "status-chip status-standby";
  }
  try {
    const query = state.conflictFilter === "all" ? "" : `?status=${state.conflictFilter}`;
    const payload = await api(`/api/conflicts${query}`);
    state.conflicts = payload.conflicts || [];
    const openCount = Number(payload.open_count || 0);
    updateConflictBadge(openCount);
    if (conflictsStatus) {
      conflictsStatus.textContent = openCount ? `${openCount} open` : "Clear";
      conflictsStatus.className = `status-chip ${openCount ? "status-standby" : "status-enabled"}`;
    }
    renderConflicts();
  } catch (error) {
    if (conflictsStatus) {
      conflictsStatus.textContent = "Error";
      conflictsStatus.className = "status-chip status-error";
    }
    state.conflicts = [];
    conflictsList.innerHTML = "";
    conflictsList.append(emptyState("Could not load conflicts", error.message));
  }
}

async function loadGithubSync() {
  try {
    const status = await api("/api/github-sync");
    state.githubSync = status;
    githubSyncStatus.textContent = status.last_checked_at ? "Tracked" : "Ready";
    githubSyncStatus.className = `status-chip ${status.last_checked_at ? "status-enabled" : "status-standby"}`;
    syncLastChecked.textContent = formatDate(status.last_checked_at);
    syncTrackedRepos.textContent = status.tracked_repositories;
    githubSourceLink.href = status.source_url;
    githubSourceLink.textContent = status.source_url.replace("https://", "");
    if (dashboardCronStatus) {
      dashboardCronStatus.textContent = status.last_checked_at ? "Connected" : "Ready";
      dashboardCronMeta.textContent = status.last_checked_at
        ? `last sync ${formatDate(status.last_checked_at)}`
        : "waiting for first sync";
      dashboardIngestStatus.textContent = status.last_checked_at ? "Running" : "Ready";
      dashboardIngestStatus.className = `status-chip ${status.last_checked_at ? "status-enabled" : "status-standby"}`;
      dashboardIngestionList.innerHTML = `
        <div class="entity-item">
          <div>
            <strong>Source inbox</strong>
            <p>${escapeHtml(status.tracked_repositories)} repositories tracked</p>
          </div>
          <span class="status-chip ${status.last_checked_at ? "status-enabled" : "status-standby"}">${escapeHtml(status.last_checked_at ? "tracked" : "ready")}</span>
        </div>
        <div class="entity-item">
          <div>
            <strong>Linked note index</strong>
            <p>New source material flows into graph and vector memory.</p>
          </div>
          <span class="status-chip status-enabled">live</span>
        </div>
        <div class="entity-item">
          <div>
            <strong>Shared learning loop</strong>
            <p>${status.run_improve ? "Runs improvement after sync." : "Manual improvement enabled from Sources."}</p>
          </div>
          <span class="status-chip ${status.run_improve ? "status-enabled" : "status-standby"}">${status.run_improve ? "auto" : "manual"}</span>
        </div>
      `;
    }
    renderKnowledgeDailyUpdate(status);
    renderKnowledgeSources();
  } catch (error) {
    state.githubSync = null;
    githubSyncStatus.textContent = "Error";
    githubSyncStatus.className = "status-chip status-error";
    syncResult.innerHTML = "";
    syncResult.append(emptyState("Could not load sync status", error.message));
    if (dashboardCronStatus) {
      dashboardCronStatus.textContent = "Error";
      dashboardCronMeta.textContent = "sync status failed";
      dashboardIngestStatus.textContent = "Error";
      dashboardIngestStatus.className = "status-chip status-error";
      dashboardIngestionList.innerHTML = "";
      dashboardIngestionList.append(emptyState("Could not load source inbox", error.message));
    }
    renderKnowledgeSources(error);
  }
}

async function loadObsidianSources() {
  if (!obsidianSourceStatus || !obsidianSourceList) return;
  try {
    const payload = await api("/api/sources?type=obsidian_vault");
    state.obsidianSources = payload;
    const summary = payload.summary || {};
    const sources = payload.sources || [];
    const vaults = Number(summary.obsidian_vaults || 0);
    const documents = Number(summary.obsidian_documents || 0);
    const conflicts = Number(summary.open_conflicts || 0);
    obsidianVaultCount.textContent = String(vaults);
    obsidianDocumentCount.textContent = String(documents);
    obsidianSourceStatus.textContent = conflicts ? "Conflict" : vaults ? "Connected" : "Ready";
    obsidianSourceStatus.className = `status-chip ${
      conflicts ? "status-error" : vaults ? "status-enabled" : "status-standby"
    }`;
    obsidianSourceList.innerHTML = "";

    if (!sources.length) {
      obsidianSourceList.append(emptyState("No Obsidian vaults", "Register a team vault source."));
    } else {
      sources.forEach((source) => {
        const item = document.createElement("div");
        item.className = "entity-item";
        item.innerHTML = `
          <div>
            <strong>${escapeHtml(source.name || "Obsidian vault")}</strong>
            <p>${escapeHtml(source.documents || 0)} notes · ${escapeHtml(formatDate(source.last_push_at))}</p>
          </div>
          <span class="status-chip ${
            source.open_conflicts ? "status-error" : "status-enabled"
          }">${source.open_conflicts ? "conflict" : "synced"}</span>
        `;
        obsidianSourceList.append(item);
      });
    }

    if (dashboardIngestionList && sources.length) {
      sources.slice(0, 2).forEach((source) => {
        const item = document.createElement("div");
        item.className = "entity-item";
        item.innerHTML = `
          <div>
            <strong>${escapeHtml(source.name || "Obsidian vault")}</strong>
            <p>${escapeHtml(source.documents || 0)} synced notes from the team vault.</p>
          </div>
          <span class="status-chip ${
            source.open_conflicts ? "status-error" : "status-enabled"
          }">${source.open_conflicts ? "review" : "ready"}</span>
        `;
        dashboardIngestionList.append(item);
      });
    }
    renderKnowledgeSources();
  } catch (error) {
    state.obsidianSources = null;
    obsidianSourceStatus.textContent = "Error";
    obsidianSourceStatus.className = "status-chip status-error";
    obsidianSourceList.innerHTML = "";
    obsidianSourceList.append(emptyState("Could not load Obsidian sources", error.message));
    renderKnowledgeSources(error);
  }
}

function renderKnowledgeDailyUpdate(status = state.githubSync) {
  if (!knowledgeDailyUpdate || !knowledgeDigestStatus) return;
  knowledgeDailyUpdate.innerHTML = "";
  if (!status) {
    knowledgeDigestStatus.textContent = "Waiting";
    knowledgeDigestStatus.className = "status-chip status-standby";
    knowledgeDailyUpdate.append(emptyState("No repository status", "Run or load source sync status."));
    return;
  }
  const checked = Boolean(status.last_checked_at);
  knowledgeDigestStatus.textContent = checked ? "Tracked" : "Ready";
  knowledgeDigestStatus.className = `status-chip ${checked ? "status-enabled" : "status-standby"}`;
  const rows = [
    ["Organization", status.org || "masumi-network", checked ? "tracked" : "ready"],
    ["Last digest", formatDate(status.last_digest_at || status.last_checked_at), "daily"],
    ["Repositories", `${status.tracked_repositories || 0} tracked`, "source"],
    ["Recent commits", `${status.tracked_commit_repositories || 0} repositories`, "context"],
  ];
  rows.forEach(([label, value, chip]) => {
    const item = document.createElement("div");
    item.className = "entity-item";
    item.innerHTML = `
      <div>
        <strong>${escapeHtml(label)}</strong>
        <p>${escapeHtml(value)}</p>
      </div>
      <span class="status-chip ${checked ? "status-enabled" : "status-standby"}">${escapeHtml(chip)}</span>
    `;
    knowledgeDailyUpdate.append(item);
  });
}

function renderKnowledgeSources(error = null) {
  if (!knowledgeSourceList) return;
  knowledgeSourceList.innerHTML = "";
  if (error) {
    knowledgeSourceList.append(emptyState("Could not load sources", error.message));
    if (knowledgeStatus) {
      knowledgeStatus.textContent = "Source error";
      knowledgeStatus.className = "status-chip status-error";
    }
    return;
  }

  const github = state.githubSync;
  const obsidianPayload = state.obsidianSources || {};
  const obsidianSources = obsidianPayload.sources || [];
  const summary = obsidianPayload.summary || {};
  const sourceRows = [];
  if (github) {
    sourceRows.push({
      name: `GitHub: ${github.org || "organization"}`,
      body: `${github.tracked_repositories || 0} repositories - ${formatDate(github.last_checked_at)}`,
      status: github.last_checked_at ? "tracked" : "ready",
      error: false,
    });
  }
  obsidianSources.forEach((source) => {
    sourceRows.push({
      name: source.name || "Obsidian vault",
      body: `${source.documents || 0} notes - ${formatDate(source.last_push_at)}`,
      status: source.open_conflicts ? "review" : "synced",
      error: Boolean(source.open_conflicts),
    });
  });

  const sourceCount = sourceRows.length;
  const snapshotCount = Number(github?.tracked_repositories || 0) + Number(summary.obsidian_documents || 0);
  const conflictCount = Number(summary.open_conflicts || 0);
  if (knowledgeSourceCount) knowledgeSourceCount.textContent = String(sourceCount);
  if (knowledgeSnapshotCount && !state.snapshot) knowledgeSnapshotCount.textContent = String(snapshotCount);
  if (knowledgeConflictCount) knowledgeConflictCount.textContent = String(conflictCount);

  if (!sourceRows.length) {
    knowledgeSourceList.append(emptyState("No connected sources", "GitHub and Obsidian sources will appear here."));
    return;
  }

  sourceRows.forEach((source) => {
    const item = document.createElement("div");
    item.className = "entity-item";
    item.innerHTML = `
      <div>
        <strong>${escapeHtml(source.name)}</strong>
        <p>${escapeHtml(source.body)}</p>
      </div>
      <span class="status-chip ${source.error ? "status-error" : "status-enabled"}">${escapeHtml(source.status)}</span>
    `;
    knowledgeSourceList.append(item);
  });
}

async function loadAccess() {
  if (!canUse("admin")) return;
  accessTokenStatus.textContent = "Loading";
  accessTokenStatus.className = "status-chip status-standby";
  if (agentsStatus) {
    agentsStatus.textContent = "Loading";
    agentsStatus.className = "status-chip status-standby";
  }
  if (auditStatus) {
    auditStatus.textContent = "Loading";
    auditStatus.className = "status-chip status-standby";
  }
  try {
    const snapshot = await api("/api/access");
    state.accessSnapshot = snapshot;
    renderAccess(snapshot);
    accessTokenStatus.textContent = "Ready";
    accessTokenStatus.className = "status-chip status-enabled";
    if (agentsStatus) {
      agentsStatus.textContent = "Ready";
      agentsStatus.className = "status-chip status-enabled";
    }
    if (auditStatus) {
      auditStatus.textContent = "Ready";
      auditStatus.className = "status-chip status-enabled";
    }
  } catch (error) {
    accessTokenStatus.textContent = "Error";
    accessTokenStatus.className = "status-chip status-error";
    if (agentsStatus) {
      agentsStatus.textContent = "Error";
      agentsStatus.className = "status-chip status-error";
    }
    if (auditStatus) {
      auditStatus.textContent = "Error";
      auditStatus.className = "status-chip status-error";
    }
    accessPrincipalList.innerHTML = "";
    accessPrincipalList.append(emptyState("Could not load access", error.message));
    if (agentsTokenList) {
      agentsTokenList.innerHTML = "";
      agentsTokenList.append(emptyState("Could not load agents", error.message));
    }
    if (auditAccessList) {
      auditAccessList.innerHTML = "";
      auditAccessList.append(emptyListItem("Could not load audit", error.message));
    }
  }
}

function renderAccess(snapshot) {
  accessPrincipalList.innerHTML = "";
  accessTokenList.innerHTML = "";
  accessAuditList.innerHTML = "";
  renderDashboardMcpAccess(snapshot);
  renderAgents(snapshot);
  renderAuditAccessEvents(snapshot.audit_events || []);

  if (!snapshot.principals?.length) {
    accessPrincipalList.append(
      emptyState("No stored principals", "Create a teammate or service-account token."),
    );
  } else {
    snapshot.principals.forEach((principal) => {
      const item = document.createElement("div");
      item.className = "entity-item";
      item.innerHTML = `
        <div>
          <strong>${escapeHtml(principal.name)}</strong>
          <p>${escapeHtml(principal.kind)} - ${escapeHtml(roleLabel(principal.role))}</p>
          <p>${escapeHtml((principal.scopes || []).join(", "))}</p>
          ${principal.seat_slug ? `<p>Seat ${escapeHtml(principal.seat_slug)} - ${escapeHtml(principal.default_dataset || "unset")}</p>` : ""}
        </div>
        <span class="status-chip status-enabled">${escapeHtml(principal.team_id || "default")}</span>
      `;
      accessPrincipalList.append(item);
    });
  }

  if (!snapshot.tokens?.length) {
    accessTokenList.append(emptyState("No stored tokens", "Bootstrap env keys are still available."));
  } else {
    snapshot.tokens.forEach((token) => {
      const item = document.createElement("div");
      item.className = "entity-item";
      const status = token.revoked_at ? "Revoked" : token.expires_at ? "Expires" : "Active";
      item.innerHTML = `
        <div>
          <strong>${escapeHtml(token.name)}</strong>
          <p>${escapeHtml(token.prefix)}... - ${escapeHtml(roleLabel(token.role))}</p>
          <p>Last used ${escapeHtml(formatDate(token.last_used_at))}</p>
          ${token.default_dataset ? `<p>${escapeHtml(token.default_dataset)}</p>` : ""}
        </div>
      `;
      const action = document.createElement("button");
      action.className = "secondary-button compact-button";
      action.type = "button";
      action.textContent = token.revoked_at ? "Revoked" : "Revoke";
      action.disabled = Boolean(token.revoked_at);
      action.title = status;
      action.addEventListener("click", () => revokeAccessToken(token.id));
      item.append(action);
      accessTokenList.append(item);
    });
  }

  const events = snapshot.audit_events || [];
  events.slice(-12).reverse().forEach((event) => {
    accessAuditList.append(eventListItem(event));
  });
  if (!events.length) {
    accessAuditList.append(emptyListItem("No audit events", "Create or revoke a token to start the trail."));
  }
}

function renderAgents(snapshot) {
  if (!agentsTokenList) return;
  agentsTokenList.innerHTML = "";
  const principalsById = new Map((snapshot.principals || []).map((principal) => [principal.id, principal]));
  const agentTokens = (snapshot.tokens || []).filter((token) => {
    const principal = principalsById.get(token.principal_id);
    return principal?.kind === "service_account";
  });
  const activeAgentTokens = agentTokens.filter((token) => !token.revoked_at);
  if (agentsStatus) {
    agentsStatus.textContent = `${activeAgentTokens.length} active`;
    agentsStatus.className = `status-chip ${activeAgentTokens.length ? "status-enabled" : "status-standby"}`;
  }
  if (!agentTokens.length) {
    agentsTokenList.append(emptyState("No service-account tokens", "Create an autonomous agent token from Access."));
    return;
  }
  agentTokens.forEach((token) => {
    const principal = principalsById.get(token.principal_id);
    const revoked = Boolean(token.revoked_at);
    const item = document.createElement("div");
    item.className = "entity-item";
    item.innerHTML = `
      <div>
        <strong>${escapeHtml(token.name)}</strong>
        <p>${escapeHtml(roleLabel(token.role))} - ${escapeHtml(principal?.team_id || token.team_id || "default")}</p>
        <p>${escapeHtml((token.scopes || []).join(", "))}</p>
      </div>
      <span class="status-chip ${revoked ? "status-error" : "status-enabled"}">${escapeHtml(revoked ? "revoked" : token.prefix + "...")}</span>
    `;
    agentsTokenList.append(item);
  });
}

function renderAuditAccessEvents(events = []) {
  if (!auditAccessList) return;
  auditAccessList.innerHTML = "";
  const filtered = renderAuditFilterState(events);
  if (!filtered.length) {
    auditAccessList.append(emptyListItem("No matching events", "Change the audit filter or run an agent action."));
    return;
  }
  filtered.slice(-30).reverse().forEach((event) => {
    auditAccessList.append(eventListItem(event));
  });
}

async function loadSettings() {
  if (!canUse("admin") || !settingsHealthGrid) return;
  settingsStatus.textContent = "Loading";
  settingsStatus.className = "status-chip status-standby";
  settingsHealthGrid.innerHTML = `
    <div class="skeleton index-skeleton"></div>
    <div class="skeleton index-skeleton"></div>
    <div class="skeleton index-skeleton"></div>
  `;
  try {
    const [ready, learning, mirror] = await Promise.all([
      api("/readyz"),
      api("/api/learning-agent"),
      api("/api/backup-mirror").catch((error) => ({ ok: false, error: error.message })),
    ]);
    state.settingsSnapshot = { ready, learning, mirror };
    renderSettings(state.settingsSnapshot);
    settingsStatus.textContent = "Ready";
    settingsStatus.className = "status-chip status-enabled";
  } catch (error) {
    settingsStatus.textContent = "Error";
    settingsStatus.className = "status-chip status-error";
    settingsHealthGrid.innerHTML = "";
    settingsHealthGrid.append(emptyState("Could not load settings", error.message));
  }
}

function renderSettings(snapshot) {
  if (!settingsHealthGrid) return;
  const ready = snapshot.ready || {};
  const learning = snapshot.learning || {};
  const github = learning.sources?.github || {};
  renderSettingsMirror(snapshot.mirror);
  const rows = [
    {
      name: "HTTP service",
      body: `${ready.service || "citadel"} - tenant ${ready.tenant_id || "default"}`,
      status: ready.ok ? "ready" : "error",
      error: !ready.ok,
    },
    {
      name: "Default dataset",
      body: ready.default_dataset || "unset",
      status: "config",
      error: false,
    },
    {
      name: "Auto improvement",
      body: ready.auto_improve ? "Enabled after accepted ingest" : "Manual improvement",
      status: ready.auto_improve ? "enabled" : "manual",
      error: false,
    },
    {
      name: "Global context index",
      body: ready.build_global_context_index ? "Enabled" : "Disabled",
      status: ready.build_global_context_index ? "enabled" : "off",
      error: !ready.build_global_context_index,
    },
    {
      name: "Learning agent",
      body: `${(learning.capabilities || []).join(", ") || "status loaded"}`,
      status: learning.ok ? "ready" : "error",
      error: !learning.ok,
    },
    {
      name: "GitHub source",
      body: `${github.org || "masumi-network"} - ${github.tracked_repositories || 0} repositories`,
      status: github.last_checked_at ? "tracked" : "ready",
      error: false,
    },
  ];

  settingsHealthGrid.innerHTML = "";
  rows.forEach((row) => {
    const item = document.createElement("div");
    item.className = "entity-item";
    item.innerHTML = `
      <div>
        <strong>${escapeHtml(row.name)}</strong>
        <p>${escapeHtml(row.body)}</p>
      </div>
      <span class="status-chip ${row.error ? "status-error" : "status-enabled"}">${escapeHtml(row.status)}</span>
    `;
    settingsHealthGrid.append(item);
  });
}

function renderSettingsMirror(mirror) {
  if (!settingsMirrorList) return;
  settingsMirrorList.innerHTML = "";
  if (!mirror || mirror.ok === false) {
    settingsMirrorList.append(
      emptyState(
        "Mirror status unavailable",
        mirror?.error || "The server did not return mirror status.",
      ),
    );
    return;
  }

  const summary = mirror.summary || {};
  const latest = mirror.latest_export || null;
  const rows = [
    {
      name: "Manifest exporter",
      body: `${mirror.repo || "Vault-Backup-Mirror"} on ${mirror.branch || "main"}`,
      status: mirror.enabled ? "enabled" : "dry-run",
      error: false,
    },
    {
      name: "Tracked state files",
      body: `${summary.available_files || 0}/${summary.tracked_files || 0} available - ${formatBytes(summary.total_bytes)}`,
      status: summary.missing_files ? "partial" : "tracked",
      error: false,
    },
    {
      name: "Latest manifest",
      body: latest
        ? `${latest.snapshot_id || "snapshot"} - ${formatDate(latest.exported_at)}`
        : "No manifest written yet.",
      status: latest ? "ready" : "pending",
      error: false,
    },
  ];

  rows.forEach((row) => {
    const item = document.createElement("div");
    item.className = "entity-item";
    item.innerHTML = `
      <div>
        <strong>${escapeHtml(row.name)}</strong>
        <p>${escapeHtml(row.body)}</p>
      </div>
      <span class="status-chip ${row.error ? "status-error" : "status-enabled"}">${escapeHtml(row.status)}</span>
    `;
    settingsMirrorList.append(item);
  });
}

function renderLearningAgentRun(result) {
  const github = result.sources?.github || {};
  const digest = result.organization_digest || {};
  const chat = result.notifications?.google_chat || {};
  const chatLabel = chat.sent
    ? "sent"
    : chat.reason || chat.status_category || (chat.enabled ? "ready" : "disabled");
  const preview = digest.preview
    ? `<pre class="digest-preview">${escapeHtml(digest.preview)}</pre>`
    : "";
  syncResult.innerHTML = `
    <dl class="result-grid">
      <div><dt>Repos scanned</dt><dd>${escapeHtml(github.repos_scanned || 0)}</dd></div>
      <div><dt>Changed</dt><dd>${escapeHtml(github.changed_count || 0)}</dd></div>
      <div><dt>Open PRs</dt><dd>${escapeHtml(github.open_pull_request_count || 0)}</dd></div>
      <div><dt>Merged PRs</dt><dd>${escapeHtml(github.merged_pull_request_count || 0)}</dd></div>
      <div><dt>Digest</dt><dd>${digest.meaningful ? "Meaningful" : "Quiet"}</dd></div>
      <div><dt>Google Chat</dt><dd>${escapeHtml(chatLabel)}</dd></div>
    </dl>
    ${preview}
  `;
}

function renderDashboardMcpAccess(snapshot) {
  if (!dashboardMcpList || !dashboardMcpClients) return;
  const activeTokens = (snapshot.tokens || []).filter((token) => !token.revoked_at);
  dashboardMcpClients.textContent = `${activeTokens.length} active`;
  dashboardMcpMeta.textContent = `${(snapshot.principals || []).length} principals`;
  dashboardMcpStatus.textContent = "Authorized";
  dashboardMcpStatus.className = "status-chip status-enabled";
  dashboardMcpList.innerHTML = "";

  if (!activeTokens.length) {
    dashboardMcpList.append(emptyState("No MCP tokens", "Create a service-account token for agents."));
    return;
  }

  activeTokens.slice(0, 3).forEach((token) => {
    const item = document.createElement("div");
    item.className = "entity-item";
    item.innerHTML = `
      <div>
        <strong>${escapeHtml(token.name)}</strong>
        <p>${escapeHtml(roleLabel(token.role))} - ${escapeHtml((token.scopes || []).slice(0, 3).join(", "))}</p>
      </div>
      <span class="status-chip status-enabled">${escapeHtml(token.prefix)}...</span>
    `;
    dashboardMcpList.append(item);
  });
}

async function revokeAccessToken(tokenId) {
  accessTokenStatus.textContent = "Revoking";
  accessTokenStatus.className = "status-chip status-standby";
  try {
    await api(`/api/access/tokens/${encodeURIComponent(tokenId)}/revoke`, {
      method: "POST",
      body: JSON.stringify({}),
    });
    await loadAccess();
  } catch (error) {
    accessTokenStatus.textContent = "Error";
    accessTokenStatus.className = "status-chip status-error";
    accessTokenList.prepend(emptyState("Could not revoke token", error.message));
  }
}

function connectEvents() {
  if (!window.EventSource) {
    window.setInterval(() => loadMesh(false), 5000);
    return;
  }

  state.eventSource = new EventSource("/events");
  state.eventSource.addEventListener("open", () => {
    setConnectionState("enabled", "Live");
  });
  state.eventSource.addEventListener("snapshot", (event) => {
    mergeGraph(JSON.parse(event.data));
  });
  state.eventSource.addEventListener("mesh-event", () => {
    loadMesh(false);
  });
  state.eventSource.addEventListener("error", () => {
    setConnectionState("standby", "Reconnecting");
  });
}

document.getElementById("refreshButton").addEventListener("click", () => {
  loadMesh();
  loadGithubSync();
  loadObsidianSources();
  loadConflicts();
  if (state.graphMode === "knowledge") {
    loadKnowledgeGraph(true);
  }
  if (canUse("admin")) {
    loadAccess();
    loadSettings();
  }
});
document.getElementById("meshRetryButton").addEventListener("click", () => loadMesh());
document.getElementById("fitButton").addEventListener("click", () => {
  resetGraphView();
});
document.getElementById("pauseButton").addEventListener("click", (event) => {
  state.paused = !state.paused;
  event.currentTarget.textContent = state.paused ? "Resume" : "Pause";
  canvas.classList.toggle("is-paused", state.paused);
});

auditFilterButtons.forEach((button) => {
  button.addEventListener("click", () => {
    state.auditFilter = button.dataset.auditFilter || "all";
    renderAuditAccessEvents(state.accessSnapshot?.audit_events || []);
  });
});

conflictFilterButtons.forEach((button) => {
  button.addEventListener("click", () => {
    state.conflictFilter = button.dataset.conflictFilter || "open";
    loadConflicts();
  });
});

graphModeButtons.forEach((button) => {
  button.addEventListener("click", () => setGraphMode(button.dataset.graphMode || "live"));
});

canvas.addEventListener("pointerdown", (event) => {
  graph.pointerDown = true;
  graph.pointerMoved = false;
  graph.pendingNode = nearestNode(event);
  graph.lastPointerX = event.clientX;
  graph.lastPointerY = event.clientY;
  canvas.classList.add("dragging");
  canvas.setPointerCapture(event.pointerId);
});

canvas.addEventListener("pointermove", (event) => {
  if (!graph.pointerDown || state.paused) return;
  const dx = event.clientX - graph.lastPointerX;
  const dy = event.clientY - graph.lastPointerY;
  if (Math.abs(dx) + Math.abs(dy) > 3) graph.pointerMoved = true;
  graph.targetYaw += dx * 0.0032;
  graph.targetPitch = clamp(graph.targetPitch + dy * 0.0024, -0.78, 0.52);
  graph.lastPointerX = event.clientX;
  graph.lastPointerY = event.clientY;
});

canvas.addEventListener("pointerup", (event) => {
  if (!graph.pointerMoved) {
    selectNode(graph.pendingNode || nearestNode(event));
  }
  graph.pointerDown = false;
  graph.pendingNode = null;
  canvas.classList.remove("dragging");
  if (canvas.hasPointerCapture(event.pointerId)) {
    canvas.releasePointerCapture(event.pointerId);
  }
});

canvas.addEventListener("pointercancel", (event) => {
  graph.pointerDown = false;
  graph.pendingNode = null;
  canvas.classList.remove("dragging");
  if (canvas.hasPointerCapture(event.pointerId)) {
    canvas.releasePointerCapture(event.pointerId);
  }
});

canvas.addEventListener(
  "wheel",
  (event) => {
    if (state.paused) return;
    event.preventDefault();
    const maxDistance = graph.width < 560 ? 1420 : 1260;
    graph.targetDistance = clamp(graph.targetDistance + event.deltaY * 0.42, 560, maxDistance);
  },
  { passive: false },
);

canvas.addEventListener("keydown", (event) => {
  const step = event.shiftKey ? 0.16 : 0.08;
  if (event.key === "ArrowLeft") {
    graph.targetYaw -= step;
  } else if (event.key === "ArrowRight") {
    graph.targetYaw += step;
  } else if (event.key === "ArrowUp") {
    graph.targetPitch = clamp(graph.targetPitch - step, -0.78, 0.52);
  } else if (event.key === "ArrowDown") {
    graph.targetPitch = clamp(graph.targetPitch + step, -0.78, 0.52);
  } else if (event.key === "+" || event.key === "=") {
    graph.targetDistance = clamp(graph.targetDistance - 80, 560, 1260);
  } else if (event.key === "-" || event.key === "_") {
    graph.targetDistance = clamp(graph.targetDistance + 80, 560, 1260);
  } else if (event.key === "Home") {
    resetGraphView();
  } else {
    return;
  }
  event.preventDefault();
});

document.getElementById("githubSyncButton").addEventListener("click", async (event) => {
  const button = event.currentTarget;
  const error = document.getElementById("syncError");
  const force = document.getElementById("syncForce").checked;
  const postToChat = Boolean(syncPostToChat?.checked);
  error.textContent = "";
  syncResult.innerHTML = "";
  syncRunSummary.textContent = "Running";
  syncRunSummary.className = "status-chip status-standby";
  setBusy(button, true, { idle: "Run learning agent", loading: "Running" });
  try {
    const result = await api("/api/learning-agent/run", {
      method: "POST",
      body: JSON.stringify({
        force,
        post_to_chat: postToChat,
        include_digest_preview: true,
      }),
    });
    const chat = result.notifications?.google_chat || {};
    syncRunSummary.textContent = chat.sent ? "Posted" : result.ingested ? "Updated" : "Checked";
    syncRunSummary.className = "status-chip status-enabled";
    renderLearningAgentRun(result);
    await Promise.all([loadMesh(false), loadGithubSync()]);
  } catch (err) {
    error.textContent = err.message;
    syncRunSummary.textContent = "Failed";
    syncRunSummary.className = "status-chip status-error";
  } finally {
    setBusy(button, false, { idle: "Run learning agent", loading: "Running" });
  }
});

if (googleChatTestButton) {
  googleChatTestButton.addEventListener("click", async (event) => {
    const button = event.currentTarget;
    const error = document.getElementById("syncError");
    error.textContent = "";
    syncResult.innerHTML = "";
    syncRunSummary.textContent = "Testing";
    syncRunSummary.className = "status-chip status-standby";
    setBusy(button, true, { idle: "Send Google Chat test", loading: "Sending" });
    try {
      const result = await api("/api/learning-agent/google-chat/test", {
        method: "POST",
        body: JSON.stringify({}),
      });
      syncRunSummary.textContent = result.sent ? "Test sent" : "Test skipped";
      syncRunSummary.className = result.sent
        ? "status-chip status-enabled"
        : "status-chip status-error";
      const status = result.reason || result.status_category || (result.sent ? "success" : "not sent");
      syncResult.innerHTML = `
        <dl class="result-grid">
          <div><dt>Google Chat</dt><dd>${escapeHtml(status)}</dd></div>
          <div><dt>Status</dt><dd>${escapeHtml(result.status_code || "n/a")}</dd></div>
          <div><dt>Message</dt><dd>${escapeHtml(result.message_name || "n/a")}</dd></div>
          <div><dt>Thread</dt><dd>${escapeHtml(result.thread_name || "n/a")}</dd></div>
        </dl>
      `;
    } catch (err) {
      error.textContent = err.message;
      syncRunSummary.textContent = "Failed";
      syncRunSummary.className = "status-chip status-error";
    } finally {
      setBusy(button, false, { idle: "Send Google Chat test", loading: "Sending" });
    }
  });
}

document.getElementById("obsidianVaultForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const formData = new FormData(form);
  const button = document.getElementById("obsidianVaultSubmit");
  const error = document.getElementById("obsidianSourceError");
  const vaultName = String(formData.get("vaultName") || "").trim();
  error.textContent = "";
  if (!vaultName) {
    error.textContent = "Add a vault name.";
    form.querySelector("[name='vaultName']").focus();
    return;
  }
  obsidianSourceStatus.textContent = "Registering";
  obsidianSourceStatus.className = "status-chip status-standby";
  setBusy(button, true, { idle: "Register vault", loading: "Registering" });
  try {
    await api("/api/obsidian/vaults", {
      method: "POST",
      body: JSON.stringify({
        vault_name: vaultName,
        team_id: String(formData.get("teamId") || "").trim() || null,
        plugin_version: "web",
      }),
    });
    form.reset();
    await Promise.all([loadObsidianSources(), loadMesh(false)]);
  } catch (err) {
    error.textContent = err.message;
    obsidianSourceStatus.textContent = "Failed";
    obsidianSourceStatus.className = "status-chip status-error";
  } finally {
    setBusy(button, false, { idle: "Register vault", loading: "Registering" });
  }
});

document.getElementById("accessSeatForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const formData = new FormData(form);
  const button = document.getElementById("accessSeatSubmit");
  const error = document.getElementById("accessSeatError");
  const status = document.getElementById("accessSeatStatus");
  const reveal = document.getElementById("newSeatToken");
  const name = String(formData.get("name") || "").trim();
  const slug = String(formData.get("slug") || "").trim();
  error.textContent = "";
  reveal.hidden = true;
  reveal.innerHTML = "";
  if (!name || !slug) {
    error.textContent = "Name and seat slug are required.";
    return;
  }
  status.textContent = "Creating";
  status.className = "status-chip status-standby";
  setBusy(button, true, { idle: "Create seat and issue writer token", loading: "Creating" });
  try {
    const response = await api("/api/access/seats", {
      method: "POST",
      body: JSON.stringify({
        name,
        slug,
        email: String(formData.get("email") || "").trim() || null,
        role: String(formData.get("role") || "writer"),
        issue_token: true,
      }),
    });
    reveal.hidden = false;
    reveal.innerHTML = `
      <strong>Seat created</strong>
      <p>Node dataset: ${escapeHtml(response.principal.default_dataset)}</p>
      <p>Copy this writer token now. Citadel stores only the hash.</p>
      <code>${escapeHtml(response.token)}</code>
    `;
    form.reset();
    await loadAccess();
  } catch (err) {
    error.textContent = err.message;
    status.textContent = "Failed";
    status.className = "status-chip status-error";
  } finally {
    setBusy(button, false, { idle: "Create seat and issue writer token", loading: "Creating" });
  }
});

document.getElementById("accessTokenForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const formData = new FormData(form);
  const button = document.getElementById("accessTokenSubmit");
  const error = document.getElementById("accessTokenError");
  const name = String(formData.get("name") || "").trim();
  error.textContent = "";
  newAccessToken.hidden = true;
  newAccessToken.innerHTML = "";
  if (!name) {
    error.textContent = "Add a teammate or agent name.";
    form.querySelector("[name='name']").focus();
    return;
  }
  accessTokenStatus.textContent = "Creating";
  accessTokenStatus.className = "status-chip status-standby";
  setBusy(button, true, { idle: "Create access token", loading: "Creating" });
  try {
    const allowedRaw = String(formData.get("allowedDatasets") || "").trim();
    const allowedDatasets = allowedRaw
      ? allowedRaw.split(",").map((value) => value.trim()).filter(Boolean)
      : null;
    const defaultDataset = String(formData.get("defaultDataset") || "").trim() || null;
    const defaultSession = String(formData.get("defaultSession") || "").trim() || null;
    const response = await api("/api/access/tokens", {
      method: "POST",
      body: JSON.stringify({
        name,
        role: String(formData.get("role") || "reader"),
        kind: String(formData.get("kind") || "service_account"),
        team_id: String(formData.get("teamId") || "").trim() || null,
        default_dataset: defaultDataset,
        default_session: defaultSession,
        allowed_datasets: allowedDatasets,
      }),
    });
    newAccessToken.hidden = false;
    newAccessToken.innerHTML = `
      <strong>Token created</strong>
      <p>Copy this now. Citadel stores only the hash and will not show it again.</p>
      <code>${escapeHtml(response.token)}</code>
    `;
    form.reset();
    await loadAccess();
  } catch (err) {
    error.textContent = err.message;
    accessTokenStatus.textContent = "Failed";
    accessTokenStatus.className = "status-chip status-error";
  } finally {
    setBusy(button, false, { idle: "Create access token", loading: "Creating" });
  }
});

document.getElementById("ingestForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const formData = new FormData(form);
  const button = document.getElementById("ingestSubmit");
  const error = document.getElementById("ingestError");
  const data = String(formData.get("data") || "").trim();
  const tags = String(formData.get("tags") || "")
    .split(",")
    .map((tag) => tag.trim())
    .filter(Boolean);
  error.textContent = "";
  form.querySelector("[name='data']").setAttribute("aria-invalid", "false");
  if (!data) {
    error.textContent = "Add note text before saving.";
    form.querySelector("[name='data']").setAttribute("aria-invalid", "true");
    form.querySelector("[name='data']").focus();
    return;
  }
  setBusy(button, true, { idle: "Save to vault", loading: "Indexing" });
  try {
    await api("/ingest", {
      method: "POST",
      body: JSON.stringify({
        data,
        dataset: String(formData.get("dataset") || "").trim() || null,
        tags,
      }),
    });
    form.querySelector("[name='data']").value = "";
    await loadMesh(false);
  } catch (err) {
    error.textContent = err.message;
  } finally {
    setBusy(button, false, { idle: "Save to vault", loading: "Indexing" });
  }
});

document.getElementById("searchForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const formData = new FormData(form);
  const button = document.getElementById("searchSubmit");
  const error = document.getElementById("searchError");
  const results = document.getElementById("searchResults");
  const queryInput = form.querySelector("[name='query']");
  const topKInput = form.querySelector("[name='topK']");
  const query = String(formData.get("query") || "").trim();
  const topK = Number.parseInt(String(formData.get("topK") || "10"), 10) || 10;
  error.textContent = "";
  results.innerHTML = "";
  queryInput.setAttribute("aria-invalid", "false");
  topKInput.setAttribute("aria-invalid", "false");
  if (!query) {
    error.textContent = "Enter a search query.";
    queryInput.setAttribute("aria-invalid", "true");
    queryInput.focus();
    setSearchStatus("Idle");
    return;
  }
  if (topK < 1 || topK > 100) {
    error.textContent = "Top K must be between 1 and 100.";
    topKInput.setAttribute("aria-invalid", "true");
    topKInput.focus();
    setSearchStatus("Check limit", "status-error");
    return;
  }
  setBusy(button, true, { idle: "Search vault", loading: "Searching" });
  setSearchStatus("Searching", "status-standby");
  results.append(searchLoadingState());
  try {
    const response = await api("/search", {
      method: "POST",
      body: JSON.stringify({
        query,
        dataset: String(formData.get("dataset") || "").trim() || null,
        top_k: topK,
      }),
    });
    const returned = response.results || [];
    setSearchStatus(returned.length ? `${returned.length} result${returned.length === 1 ? "" : "s"}` : "No results", returned.length ? "status-enabled" : "status-standby");
    renderSearchResults(returned, response);
    await loadMesh(false);
  } catch (err) {
    results.innerHTML = "";
    results.append(searchErrorState(err.message));
    const retry = results.querySelector("[data-search-retry]");
    if (retry) retry.addEventListener("click", () => form.requestSubmit());
    setSearchStatus("Failed", "status-error");
  } finally {
    setBusy(button, false, { idle: "Search vault", loading: "Searching" });
  }
});

document.getElementById("feedbackForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const formData = new FormData(form);
  const button = document.getElementById("feedbackSubmit");
  const error = document.getElementById("feedbackError");
  const qaInput = form.querySelector("[name='qaId']");
  const qaId = String(formData.get("qaId") || "").trim();
  const scoreValue = String(formData.get("score") || "").trim();
  error.textContent = "";
  feedbackResult.innerHTML = "";
  qaInput.setAttribute("aria-invalid", "false");
  if (!qaId) {
    error.textContent = "Add the QA ID before recording feedback.";
    qaInput.setAttribute("aria-invalid", "true");
    qaInput.focus();
    return;
  }
  feedbackStatus.textContent = "Recording";
  feedbackStatus.className = "status-chip status-standby";
  setBusy(button, true, { idle: "Record feedback", loading: "Recording" });
  try {
    const response = await api("/feedback", {
      method: "POST",
      body: JSON.stringify({
        qa_id: qaId,
        score: scoreValue === "" ? null : Number.parseInt(scoreValue, 10),
        text: String(formData.get("text") || "").trim() || null,
        dataset: String(formData.get("dataset") || "").trim() || null,
        session_id: String(formData.get("sessionId") || "").trim() || null,
      }),
    });
    feedbackStatus.textContent = response.recorded ? "Recorded" : "Skipped";
    feedbackStatus.className = `status-chip ${response.recorded ? "status-enabled" : "status-standby"}`;
    feedbackResult.innerHTML = `
      <dl class="result-grid">
        <div><dt>Recorded</dt><dd>${response.recorded ? "Yes" : "No"}</dd></div>
        <div><dt>Improved</dt><dd>${response.improved ? "Yes" : "No"}</dd></div>
      </dl>
    `;
    await loadMesh(false);
  } catch (err) {
    error.textContent = err.message;
    feedbackStatus.textContent = "Failed";
    feedbackStatus.className = "status-chip status-error";
  } finally {
    setBusy(button, false, { idle: "Record feedback", loading: "Recording" });
  }
});

document.getElementById("upgradeButton").addEventListener("click", async (event) => {
  const button = event.currentTarget;
  const error = document.getElementById("upgradeError");
  error.textContent = "";
  upgradeStatus.textContent = "Running";
  upgradeStatus.className = "status-chip status-standby";
  setBusy(button, true, { idle: "Run improvement", loading: "Improving" });
  try {
    await api("/api/self-upgrade", {
      method: "POST",
      body: JSON.stringify({}),
    });
    upgradeStatus.textContent = "Complete";
    upgradeStatus.className = "status-chip status-enabled";
    await loadMesh(false);
  } catch (err) {
    error.textContent = err.message;
    upgradeStatus.textContent = "Failed";
    upgradeStatus.className = "status-chip status-error";
  } finally {
    setBusy(button, false, { idle: "Run improvement", loading: "Improving" });
  }
});

function renderSearchResults(results, response = {}) {
  const container = document.getElementById("searchResults");
  container.innerHTML = "";
  if (!results.length) {
    container.append(searchEmptyState(response));
    return;
  }
  results.slice(0, 8).forEach((result, index) => {
    const item = document.createElement("article");
    item.className = "result-item citation-card";
    const feedbackId = findFeedbackId(result);
    const envelope = resultEnvelope(result);
    const provenance = resultProvenance(result);
    const metaRows = resultMetaRows(result);
    const documentEndpoint = safeDocumentEndpoint(result);
    const sourceUrl = safeExternalUrl(provenance.source_url);
    const drilldown = envelope.retrieval?.document_drilldown_available === true;
    const rank = envelope.rank || index + 1;
    item.innerHTML = `
      <div class="result-header">
        <div>
          <div class="result-meta">Citation ${escapeHtml(rank)} · ${escapeHtml(envelope.dataset || result?.dataset || "default dataset")}</div>
          <strong>${escapeHtml(resultTitle(result, index))}</strong>
        </div>
        <div class="result-trust-chips" aria-label="Retrieval status">
          <span class="status-chip status-standby">Untrusted context</span>
          <span class="status-chip ${drilldown ? "status-enabled" : ""}">${drilldown ? "Document" : "Chunk"}</span>
        </div>
      </div>
      <p class="result-summary">${escapeHtml(resultBodyText(result))}</p>
      ${
        metaRows.length
          ? `<dl class="result-provenance">${metaRows
              .map(
                ([label, value]) => `
                  <div>
                    <dt>${escapeHtml(label)}</dt>
                    <dd>${escapeHtml(value)}</dd>
                  </div>
                `
              )
              .join("")}</dl>`
          : ""
      }
      <div class="result-retrieval">
        <span class="citation-required">Citation required before acting</span>
        ${
          sourceUrl
            ? `<a class="result-source-url" href="${escapeHtml(sourceUrl)}" target="_blank" rel="noreferrer">${escapeHtml(sourceUrl)}</a>`
            : provenance.source_url
              ? `<span class="result-source-url">${escapeHtml(provenance.source_url)}</span>`
              : ""
        }
      </div>
      <details class="result-raw">
        <summary>Show raw result</summary>
        <pre class="result-body">${escapeHtml(JSON.stringify(result, null, 2))}</pre>
      </details>
    `;
    const actions = document.createElement("div");
    actions.className = "result-actions";
    const previewPanel = document.createElement("div");
    previewPanel.className = "result-document-preview";
    previewPanel.hidden = true;
    if (documentEndpoint) {
      const action = document.createElement("button");
      action.className = "secondary-button result-document-link";
      action.type = "button";
      action.textContent = "Preview source";
      action.addEventListener("click", () => loadDocumentPreview(action, documentEndpoint, previewPanel));
      actions.append(action);
    }
    if (feedbackId) {
      const action = document.createElement("button");
      action.className = "secondary-button result-feedback-button";
      action.type = "button";
      action.textContent = "Use for feedback";
      action.addEventListener("click", () => fillFeedbackForm(feedbackId));
      actions.append(action);
    }
    if (actions.children.length) {
      item.append(actions);
    }
    item.append(previewPanel);
    container.append(item);
  });
}

window.addEventListener("resize", () => {
  resizeCanvas();
  if (state.graphMode === "knowledge") {
    buildGraphScene();
    return;
  }
  if (state.snapshot) mergeGraph(state.snapshot);
});

reducedMotionQuery.addEventListener("change", (event) => {
  graph.reducedMotion = event.matches;
});

initializeGraph();
resizeCanvas();
initializeNavigation();
loadSession().then(() => {
  setPage(initialPage());
  loadMesh();
  loadGithubSync();
  loadObsidianSources();
  loadConflicts();
  if (canUse("admin")) {
    loadAccess();
    loadSettings();
  }
  connectEvents();
  animateGraph();
});
