const state = {
  apiBaseUrl: "",
  farms: [],
  selectedFarmId: null,
  sessionOffset: 0,
  sessionLimit: 8,
  sessionTotal: 0,
  currentSessions: [],
  sessionImages: new Map(),
  ptzPreviewObjectUrl: null,
  refreshTimer: null,
};

const elements = {
  apiState: document.querySelector("#apiState"),
  refreshButton: document.querySelector("#refreshButton"),
  settingsButton: document.querySelector("#settingsButton"),
  settingsDialog: document.querySelector("#settingsDialog"),
  settingsForm: document.querySelector("#settingsForm"),
  apiUrl: document.querySelector("#apiUrl"),
  farmGrid: document.querySelector("#farmGrid"),
  onlineCount: document.querySelector("#onlineCount"),
  serviceCount: document.querySelector("#serviceCount"),
  pendingCount: document.querySelector("#pendingCount"),
  lastUpdated: document.querySelector("#lastUpdated"),
  workspace: document.querySelector("#workspace"),
  gallerySection: document.querySelector("#gallerySection"),
  logsSection: document.querySelector("#logsSection"),
  farmSelect: document.querySelector("#farmSelect"),
  selectedFarmState: document.querySelector("#selectedFarmState"),
  ptzState: document.querySelector("#ptzState"),
  ptzCamera: document.querySelector("#ptzCamera"),
  ptzSpeed: document.querySelector("#ptzSpeed"),
  ptzPreview: document.querySelector("#ptzPreview"),
  ptzPreviewPlaceholder: document.querySelector("#ptzPreviewPlaceholder"),
  ptzPreviewTime: document.querySelector("#ptzPreviewTime"),
  refreshPtzPreview: document.querySelector("#refreshPtzPreview"),
  imageType: document.querySelector("#imageType"),
  imageCamera: document.querySelector("#imageCamera"),
  imageGrid: document.querySelector("#imageGrid"),
  imagePage: document.querySelector("#imagePage"),
  previousImages: document.querySelector("#previousImages"),
  nextImages: document.querySelector("#nextImages"),
  loadImagesButton: document.querySelector("#loadImagesButton"),
  logUnit: document.querySelector("#logUnit"),
  loadLogsButton: document.querySelector("#loadLogsButton"),
  logOutput: document.querySelector("#logOutput"),
  imageDialog: document.querySelector("#imageDialog"),
  closeImageDialog: document.querySelector("#closeImageDialog"),
  fullImage: document.querySelector("#fullImage"),
  fullImageTitle: document.querySelector("#fullImageTitle"),
  fullImageMeta: document.querySelector("#fullImageMeta"),
  downloadImage: document.querySelector("#downloadImage"),
  toastRegion: document.querySelector("#toastRegion"),
};

function apiUrl(path) {
  return `${state.apiBaseUrl}${path}`;
}

async function fetchApi(path, options = {}) {
  if (!state.apiBaseUrl) throw new Error("제어 API 주소가 설정되지 않았습니다.");
  const response = await fetch(apiUrl(path), {
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
  });
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const payload = await response.json();
      detail = payload.detail || detail;
    } catch (_) { /* response was not JSON */ }
    throw new Error(detail);
  }
  return response.json();
}

async function fetchBlob(path) {
  if (!state.apiBaseUrl) throw new Error("제어 API 주소가 설정되지 않았습니다.");
  const response = await fetch(apiUrl(path), { cache: "no-store" });
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const payload = await response.json();
      detail = payload.detail || detail;
    } catch (_) { /* response was not JSON */ }
    throw new Error(detail);
  }
  return response.blob();
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function bytes(value) {
  if (!Number.isFinite(value)) return "—";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let amount = value;
  let unit = 0;
  while (amount >= 1024 && unit < units.length - 1) {
    amount /= 1024;
    unit += 1;
  }
  return `${amount.toFixed(unit < 2 ? 0 : 1)} ${units[unit]}`;
}

