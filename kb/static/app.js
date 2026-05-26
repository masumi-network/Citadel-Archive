import * as THREE from "./vendor/three.module.min.js";

const state = {
  snapshot: null,
  nodes: new Map(),
  edges: [],
  selectedId: null,
  paused: false,
  eventSource: null,
  role: null,
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
const feedbackStatus = document.getElementById("feedbackStatus");
const feedbackResult = document.getElementById("feedbackResult");
const accessTokenStatus = document.getElementById("accessTokenStatus");
const accessPrincipalList = document.getElementById("accessPrincipalList");
const accessTokenList = document.getElementById("accessTokenList");
const accessAuditList = document.getElementById("accessAuditList");
const newAccessToken = document.getElementById("newAccessToken");
const pageButtons = Array.from(document.querySelectorAll("[data-page-target]"));
const pages = Array.from(document.querySelectorAll("[data-page]"));
const roleOrder = { reader: 1, writer: 2, admin: 3 };
const reducedMotionQuery = window.matchMedia("(prefers-reduced-motion: reduce)");

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
  nodeLabelSprites: new Map(),
  width: 1,
  height: 1,
  yaw: -0.42,
  pitch: -0.24,
  distance: 820,
  targetYaw: -0.42,
  targetPitch: -0.24,
  targetDistance: 820,
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
  dataset: "#58c7a9",
  document: "#e0b45b",
  tag: "#b5bdc9",
  index: "#8bc7ff",
  query: "#f0c75e",
  feedback: "#ff837a",
  upgrade: "#69da93",
  source: "#8bc7ff",
  repository: "#b59cff",
};

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
    ? `${label} workspace access`
    : "No workspace session";
  accessMode.textContent = label;
  accessMode.className = sessionRole.className;

  document.querySelectorAll("[data-min-role]").forEach((element) => {
    const allowed = canUse(element.dataset.minRole);
    if (element.classList.contains("nav-link")) {
      element.disabled = !allowed;
      return;
    }
    if (element.matches("button, input, textarea, select")) {
      element.disabled = !allowed;
    }
  });
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
  return pages.some((page) => page.dataset.page === hash) ? hash : "overview";
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
  buildGraphScene();
  if (!graph.viewInitialized) {
    resetGraphView();
    graph.viewInitialized = true;
  }
  renderSnapshot(snapshot);
  selectNode(state.nodes.get(state.selectedId) || null);
}

function renderSnapshot(snapshot) {
  meshAlert.hidden = true;
  canvasEmpty.hidden = snapshot.nodes.length > 4;
  graphMeta.textContent = `${snapshot.default_dataset} - rev ${snapshot.revision} - ${formatDate(snapshot.generated_at)}`;
  document.getElementById("statNodes").textContent = snapshot.stats.nodes;
  document.getElementById("statEdges").textContent = snapshot.stats.edges;
  document.getElementById("statDocuments").textContent = snapshot.stats.documents;
  document.getElementById("statSearches").textContent = snapshot.stats.searches;
  document.getElementById("statFeedback").textContent = snapshot.stats.feedback;
  document.getElementById("statUpgrades").textContent = snapshot.stats.upgrades;
  document.getElementById("statErrors").textContent = snapshot.stats.errors;
  eventCount.textContent = String(snapshot.events.length);

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

  eventList.innerHTML = "";
  snapshot.events.slice(0, 28).forEach((event) => {
    const item = document.createElement("li");
    item.className = "event-item";
    item.innerHTML = `
      <div class="event-row">
        <span class="event-type">${escapeHtml(event.type)}</span>
        <time class="event-time">${escapeHtml(formatDate(event.created_at))}</time>
      </div>
      <div class="event-message">${escapeHtml(event.message)}</div>
      <div class="event-details">${escapeHtml(formatDetails(event.details))}</div>
    `;
    eventList.append(item);
  });

  if (!snapshot.events.length) {
    const empty = document.createElement("li");
    empty.className = "event-item empty-event";
    empty.innerHTML = "<strong>No events yet</strong><p>Run a sync or ingest a memory.</p>";
    eventList.append(empty);
  }
}

function emptyState(title, body) {
  const item = document.createElement("div");
  item.className = "empty-state";
  item.innerHTML = `<strong>${escapeHtml(title)}</strong><p>${escapeHtml(body)}</p>`;
  return item;
}

