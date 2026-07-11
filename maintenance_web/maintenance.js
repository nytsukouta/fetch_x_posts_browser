"use strict";

const EDITABLE_FIELDS = [
  "event_name", "normalized_event_name", "organization", "venue_name",
  "normalized_venue_name", "location", "normalized_location", "start_date",
  "end_date", "start_time", "category", "posting_recommendation",
  "is_event_announcement", "has_actionable_schedule_info",
  "manual_reference_url", "manual_publish_status",
];

const state = {
  status: null,
  items: [],
  selectedId: "",
  detail: null,
  revision: "",
  initialSnapshot: "",
  busy: false,
};

const $ = (id) => document.getElementById(id);
const elements = {
  syncSummary: $("syncSummary"), warningBar: $("warningBar"),
  baseCount: $("baseCount"), scheduleCount: $("scheduleCount"),
  overrideCount: $("overrideCount"), problemCount: $("problemCount"),
  syncButton: $("syncButton"), publishButton: $("publishButton"),
  searchInput: $("searchInput"), prefectureFilter: $("prefectureFilter"),
  publicationFilter: $("publicationFilter"), upcomingOnly: $("upcomingOnly"),
  overrideOnly: $("overrideOnly"), resultCount: $("resultCount"), eventList: $("eventList"),
  emptyState: $("emptyState"), editForm: $("editForm"), eventId: $("eventId"),
  detailTitle: $("detailTitle"), overrideBadge: $("overrideBadge"), noteInput: $("noteInput"),
  previewStatus: $("previewStatus"), previewText: $("previewText"), previewLink: $("previewLink"),
  sourceLinks: $("sourceLinks"), deleteButton: $("deleteButton"), toast: $("toast"),
};

async function api(url, options = {}) {
  const response = await fetch(url, {
    cache: "no-store",
    headers: options.body ? { "Content-Type": "application/json" } : undefined,
    ...options,
  });
  let payload;
  try { payload = await response.json(); } catch (_error) { payload = {}; }
  if (!response.ok) {
    const error = new Error(payload.error || `HTTP ${response.status}`);
    error.status = response.status;
    throw error;
  }
  return payload;
}

function showToast(message, error = false) {
  elements.toast.textContent = message;
  elements.toast.classList.toggle("error", error);
  elements.toast.hidden = false;
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => { elements.toast.hidden = true; }, 4200);
}

function setBusy(busy) {
  state.busy = busy;
  for (const button of document.querySelectorAll("button")) button.disabled = busy;
}

function formValues() {
  const values = {};
  for (const field of EDITABLE_FIELDS) {
    const control = elements.editForm.elements.namedItem(field);
    values[field] = String(control?.value || "").trim();
  }
  values.manual_publish_status ||= "default";
  return { values, note: elements.noteInput.value.trim() };
}

function snapshot() {
  if (!state.detail) return "";
  return JSON.stringify(formValues());
}

function isDirty() {
  return Boolean(state.detail && snapshot() !== state.initialSnapshot);
}

function confirmDiscard() {
  return !isDirty() || window.confirm("未保存の変更があります。破棄して続けますか？");
}

function normalizedBaseValue(field, value) {
  if (field === "manual_publish_status" && !value) return "default";
  return String(value || "").trim();
}

function markChangedFields() {
  if (!state.detail) return;
  const values = formValues().values;
  for (const field of EDITABLE_FIELDS) {
    const control = elements.editForm.elements.namedItem(field);
    const changed = values[field] !== normalizedBaseValue(field, state.detail.base[field]);
    control?.closest("label")?.classList.toggle("changed", changed);
  }
}

function updatePreview() {
  if (!state.detail) return;
  const { values } = formValues();
  const status = values.manual_publish_status;
  const hasDate = /^\d{4}-\d{2}-\d{2}$/.test(values.start_date);
  const forced = status === "published" && hasDate && Boolean(values.event_name || values.organization);
  const excluded = status === "excluded";
  const currentSchedule = state.detail.schedule;
  const listed = excluded ? false : forced || (Boolean(currentSchedule) && !isDirty());
  elements.previewStatus.textContent = listed ? "掲載" : excluded ? "除外" : "保存後に再判定";
  const dateText = [values.start_date, values.end_date && values.end_date !== values.start_date ? `〜 ${values.end_date}` : "", values.start_time].filter(Boolean).join(" ");
  elements.previewText.textContent = `${values.event_name || values.organization || "名称未設定"}｜${values.venue_name || "会場未設定"}｜${dateText || "日程未設定"}`;
  const href = values.manual_reference_url || currentSchedule?.official_reference_url || "";
  elements.previewLink.hidden = !href;
  if (href) elements.previewLink.href = href;
  markChangedFields();
}