function dateTime(value, fromEpoch = false) {
  if (!value) return "—";
  const date = new Date(fromEpoch ? value * 1000 : value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("ko-KR", {
    month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit",
  }).format(date);
}

function duration(value) {
  if (!Number.isFinite(value)) return "진행 중";
  const seconds = Math.max(0, Math.round(value));
  if (seconds < 60) return `${seconds}초`;
  const minutes = Math.floor(seconds / 60);
  const remainder = seconds % 60;
  if (minutes < 60) return remainder ? `${minutes}분 ${remainder}초` : `${minutes}분`;
  const hours = Math.floor(minutes / 60);
  return `${hours}시간 ${minutes % 60}분`;
}

function toast(message, type = "success") {
  const node = document.createElement("div");
  node.className = `toast ${type}`;
  node.textContent = message;
  elements.toastRegion.append(node);
  window.setTimeout(() => node.remove(), 5200);
}

function setConnection(connected, label) {
  elements.apiState.classList.toggle("online", connected);
  elements.apiState.classList.toggle("offline", !connected);
  elements.apiState.lastChild.textContent = ` ${label}`;
}

function renderSummary() {
  const online = state.farms.filter((farm) => farm.online).length;
  const services = state.farms.reduce(
    (sum, farm) => sum + Object.values(farm.services || {}).filter((value) => value === "active").length,
    0,
  );
  const pending = state.farms.reduce(
    (sum, farm) => sum + (farm.report?.sessions?.pending_upload || 0),
    0,
  );
  elements.onlineCount.textContent = `${online}/${state.farms.length || 5}`;
  elements.serviceCount.textContent = `${services}/${(state.farms.length || 5) * 3}`;
  elements.pendingCount.textContent = String(pending);
}

function renderFarms() {
  if (!state.farms.length) {
    elements.farmGrid.innerHTML = '<div class="empty-card">조회할 농가가 없습니다.</div>';
    return;
  }
  elements.farmGrid.innerHTML = state.farms.map((farm) => {
    const report = farm.report || {};
    const disk = report.disk || {};
    const sessions = report.sessions || {};
    const services = Object.values(farm.services || {});
    const selected = farm.id === state.selectedFarmId ? "selected" : "";
    return `
      <article class="farm-card ${farm.online ? "online" : "offline"} ${selected}" data-farm-id="${escapeHtml(farm.id)}" tabindex="0">
        <div class="farm-name-row"><h3>${escapeHtml(farm.name)}</h3><span class="farm-status-dot"></span></div>
        <div class="farm-metric">
          <span>${farm.online ? "디스크 여유 공간" : "연결 상태"}</span>
          <strong>${farm.online ? bytes(disk.free_bytes) : "OFFLINE"}</strong>
        </div>
        <div class="farm-metric"><span>업로드 완료 / 대기</span><strong>${sessions.uploaded ?? "—"} / ${sessions.pending_upload ?? "—"}</strong></div>
        <div class="service-dots" title="수집 · 작물촬영 · 업로드">${[0, 1, 2].map((i) => `<i class="${services[i] === "active" ? "active" : ""}"></i>`).join("")}</div>
      </article>`;
  }).join("");

  elements.farmGrid.querySelectorAll(".farm-card").forEach((card) => {
    const select = () => selectFarm(card.dataset.farmId);
    card.addEventListener("click", select);
    card.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") select();
    });
  });
}

function updateFarmSelect() {
  elements.farmSelect.innerHTML = state.farms
    .map((farm) => `<option value="${escapeHtml(farm.id)}">${escapeHtml(farm.name)}</option>`)
    .join("");
  elements.farmSelect.value = state.selectedFarmId || "";
}

function selectFarm(farmId) {
  state.selectedFarmId = farmId;
  state.sessionOffset = 0;
  state.sessionImages.clear();
  const farm = state.farms.find((item) => item.id === farmId);
  if (!farm) return;
  elements.workspace.classList.remove("hidden");
  elements.gallerySection.classList.remove("hidden");
  elements.logsSection.classList.remove("hidden");
  elements.farmSelect.value = farmId;
  elements.selectedFarmState.textContent = farm.online ? "온라인" : "오프라인";
  elements.selectedFarmState.className = `mini-state ${farm.online ? "ok" : "error"}`;
  elements.ptzState.textContent = farm.ptz_enabled ? "사용 가능" : "설정 필요";
  elements.ptzState.className = `mini-state ${farm.ptz_enabled ? "ok" : "warning"}`;
  document.querySelectorAll(".ptz-pad button").forEach((button) => {
    button.disabled = !farm.ptz_enabled;
  });
  renderFarms();
  loadSessions();
  loadPtzPreview();
}

