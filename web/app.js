const state = {
  apiBaseUrl: "",
  farms: [],
  selectedFarmId: null,
  imageOffset: 0,
  imageLimit: 24,
  imageTotal: 0,
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
  state.imageOffset = 0;
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
  loadImages();
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
      if (action === "capture") await loadImages();
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

async function loadImages() {
  if (!state.selectedFarmId) return;
  elements.imageGrid.innerHTML = '<div class="empty-card">이미지를 조회하고 있습니다…</div>';
  const params = new URLSearchParams({ limit: state.imageLimit, offset: state.imageOffset });
  if (elements.imageType.value) params.set("data_type", elements.imageType.value);
  if (elements.imageCamera.value) params.set("camera", elements.imageCamera.value);
  try {
    const payload = await fetchApi(`/api/farms/${state.selectedFarmId}/images?${params}`);
    state.imageTotal = payload.total;
    renderImages(payload.items);
    const start = payload.total ? state.imageOffset + 1 : 0;
    const end = Math.min(state.imageOffset + state.imageLimit, payload.total);
    elements.imagePage.textContent = `${start}–${end} / ${payload.total}`;
    elements.previousImages.disabled = state.imageOffset === 0;
    elements.nextImages.disabled = state.imageOffset + state.imageLimit >= payload.total;
  } catch (error) {
    elements.imageGrid.innerHTML = `<div class="empty-card">${escapeHtml(error.message)}</div>`;
  }
}

function renderImages(items) {
  if (!items.length) {
    elements.imageGrid.innerHTML = '<div class="empty-card">조건에 맞는 저장 이미지가 없습니다.</div>';
    return;
  }
  elements.imageGrid.innerHTML = items.map((item) => {
    const src = apiUrl(item.url);
    const typeLabel = item.data_type === "crop" ? "작물" : "농작업";
    return `
      <article class="image-card" data-image-id="${escapeHtml(item.id)}" tabindex="0">
        <img src="${escapeHtml(src)}" alt="${escapeHtml(item.camera_id)} ${typeLabel} 이미지" loading="lazy" />
        <div class="image-card-body">
          <div><strong>${escapeHtml(item.camera_id || "CAM")}</strong><small>${dateTime(item.captured_at, true)} · ${bytes(item.size_bytes)}</small></div>
          <span class="image-tag">${typeLabel}</span>
        </div>
      </article>`;
  }).join("");
  elements.imageGrid.querySelectorAll(".image-card").forEach((card, index) => {
    const open = () => openImage(items[index]);
    card.addEventListener("click", open);
    card.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") open();
    });
  });
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
elements.loadImagesButton.addEventListener("click", () => { state.imageOffset = 0; loadImages(); });
elements.previousImages.addEventListener("click", () => { state.imageOffset = Math.max(0, state.imageOffset - state.imageLimit); loadImages(); });
elements.nextImages.addEventListener("click", () => { state.imageOffset += state.imageLimit; loadImages(); });
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