function renderStatus() {
  const status = state.status || {};
  const counts = status.counts || {};
  elements.baseCount.textContent = String(counts.base || 0);
  elements.scheduleCount.textContent = String(counts.schedule || 0);
  elements.overrideCount.textContent = String(counts.overrides || 0);
  elements.problemCount.textContent = String((counts.orphan || 0) + (counts.ambiguous || 0));
  const sync = status.sync || {};
  elements.syncSummary.replaceChildren();
  if (sync.updated_at) {
    elements.syncSummary.append(`最終同期: ${formatDateTime(sync.updated_at)} `);
    if (sync.url) {
      const link = document.createElement("a");
      link.href = sync.url;
      link.target = "_blank";
      link.rel = "noreferrer";
      link.textContent = `run #${sync.run_id}`;
      elements.syncSummary.append(link);
    }
  } else {
    elements.syncSummary.textContent = "まだGitHubから同期していません";
  }
  const warnings = [];
  if (!status.gh?.available) warnings.push("GitHub CLI (gh) が見つかりません。");
  else if (!status.gh?.authenticated) warnings.push("GitHub CLIが未認証です。");
  if (counts.orphan) warnings.push(`対象が見つからない補正が ${counts.orphan} 件あります。`);
  if (counts.ambiguous) warnings.push(`対象を一意に決められない補正が ${counts.ambiguous} 件あります。`);
  for (const message of sync.warnings || []) warnings.push(message);
  elements.warningBar.hidden = warnings.length === 0;
  elements.warningBar.textContent = warnings.join(" ");
  elements.publishButton.disabled = state.busy || !status.git?.override_changed;
}

function formatDateTime(value) {
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? value : date.toLocaleString("ja-JP");
}

function itemDate(item) {
  return item.effective.end_date || item.effective.start_date || "";
}

function isUpcoming(item) {
  const value = itemDate(item);
  if (!value) return false;
  const today = new Date();
  const local = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;
  return value >= local;
}

function filteredItems() {
  const keyword = elements.searchInput.value.trim().toLowerCase();
  const prefecture = elements.prefectureFilter.value;
  const publication = elements.publicationFilter.value;
  return state.items.filter((item) => {
    const row = item.effective;
    const haystack = [row.event_name, row.organization, row.venue_name, row.normalized_location].filter(Boolean).join(" ").toLowerCase();
    const status = row.manual_publish_status || "default";
    return (!keyword || haystack.includes(keyword))
      && (!prefecture || item.prefecture === prefecture)
      && (!publication || status === publication)
      && (!elements.overrideOnly.checked || item.has_override)
      && (!elements.upcomingOnly.checked || isUpcoming(item));
  });
}

function renderList() {
  const items = filteredItems();
  elements.resultCount.textContent = `${items.length}件 / 全${state.items.length}件`;
  elements.eventList.replaceChildren();
  if (!items.length) {
    const message = document.createElement("p");
    message.className = "empty-state";
    message.textContent = state.items.length ? "条件に合う公演はありません。" : "データがありません。GitHubから最新データを取得してください。";
    elements.eventList.append(message);
    return;
  }
  for (const item of items) {
    const row = item.effective;
    const button = document.createElement("button");
    button.type = "button";
    button.className = `event-item${item.event_id === state.selectedId ? " active" : ""}`;
    const title = document.createElement("strong");
    title.textContent = row.event_name || row.organization || "名称未設定";
    const meta = document.createElement("div");
    meta.className = "event-meta";
    for (const value of [row.organization, row.venue_name, row.start_date]) {
      if (!value) continue;
      const span = document.createElement("span");
      span.textContent = value;
      meta.append(span);
    }
    if (item.has_override) {
      const badge = document.createElement("span");
      badge.className = `mini-badge${row.manual_publish_status === "excluded" ? " excluded" : ""}`;
      badge.textContent = row.manual_publish_status === "excluded" ? "除外" : "補正";
      meta.append(badge);
    }
    button.append(title, meta);
    button.addEventListener("click", () => selectEvent(item.event_id));
    elements.eventList.append(button);
  }
}

function populatePrefectures() {
  const selected = elements.prefectureFilter.value;
  const values = [...new Set(state.items.map((item) => item.prefecture).filter(Boolean))].sort();
  elements.prefectureFilter.replaceChildren(new Option("すべて", ""));
  for (const value of values) elements.prefectureFilter.append(new Option(value, value));
  if (values.includes(selected)) elements.prefectureFilter.value = selected;
}

async function loadStatus() {
  state.status = await api("/api/status");
  state.revision = state.status.revision || "";
  renderStatus();
}

async function loadEvents() {
  const payload = await api("/api/events");
  state.items = payload.items || [];
  state.revision = payload.revision || state.revision;
  populatePrefectures();
  renderList();
}

async function selectEvent(eventId, force = false) {
  if (!force && eventId !== state.selectedId && !confirmDiscard()) return;
  try {
    const detail = await api(`/api/events/${encodeURIComponent(eventId)}`);
    state.selectedId = eventId;
    state.detail = detail;
    state.revision = detail.revision;
    fillForm(detail);
    renderList();
  } catch (error) { showToast(error.message, true); }
}