async function loadPtzPreview() {
  const farm = state.farms.find((item) => item.id === state.selectedFarmId);
  if (!farm?.online) {
    elements.ptzPreview.classList.add("hidden");
    elements.ptzPreviewPlaceholder.classList.remove("hidden");
    elements.ptzPreviewPlaceholder.textContent = "농가 PC가 오프라인입니다.";
    elements.ptzPreviewTime.textContent = "—";
    return;
  }
  const camera = elements.ptzCamera.value;
  elements.refreshPtzPreview.disabled = true;
  elements.ptzPreviewPlaceholder.classList.remove("hidden");
  elements.ptzPreviewPlaceholder.textContent = `${camera} 현재 화면을 불러오는 중…`;
  try {
    const blob = await fetchBlob(`/api/farms/${farm.id}/preview?camera=${encodeURIComponent(camera)}&_=${Date.now()}`);
    if (state.ptzPreviewObjectUrl) URL.revokeObjectURL(state.ptzPreviewObjectUrl);
    state.ptzPreviewObjectUrl = URL.createObjectURL(blob);
    elements.ptzPreview.src = state.ptzPreviewObjectUrl;
    elements.ptzPreview.classList.remove("hidden");
    elements.ptzPreviewPlaceholder.classList.add("hidden");
    elements.ptzPreviewTime.textContent = `${camera} · ${dateTime(new Date().toISOString())} 갱신`;
  } catch (error) {
    elements.ptzPreview.classList.add("hidden");
    elements.ptzPreviewPlaceholder.classList.remove("hidden");
    elements.ptzPreviewPlaceholder.textContent = `화면 조회 실패: ${error.message}`;
    elements.ptzPreviewTime.textContent = "—";
  } finally {
    elements.refreshPtzPreview.disabled = false;
  }
}

async function loadDashboard({ quiet = false } = {}) {
  if (!state.apiBaseUrl) {
    setConnection(false, "API 미연결");
    if (!elements.settingsDialog.open) elements.settingsDialog.showModal();
    return;
  }
  elements.refreshButton.classList.add("loading");
  try {
    const [health, dashboard] = await Promise.all([
      fetchApi("/api/health"),
      fetchApi("/api/dashboard"),
    ]);
    state.farms = dashboard.farms || [];
    setConnection(true, `${health.user} 연결됨`);
    elements.lastUpdated.textContent = `${dateTime(dashboard.generated_at)} 갱신`;
    if (!state.selectedFarmId && state.farms.length) state.selectedFarmId = state.farms[0].id;
    renderSummary();
    renderFarms();
    updateFarmSelect();
    if (state.selectedFarmId) selectFarm(state.selectedFarmId);
    if (!quiet) toast("농가 상태를 갱신했습니다.");
  } catch (error) {
    setConnection(false, "API 연결 실패");
    if (!quiet) toast(`연결 실패: ${error.message}`, "error");
  } finally {
    elements.refreshButton.classList.remove("loading");
  }
}

async function runAction(action) {
  const farm = state.farms.find((item) => item.id === state.selectedFarmId);
  if (!farm) return;
  if (action === "restart" && !window.confirm(`${farm.name} 수집 서비스를 재시작할까요?`)) return;
  const button = document.querySelector(`[data-action="${action}"]`);
  button.disabled = true;
  try {
    const job = await fetchApi(`/api/farms/${farm.id}/actions/${action}`, { method: "POST" });
    toast(`${farm.name}: 작업을 시작했습니다.`);
    const result = await waitForJob(job.id);
    elements.logOutput.textContent = result.output || result.error || "작업이 완료되었습니다.";
    if (result.status === "succeeded") {
      toast(`${farm.name}: 작업이 완료됐습니다.`);
      await loadDashboard({ quiet: true });
      if (action === "capture") await loadSessions();
    } else {
      toast(`${farm.name}: ${result.error}`, "error");
    }
  } catch (error) {
    toast(`실행 실패: ${error.message}`, "error");
  } finally {
    button.disabled = false;
  }
}