function formatDetails(details = {}) {
  return Object.entries(details)
    .filter(([, value]) => value !== null && value !== undefined && value !== "")
    .map(([key, value]) => `${key}: ${Array.isArray(value) ? value.join(", ") : value}`)
    .join(" | ");
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

function initializeGraph() {
  graph.scene = new THREE.Scene();
  graph.scene.background = new THREE.Color(0x10141a);

  graph.camera = new THREE.PerspectiveCamera(42, 1, 1, 2600);
  graph.camera.position.set(0, 0, graph.distance);

  graph.renderer = new THREE.WebGLRenderer({
    canvas,
    antialias: true,
    alpha: false,
    preserveDrawingBuffer: true,
    powerPreference: "high-performance",
  });
  graph.renderer.outputColorSpace = THREE.SRGBColorSpace;
  graph.renderer.setClearColor(0x10141a, 1);

  graph.root = new THREE.Group();
  graph.root.rotation.order = "YXZ";
  graph.scene.add(graph.root);

  graph.scene.add(new THREE.AmbientLight(0xffffff, 0.62));
  const keyLight = new THREE.DirectionalLight(0xddefff, 1.7);
  keyLight.position.set(360, 420, 520);
  graph.scene.add(keyLight);
  const fillLight = new THREE.PointLight(0x58c7a9, 1.15, 1200);
  fillLight.position.set(-360, -180, 360);
  graph.scene.add(fillLight);

  const grid = new THREE.GridHelper(960, 18, 0x58c7a9, 0x46505e);
  grid.position.y = -230;
  grid.position.z = -20;
  for (const material of Array.isArray(grid.material) ? grid.material : [grid.material]) {
    material.transparent = true;
    material.opacity = 0.18;
    material.depthWrite = false;
  }
  graph.root.add(grid);

  graph.edgeGroup = new THREE.Group();
  graph.nodeGroup = new THREE.Group();
  graph.labelGroup = new THREE.Group();
  graph.root.add(graph.edgeGroup, graph.nodeGroup, graph.labelGroup);
}

function layoutNodes(nodes) {
  const groups = new Map();
  for (const node of nodes) {
    const type = node.type || "other";
    groups.set(type, [...(groups.get(type) || []), node]);
  }

  const positions = new Map();
  const density = clamp(Math.sqrt(Math.max(nodes.length, 8) / 18), 0.92, 1.55);
  const layouts = {
    dataset: { radius: 0, y: 0, z: 0, zScale: 0, start: 0 },
    index: { radius: 175, y: -24, z: 0, zScale: 58, start: -Math.PI / 2 },
    source: { radius: 265, y: -120, z: 10, zScale: 86, start: -0.2 },
    repository: { radius: 355, y: -156, z: 18, zScale: 126, start: 0.1 },
    document: { radius: 340, y: 104, z: -10, zScale: 118, start: Math.PI * 0.62 },
    tag: { radius: 450, y: 148, z: -22, zScale: 142, start: Math.PI * 0.86 },
    query: { radius: 382, y: 14, z: 0, zScale: 126, start: -0.05 },
    feedback: { radius: 398, y: 124, z: 14, zScale: 104, start: Math.PI * 0.16 },
    upgrade: { radius: 288, y: 68, z: 16, zScale: 78, start: -Math.PI * 0.45 },
    other: { radius: 430, y: 0, z: 0, zScale: 130, start: Math.PI * 0.35 },
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

    const radius = layout.radius * density;
    const step = (Math.PI * 2) / Math.max(sorted.length, 1);
    sorted.forEach((node, index) => {
      const seed = hashUnit(node.id);
      const angle = layout.start + step * index + (seed - 0.5) * 0.22;
      const lane = ((index % 3) - 1) * 14;
      positions.set(node.id, {
        x: Math.cos(angle) * (radius + lane),
        y: layout.y + Math.sin(angle) * radius * 0.38,
        z: layout.z + Math.sin(angle * 1.7 + seed * Math.PI) * layout.zScale,
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
  graph.nodeLabelSprites.clear();

  const edgePositions = [];
  for (const edge of state.edges) {
    const source = state.nodes.get(edge.source);
    const target = state.nodes.get(edge.target);
    if (!source || !target) continue;
    edgePositions.push(source.x, source.y, source.z, target.x, target.y, target.z);
  }

  if (edgePositions.length) {
    const edgeGeometry = new THREE.BufferGeometry();
    edgeGeometry.setAttribute("position", new THREE.Float32BufferAttribute(edgePositions, 3));
    const edgeMaterial = new THREE.LineBasicMaterial({
      color: 0x9aa5b5,
      transparent: true,
      opacity: 0.34,
      depthWrite: false,
    });
    graph.edgeGroup.add(new THREE.LineSegments(edgeGeometry, edgeMaterial));
  }

  const nodes = Array.from(state.nodes.values()).sort(compareNodes);
  nodes.forEach((node) => {
    const radius = nodeRadius(node);
    const color = new THREE.Color(colors[node.type] || "#b5bdc9");
    const geometry = nodeGeometry(node, radius);
    const material = new THREE.MeshStandardMaterial({
      color,
      emissive: color,
      emissiveIntensity: 0.08,
      roughness: 0.56,
      metalness: node.type === "index" ? 0.28 : 0.14,
    });
    const mesh = new THREE.Mesh(geometry, material);
    mesh.position.set(node.x, node.y, node.z);
    mesh.userData.nodeId = node.id;
    graph.nodeMeshes.set(node.id, mesh);
    graph.nodeGroup.add(mesh);

    const label = createLabelSprite(node, radius);
    label.position.set(node.x, node.y + radius + 22, node.z + 4);
    graph.nodeLabelSprites.set(node.id, label);
    graph.labelGroup.add(label);
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

function nodeGeometry(node, radius) {
  if (node.type === "index") {
    return new THREE.BoxGeometry(radius * 1.45, radius * 1.45, radius * 1.45);
  }
  if (node.type === "source" || node.type === "repository") {
    return new THREE.IcosahedronGeometry(radius, 1);
  }
  return new THREE.SphereGeometry(radius, 28, 18);
}

function nodeRadius(node) {
  const base = Number(node.size || 24);
  if (node.type === "dataset") return clamp(base * 0.48, 18, 30);
  if (node.type === "index") return clamp(base * 0.42, 13, 22);
  return clamp(base * 0.46, 9, 26);
}

function createLabelSprite(node, radius) {
  const label = truncate(String(node.label || node.id), node.type === "repository" ? 18 : 24);
  const labelCanvas = document.createElement("canvas");
  const context = labelCanvas.getContext("2d");
  const scale = 2;
  context.font = "600 26px Inter, system-ui, sans-serif";
  const textWidth = Math.min(context.measureText(label).width, 340);
  const width = Math.ceil(textWidth + 54);
  const height = 58;
  labelCanvas.width = width * scale;
  labelCanvas.height = height * scale;
  context.scale(scale, scale);
  context.font = "600 26px Inter, system-ui, sans-serif";
  context.textBaseline = "middle";

  roundedRect(context, 0.5, 0.5, width - 1, height - 1, 8);
  context.fillStyle = "rgba(13, 16, 21, 0.82)";
  context.fill();
  context.strokeStyle = "rgba(181, 189, 201, 0.24)";
  context.stroke();

  context.fillStyle = colors[node.type] || "#b5bdc9";
  context.fillRect(14, 17, 6, 24);
  context.fillStyle = "#f2f4f7";
  context.fillText(label, 30, height / 2, width - 42);

  const texture = new THREE.CanvasTexture(labelCanvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.minFilter = THREE.LinearFilter;
  texture.magFilter = THREE.LinearFilter;
  const material = new THREE.SpriteMaterial({
    map: texture,
    transparent: true,
    opacity: 0.84,
    depthWrite: false,
  });
  const sprite = new THREE.Sprite(material);
  const labelScale = clamp(radius * 2.8, 38, 58);
  sprite.scale.set((width / height) * labelScale, labelScale, 1);
  return sprite;
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
    mesh.scale.setScalar(selected ? 1.18 : 1);
    mesh.material.emissiveIntensity = selected ? 0.34 : 0.08;
  }
  for (const [id, sprite] of graph.nodeLabelSprites.entries()) {
    sprite.material.opacity = id === state.selectedId ? 1 : 0.82;
  }
  renderGraphScene();
}

function renderGraphScene() {
  if (!graph.renderer || !graph.camera || !graph.root) return;
  const damping = graph.reducedMotion ? 1 : 0.14;
  graph.yaw += (graph.targetYaw - graph.yaw) * damping;
  graph.pitch += (graph.targetPitch - graph.pitch) * damping;
  graph.distance += (graph.targetDistance - graph.distance) * damping;
  graph.root.rotation.set(graph.pitch, graph.yaw, 0);
  graph.camera.position.set(0, 0, graph.distance);
  graph.camera.lookAt(0, 0, 0);
  graph.renderer.render(graph.scene, graph.camera);
}

function animateGraph() {
  renderGraphScene();
  graph.animationFrame = window.requestAnimationFrame(animateGraph);
}

function resetGraphView() {
  graph.targetYaw = -0.42;
  graph.targetPitch = graph.width < 560 ? -0.16 : -0.24;
  graph.targetDistance = defaultGraphDistance();
  graph.yaw = graph.targetYaw;
  graph.pitch = graph.targetPitch;
  graph.distance = graph.targetDistance;
  renderGraphScene();
}

function fitGraphDistance() {
  const min = graph.width < 560 ? 640 : 560;
  const max = graph.width < 560 ? 1420 : 1260;
  graph.targetDistance = clamp(graph.targetDistance, min, max);
  graph.distance = clamp(graph.distance, min, max);
}

function defaultGraphDistance() {
  const nodeCount = Math.max(state.nodes.size, 5);
  const density = clamp(Math.sqrt(nodeCount / 16), 1, 1.42);
  const mobile = graph.width < 560 ? 1.18 : 1;
  return clamp(760 * density * mobile, 680, graph.width < 560 ? 1360 : 1180);
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
  return hit ? state.nodes.get(hit.userData.nodeId) || null : null;
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
    selectedNode.textContent = "Select a node to inspect it.";
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
    meshAlertText.textContent = error.message || "Try refreshing the dashboard.";
    console.error(error);
  }
}

async function loadGithubSync() {
  try {
    const status = await api("/api/github-sync");
    githubSyncStatus.textContent = status.last_checked_at ? "Tracked" : "Ready";
    githubSyncStatus.className = `status-chip ${status.last_checked_at ? "status-enabled" : "status-standby"}`;
    syncLastChecked.textContent = formatDate(status.last_checked_at);
    syncTrackedRepos.textContent = status.tracked_repositories;
    githubSourceLink.href = status.source_url;
    githubSourceLink.textContent = status.source_url.replace("https://", "");
  } catch (error) {
    githubSyncStatus.textContent = "Error";
    githubSyncStatus.className = "status-chip status-error";
    syncResult.innerHTML = "";
    syncResult.append(emptyState("Could not load sync status", error.message));
  }
}

async function loadAccess() {
  if (!canUse("admin")) return;
  accessTokenStatus.textContent = "Loading";
  accessTokenStatus.className = "status-chip status-standby";
  try {
    const snapshot = await api("/api/access");
    renderAccess(snapshot);
    accessTokenStatus.textContent = "Ready";
    accessTokenStatus.className = "status-chip status-enabled";
  } catch (error) {
    accessTokenStatus.textContent = "Error";
    accessTokenStatus.className = "status-chip status-error";
    accessPrincipalList.innerHTML = "";
    accessPrincipalList.append(emptyState("Could not load access", error.message));
  }
}

function renderAccess(snapshot) {
  accessPrincipalList.innerHTML = "";
  accessTokenList.innerHTML = "";
  accessAuditList.innerHTML = "";

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
    const item = document.createElement("li");
    item.className = "event-item";
    item.innerHTML = `
      <div class="event-row">
        <span class="event-type">${escapeHtml(event.action)}</span>
        <time class="event-time">${escapeHtml(formatDate(event.created_at))}</time>
      </div>
      <div class="event-message">${escapeHtml(event.actor_name || "System")}</div>
      <div class="event-details">${escapeHtml(formatDetails(event.detail || {}))}</div>
    `;
    accessAuditList.append(item);
  });
  if (!events.length) {
    const empty = document.createElement("li");
    empty.className = "event-item empty-event";
    empty.innerHTML = "<strong>No audit events</strong><p>Create or revoke a token to start the trail.</p>";
    accessAuditList.append(empty);
  }
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
  error.textContent = "";
  syncResult.innerHTML = "";
  syncRunSummary.textContent = "Running";
  syncRunSummary.className = "status-chip status-standby";
  setBusy(button, true, { idle: "Run GitHub sync", loading: "Syncing" });
  try {
    const result = await api("/api/github-sync/run", {
      method: "POST",
      body: JSON.stringify({ force }),
    });
    syncRunSummary.textContent = result.ingested ? "Updated" : "Checked";
    syncRunSummary.className = "status-chip status-enabled";
    syncResult.innerHTML = `
      <dl class="result-grid">
        <div><dt>Repos scanned</dt><dd>${escapeHtml(result.repos_scanned)}</dd></div>
        <div><dt>Changed</dt><dd>${escapeHtml(result.changed_count)}</dd></div>
        <div><dt>Events</dt><dd>${escapeHtml(result.event_count)}</dd></div>
        <div><dt>Improved</dt><dd>${result.improved ? "Yes" : "No"}</dd></div>
      </dl>
    `;
    await Promise.all([loadMesh(false), loadGithubSync()]);
  } catch (err) {
    error.textContent = err.message;
    syncRunSummary.textContent = "Failed";
    syncRunSummary.className = "status-chip status-error";
  } finally {
    setBusy(button, false, { idle: "Run GitHub sync", loading: "Syncing" });
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
    const response = await api("/api/access/tokens", {
      method: "POST",
      body: JSON.stringify({
        name,
        role: String(formData.get("role") || "reader"),
        kind: String(formData.get("kind") || "service_account"),
        team_id: String(formData.get("teamId") || "").trim() || null,
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
    error.textContent = "Add memory text before ingesting.";
    form.querySelector("[name='data']").setAttribute("aria-invalid", "true");
    form.querySelector("[name='data']").focus();
    return;
  }
  setBusy(button, true, { idle: "Ingest memory", loading: "Indexing" });
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
    setBusy(button, false, { idle: "Ingest memory", loading: "Indexing" });
  }
});

document.getElementById("searchForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const formData = new FormData(form);
  const button = document.getElementById("searchSubmit");
  const error = document.getElementById("searchError");
  const results = document.getElementById("searchResults");
  const query = String(formData.get("query") || "").trim();
  error.textContent = "";
  results.innerHTML = "";
  if (!query) {
    error.textContent = "Enter a search query.";
    form.querySelector("[name='query']").focus();
    return;
  }
  setBusy(button, true, { idle: "Search mesh", loading: "Searching" });
  results.append(emptyState("Searching", "Checking graph and vector memory."));
  try {
    const response = await api("/search", {
      method: "POST",
      body: JSON.stringify({
        query,
        dataset: String(formData.get("dataset") || "").trim() || null,
        top_k: Number.parseInt(String(formData.get("topK") || "10"), 10) || 10,
      }),
    });
    renderSearchResults(response.results || []);
    await loadMesh(false);
  } catch (err) {
    results.innerHTML = "";
    error.textContent = err.message;
  } finally {
    setBusy(button, false, { idle: "Search mesh", loading: "Searching" });
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

function renderSearchResults(results) {
  const container = document.getElementById("searchResults");
  container.innerHTML = "";
  if (!results.length) {
    container.append(emptyState("No results", "Try a broader query or ingest more source material."));
    return;
  }
  results.slice(0, 6).forEach((result, index) => {
    const item = document.createElement("div");
    item.className = "result-item";
    const feedbackId = findFeedbackId(result);
    item.innerHTML = `
      <div class="result-meta">Result ${index + 1}</div>
      <pre class="result-body">${escapeHtml(JSON.stringify(result, null, 2))}</pre>
    `;
    if (feedbackId) {
      const action = document.createElement("button");
      action.className = "secondary-button result-feedback-button";
      action.type = "button";
      action.textContent = "Use for feedback";
      action.addEventListener("click", () => fillFeedbackForm(feedbackId));
      item.append(action);
    }
    container.append(item);
  });
}

window.addEventListener("resize", () => {
  resizeCanvas();
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
  connectEvents();
  animateGraph();
});