function fillForm(detail) {
  const row = detail.effective;
  elements.emptyState.hidden = true;
  elements.editForm.hidden = false;
  elements.eventId.textContent = detail.event_id;
  elements.detailTitle.textContent = row.event_name || row.organization || "公演情報を補正";
  elements.overrideBadge.hidden = !detail.override;
  elements.deleteButton.hidden = !detail.override;
  for (const field of EDITABLE_FIELDS) {
    const control = elements.editForm.elements.namedItem(field);
    let value = row[field] || "";
    if (field === "manual_publish_status" && !value) value = "default";
    control.value = value;
  }
  elements.noteInput.value = detail.override?.note || "";
  elements.sourceLinks.replaceChildren();
  for (const url of detail.source_tweet_urls || []) {
    const link = document.createElement("a");
    link.href = url;
    link.target = "_blank";
    link.rel = "noreferrer";
    link.textContent = url;
    elements.sourceLinks.append(link);
  }
  state.initialSnapshot = snapshot();
  updatePreview();
}

async function refreshAll(preserveSelection = true) {
  await Promise.all([loadStatus(), loadEvents()]);
  if (preserveSelection && state.selectedId && state.items.some((item) => item.event_id === state.selectedId)) {
    await selectEvent(state.selectedId, true);
  }
}

async function syncData() {
  if (!confirmDiscard() || !window.confirm("GitHub Actionsの最新成功データを取得しますか？")) return;
  setBusy(true);
  try {
    const result = await api("/api/sync", { method: "POST" });
    showToast(`run #${result.run_id} を同期しました`);
    await refreshAll(false);
    state.selectedId = "";
    state.detail = null;
    elements.editForm.hidden = true;
    elements.emptyState.hidden = false;
  } catch (error) { showToast(error.message, true); }
  finally { setBusy(false); renderStatus(); }
}

async function saveOverride(event) {
  event.preventDefault();
  if (!state.detail) return;
  const { values, note } = formValues();
  const set = {};
  for (const field of EDITABLE_FIELDS) {
    const baseValue = normalizedBaseValue(field, state.detail.base[field]);
    if (values[field] !== baseValue) set[field] = values[field];
  }
  if (!Object.keys(set).length && !note) {
    showToast("base値との差分がありません", true);
    return;
  }
  setBusy(true);
  try {
    const payload = await api(`/api/events/${encodeURIComponent(state.selectedId)}/override`, {
      method: "PUT",
      body: JSON.stringify({ revision: state.revision, set, note, target_source_tweet_urls: state.detail.source_tweet_urls }),
    });
    state.revision = payload.event.revision;
    showToast("補正を保存し、ローカルプレビューを再生成しました");
    await refreshAll(true);
  } catch (error) {
    showToast(error.status === 409 ? `${error.message} 最新データを読み直してください。` : error.message, true);
  } finally { setBusy(false); renderStatus(); }
}

async function deleteOverride() {
  if (!state.detail?.override || !window.confirm("この補正を解除し、自動抽出値へ戻しますか？")) return;
  setBusy(true);
  try {
    await api(`/api/events/${encodeURIComponent(state.selectedId)}/override`, {
      method: "DELETE", body: JSON.stringify({ revision: state.revision }),
    });
    showToast("補正を解除しました");
    await refreshAll(true);
  } catch (error) { showToast(error.message, true); }
  finally { setBusy(false); renderStatus(); }
}

async function publish() {
  if (!confirmDiscard() || !window.confirm("補正JSONだけをcommitし、origin/mainへpushしますか？")) return;
  setBusy(true);
  try {
    const result = await api("/api/publish", { method: "POST" });
    showToast(`GitHubへ反映しました (${String(result.commit).slice(0, 8)})`);
    await loadStatus();
  } catch (error) { showToast(error.message, true); }
  finally { setBusy(false); renderStatus(); }
}

function bindEvents() {
  elements.syncButton.addEventListener("click", syncData);
  elements.publishButton.addEventListener("click", publish);
  elements.editForm.addEventListener("submit", saveOverride);
  elements.deleteButton.addEventListener("click", deleteOverride);
  for (const input of [elements.searchInput, elements.prefectureFilter, elements.publicationFilter, elements.upcomingOnly, elements.overrideOnly]) {
    input.addEventListener(input.tagName === "INPUT" && input.type === "search" ? "input" : "change", renderList);
  }
  elements.editForm.addEventListener("input", (event) => {
    if (event.target.name === "event_name" && state.detail) {
      const normalized = elements.editForm.elements.namedItem("normalized_event_name");
      const previousTitle = state.detail.effective.event_name || "";
      const previousNormalized = state.detail.effective.normalized_event_name || "";
      if (normalized.value === previousNormalized && previousTitle === previousNormalized) normalized.value = event.target.value;
    }
    updatePreview();
  });
  window.addEventListener("beforeunload", (event) => {
    if (!isDirty()) return;
    event.preventDefault();
    event.returnValue = "";
  });
}

async function main() {
  bindEvents();
  try { await refreshAll(false); }
  catch (error) { showToast(error.message, true); }
}

main();