async function waitForJob(jobId) {
  for (let attempt = 0; attempt < 180; attempt += 1) {
    const job = await fetchApi(`/api/jobs/${jobId}`);
    if (["succeeded", "failed"].includes(job.status)) return job;
    await new Promise((resolve) => window.setTimeout(resolve, 1000));
  }
  throw new Error("작업 완료 대기 시간이 초과됐습니다.");
}

async function loadSessions() {
  if (!state.selectedFarmId) return;
  elements.imageGrid.innerHTML = '<div class="empty-card">촬영 세션을 조회하고 있습니다…</div>';
  const params = new URLSearchParams({ limit: state.sessionLimit, offset: state.sessionOffset });
  if (elements.imageType.value) params.set("data_type", elements.imageType.value);
  if (elements.imageCamera.value) params.set("camera", elements.imageCamera.value);
  try {
    const payload = await fetchApi(`/api/farms/${state.selectedFarmId}/sessions?${params}`);
    state.sessionTotal = payload.total;
    state.currentSessions = payload.items;
    state.sessionImages.clear();
    renderSessions(payload.items);
    const start = payload.total ? state.sessionOffset + 1 : 0;
    const end = Math.min(state.sessionOffset + state.sessionLimit, payload.total);
    elements.imagePage.textContent = `세션 ${start}–${end} / ${payload.total}`;
    elements.previousImages.disabled = state.sessionOffset === 0;
    elements.nextImages.disabled = state.sessionOffset + state.sessionLimit >= payload.total;
  } catch (error) {
    elements.imageGrid.innerHTML = `<div class="empty-card">${escapeHtml(error.message)}</div>`;
  }
}

function sessionStatusLabel(status) {
  return ({
    completed: "수집 완료",
    recording: "수집 중",
    interrupted: "중단",
    partial: "일부 누락",
  })[status] || "확인 필요";
}

function reviewLabel(flags) {
  const labels = [];
  if (flags.includes("missing_camera")) labels.push("카메라 누락");
  if (flags.includes("no_start_detection")) labels.push("시작 감지 기록 없음");
  if (flags.includes("incomplete")) labels.push("미완료");
  return labels.join(" · ");
}

function imageCard(item, typeLabel) {
  const detected = item.person_detected ? '<span class="detection-badge">사람 감지</span>' : "";
  return `
    <article class="image-card" data-image-id="${escapeHtml(item.id)}" tabindex="0">
      <div class="image-frame">
        <img src="${escapeHtml(apiUrl(item.url))}" alt="${escapeHtml(item.camera_id)} ${typeLabel} 이미지" loading="lazy" />
        ${detected}
      </div>
      <div class="image-card-body">
        <div><strong>${escapeHtml(item.camera_id || "CAM")}</strong><small>${dateTime(item.captured_at, true)} · ${bytes(item.size_bytes)}</small></div>
        <span class="image-tag">${typeLabel}</span>
      </div>
    </article>`;
}

function bindImageCards(container, items) {
  container.querySelectorAll(".image-card").forEach((card, index) => {
    const open = () => openImage(items[index]);
    card.addEventListener("click", open);
    card.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") open();
    });
  });
}

function renderSessions(sessions) {
  if (!sessions.length) {
    elements.imageGrid.innerHTML = '<div class="empty-card">조건에 맞는 촬영 세션이 없습니다.</div>';
    return;
  }

  elements.imageGrid.innerHTML = sessions.map((session, sessionIndex) => {
    const typeLabel = session.data_type === "crop" ? "작물 정기 촬영" : "농작업";
    const triggerText = session.trigger_cameras.length
      ? `시작 감지 ${session.trigger_cameras.join(", ")}`
      : "시작 감지 기록 없음";
    const warning = reviewLabel(session.review_flags);
    const statusClass = session.review_flags.length ? "warning" : session.status;
    const cameraSummary = session.cameras.map((camera) => `
      <div class="session-camera ${camera.capture_count ? "" : "missing"}">
        <strong>${escapeHtml(camera.camera_id)}</strong>
        <span>${camera.capture_count}장</span>
        <small>${camera.started_with_person ? "시작 감지" : camera.status === "missing" ? "기록 없음" : "동시 촬영"}</small>
      </div>`).join("");
    const representatives = session.representatives.map((item) => imageCard(item, typeLabel)).join("");
    return `
      <article class="session-card" data-session-index="${sessionIndex}">
        <header class="session-header">
          <div>
            <div class="session-title-row">
              <span class="image-tag">${typeLabel}</span>
              <span class="session-status ${statusClass}">${sessionStatusLabel(session.status)}</span>
            </div>
            <h3>${dateTime(session.started_at)}</h3>
            <p>${escapeHtml(session.session_id)}</p>
          </div>
          <div class="session-metrics">
            <span><strong>${session.capture_count}</strong>장</span>
            <span><strong>${duration(session.duration_seconds)}</strong>지속</span>
            <span class="${session.trigger_cameras.length ? "detected" : "warning-text"}">${escapeHtml(triggerText)}</span>
          </div>
        </header>
        ${warning ? `<p class="session-warning">⚠ ${escapeHtml(warning)}</p>` : ""}
        <div class="session-camera-grid">${cameraSummary}</div>
        <div class="session-representatives">${representatives || '<div class="empty-card">대표 이미지가 없습니다.</div>'}</div>
        <div class="session-actions">
          <span>각 카메라의 세션 시작 이미지를 표시합니다.</span>
          <button class="text-button secondary session-toggle" type="button">세션 전체 이미지 보기</button>
        </div>
        <div class="session-detail hidden"></div>
      </article>`;
  }).join("");

  elements.imageGrid.querySelectorAll(".session-card").forEach((card, sessionIndex) => {
    const session = sessions[sessionIndex];
    bindImageCards(card.querySelector(".session-representatives"), session.representatives);
    card.querySelector(".session-toggle").addEventListener("click", () => toggleSession(card, session));
  });
}

async function toggleSession(card, session) {
  const detail = card.querySelector(".session-detail");
  const button = card.querySelector(".session-toggle");
  if (!detail.classList.contains("hidden")) {
    detail.classList.add("hidden");
    button.textContent = "세션 전체 이미지 보기";
    return;
  }
  detail.classList.remove("hidden");
  button.textContent = "세션 이미지 접기";
  const key = `${session.data_type}:${session.session_id}:${elements.imageCamera.value}`;
  const cached = state.sessionImages.get(key);
  if (cached) {
    renderSessionImages(detail, session, cached);
    return;
  }
  detail.innerHTML = '<div class="empty-card">이 세션의 이미지를 불러오고 있습니다…</div>';
  await loadSessionImages(detail, session, key, false);
}

async function loadSessionImages(detail, session, key, append) {
  const current = append ? (state.sessionImages.get(key)?.items || []) : [];
  const params = new URLSearchParams({ data_type: session.data_type, limit: 60, offset: current.length });
  if (elements.imageCamera.value) params.set("camera", elements.imageCamera.value);
  try {
    const payload = await fetchApi(
      `/api/farms/${state.selectedFarmId}/sessions/${encodeURIComponent(session.session_id)}/images?${params}`,
    );
    const value = { total: payload.total, items: [...current, ...payload.items] };
    state.sessionImages.set(key, value);
    renderSessionImages(detail, session, value);
  } catch (error) {
    detail.innerHTML = `<div class="empty-card">${escapeHtml(error.message)}</div>`;
  }
}

function renderSessionImages(detail, session, value) {
  const typeLabel = session.data_type === "crop" ? "작물" : "농작업";
  detail.innerHTML = `
    <div class="session-detail-heading">
      <div><strong>세션 전체 이미지</strong><small>${value.items.length} / ${value.total}장</small></div>
    </div>
    <div class="session-image-grid">${value.items.map((item) => imageCard(item, typeLabel)).join("")}</div>
    ${value.items.length < value.total ? '<button class="text-button secondary session-more" type="button">이미지 더 보기</button>' : ""}`;
  bindImageCards(detail.querySelector(".session-image-grid"), value.items);
  const more = detail.querySelector(".session-more");
  if (more) {
    const key = `${session.data_type}:${session.session_id}:${elements.imageCamera.value}`;
    more.addEventListener("click", async () => {
      more.disabled = true;
      await loadSessionImages(detail, session, key, true);
    });
  }
}

function openImage(item) {
  const source = apiUrl(item.url);
  elements.fullImage.src = source;
  elements.fullImageTitle.textContent = `${item.camera_id} · ${item.session_id || "스냅샷"}`;
  elements.fullImageMeta.textContent = `${dateTime(item.captured_at, true)} · ${bytes(item.size_bytes)}`;
  elements.downloadImage.href = `${source}?download=true`;
  elements.imageDialog.showModal();
}

async function loadLogs() {
  if (!state.selectedFarmId) return;
  elements.logOutput.textContent = "로그를 불러오는 중입니다…";
  try {
    const payload = await fetchApi(`/api/farms/${state.selectedFarmId}/logs?unit=${elements.logUnit.value}&lines=150`);
    elements.logOutput.textContent = payload.lines || "표시할 로그가 없습니다.";
  } catch (error) {
    elements.logOutput.textContent = `로그 조회 실패: ${error.message}`;
  }
}

async function moveCamera(direction) {
  const farm = state.farms.find((item) => item.id === state.selectedFarmId);
  if (!farm?.ptz_enabled) {
    toast("이 농가에는 아직 PTZ 제어가 설정되지 않았습니다.", "error");
    return;
  }
  try {
    const job = await fetchApi(`/api/farms/${farm.id}/ptz`, {
      method: "POST",
      body: JSON.stringify({
        camera: elements.ptzCamera.value,
        direction,
        speed: Number(elements.ptzSpeed.value),
        duration: direction === "home" ? 0.1 : 0.4,
      }),
    });
    const result = await waitForJob(job.id);
    if (result.status !== "succeeded") throw new Error(result.error);
    window.setTimeout(loadPtzPreview, 500);
  } catch (error) {
    toast(`카메라 제어 실패: ${error.message}`, "error");
  }
}

elements.settingsButton.addEventListener("click", () => {
  elements.apiUrl.value = state.apiBaseUrl;
  if (!elements.settingsDialog.open) elements.settingsDialog.showModal();
});
elements.settingsForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const value = elements.apiUrl.value.trim().replace(/\/$/, "");
  if (!value.startsWith("https://")) {
    toast("Tailscale Serve의 HTTPS 주소를 입력하세요.", "error");
    return;
  }
  state.apiBaseUrl = value;
  localStorage.setItem("farmhouseApiBaseUrl", value);
  elements.settingsDialog.close();
  loadDashboard();
});
elements.refreshButton.addEventListener("click", () => loadDashboard());
elements.farmSelect.addEventListener("change", () => selectFarm(elements.farmSelect.value));
document.querySelectorAll("[data-action]").forEach((button) => button.addEventListener("click", () => runAction(button.dataset.action)));
document.querySelectorAll(".ptz-pad button").forEach((button) => button.addEventListener("click", () => moveCamera(button.dataset.direction)));
elements.ptzCamera.addEventListener("change", loadPtzPreview);
elements.refreshPtzPreview.addEventListener("click", loadPtzPreview);
elements.loadImagesButton.addEventListener("click", () => { state.sessionOffset = 0; loadSessions(); });
elements.previousImages.addEventListener("click", () => { state.sessionOffset = Math.max(0, state.sessionOffset - state.sessionLimit); loadSessions(); });
elements.nextImages.addEventListener("click", () => { state.sessionOffset += state.sessionLimit; loadSessions(); });
elements.loadLogsButton.addEventListener("click", loadLogs);
elements.closeImageDialog.addEventListener("click", () => elements.imageDialog.close());

function initialize() {
  const configured = localStorage.getItem("farmhouseApiBaseUrl") || window.FARMHOUSE_CONFIG?.apiBaseUrl || "";
  state.apiBaseUrl = configured.replace(/\/$/, "");
  loadDashboard({ quiet: true });
  const seconds = Number(window.FARMHOUSE_CONFIG?.refreshSeconds || 60);
  state.refreshTimer = window.setInterval(() => loadDashboard({ quiet: true }), Math.max(30, seconds) * 1000);
}

initialize();
