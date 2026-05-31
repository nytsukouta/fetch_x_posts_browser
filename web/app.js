const DATA_URL = "../data/output/schedule_list.json";

const URL_PARAM_KEYS = {
  search: "q",
  month: "month",
  location: "loc",
  scope: "scope",
  event: "event",
};

const state = {
  allItems: [],
  items: [],
  filteredItems: [],
  initialEventId: "",
  pendingMonth: "",
  pendingLocation: "",
};

const elements = {
  countValue: document.getElementById("countValue"),
  generatedAt: document.getElementById("generatedAt"),
  dateScopeFilter: document.getElementById("dateScopeFilter"),
  monthFilter: document.getElementById("monthFilter"),
  locationFilter: document.getElementById("locationFilter"),
  searchInput: document.getElementById("searchInput"),
  resultSummary: document.getElementById("resultSummary"),
  clearFiltersButton: document.getElementById("clearFiltersButton"),
  scheduleGrid: document.getElementById("scheduleGrid"),
  cardTemplate: document.getElementById("cardTemplate"),
};

async function main() {
  restoreFiltersFromUrl();
  bindEvents();
  enhanceAllSelects();

  try {
    const response = await fetch(DATA_URL, { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`failed to load schedule data: ${response.status}`);
    }

    const payload = await response.json();
    state.allItems = Array.isArray(payload.items) ? payload.items : [];
    elements.generatedAt.textContent = formatGeneratedAt(payload.generated_at);

    if (state.initialEventId) {
      const target = state.allItems.find((item) => (item.event_id || "") === state.initialEventId);
      if (target && elements.dateScopeFilter.value === "upcoming" && !isUpcomingSchedule(target.performance_schedule)) {
        elements.dateScopeFilter.value = "all";
      }
    }

    applyFilters();
    focusInitialEvent();
  } catch (error) {
    elements.resultSummary.textContent = "データを読み込めませんでした。HTTP サーバー経由で開いているか確認してください。";
    elements.scheduleGrid.innerHTML = `<section class="empty-state"><p>${escapeHtml(String(error))}</p></section>`;
  }
}

function bindEvents() {
  elements.searchInput.addEventListener("input", applyFilters);
  elements.dateScopeFilter.addEventListener("change", applyFilters);
  elements.monthFilter.addEventListener("change", applyFilters);
  elements.locationFilter.addEventListener("change", applyFilters);
  if (elements.clearFiltersButton) {
    elements.clearFiltersButton.addEventListener("click", clearFilters);
  }
}

function restoreFiltersFromUrl() {
  const params = new URLSearchParams(window.location.search);
  const search = params.get(URL_PARAM_KEYS.search);
  const month = params.get(URL_PARAM_KEYS.month);
  const location = params.get(URL_PARAM_KEYS.location);
  const scope = params.get(URL_PARAM_KEYS.scope);
  const eventId = params.get(URL_PARAM_KEYS.event);

  if (search) elements.searchInput.value = search;
  if (scope === "all" || scope === "upcoming") elements.dateScopeFilter.value = scope;
  state.pendingMonth = month || "";
  state.pendingLocation = location || "";
  state.initialEventId = (eventId || "").trim();
}

function writeFiltersToUrl() {
  const params = new URLSearchParams();
  const keyword = elements.searchInput.value.trim();
  if (keyword) params.set(URL_PARAM_KEYS.search, keyword);
  if (elements.dateScopeFilter.value && elements.dateScopeFilter.value !== "upcoming") {
    params.set(URL_PARAM_KEYS.scope, elements.dateScopeFilter.value);
  }
  if (elements.monthFilter.value) params.set(URL_PARAM_KEYS.month, elements.monthFilter.value);
  if (elements.locationFilter.value) params.set(URL_PARAM_KEYS.location, elements.locationFilter.value);
  if (state.initialEventId) params.set(URL_PARAM_KEYS.event, state.initialEventId);

  const query = params.toString();
  const newUrl = query ? `${window.location.pathname}?${query}` : window.location.pathname;
  window.history.replaceState(null, "", newUrl);
}

function clearFilters() {
  elements.searchInput.value = "";
  elements.dateScopeFilter.value = "upcoming";
  elements.monthFilter.value = "";
  elements.locationFilter.value = "";
  state.initialEventId = "";
  applyFilters();
}

function populateFilters(items) {
  const selectedMonth = elements.monthFilter.value || state.pendingMonth || "";
  const selectedLocation = elements.locationFilter.value || state.pendingLocation || "";
  state.pendingMonth = "";
  state.pendingLocation = "";

  const months = unique(items.map((item) => extractMonth(item.performance_schedule)).filter(Boolean));
  const locations = unique(items.map((item) => item.normalized_location).filter(Boolean));

  elements.monthFilter.innerHTML = "<option value=\"\">すべて</option>";
  elements.locationFilter.innerHTML = "<option value=\"\">すべて</option>";

  for (const month of months) {
    elements.monthFilter.append(createOption(month, month));
  }

  for (const location of locations) {
    elements.locationFilter.append(createOption(location, location));
  }

  if (selectedMonth && months.includes(selectedMonth)) {
    elements.monthFilter.value = selectedMonth;
  }
  if (selectedLocation && locations.includes(selectedLocation)) {
    elements.locationFilter.value = selectedLocation;
  }
}

function applyFilters() {
  state.items = getScopedItems();
  populateFilters(state.items);

  const keyword = elements.searchInput.value.trim().toLowerCase();
  const month = elements.monthFilter.value;
  const location = elements.locationFilter.value;

  state.filteredItems = state.items.filter((item) => {
    const haystack = [
      item.event_name,
      item.organization_name,
      item.venue_name,
      item.normalized_location,
    ]
      .filter(Boolean)
      .join(" ")
      .toLowerCase();

    if (keyword && !haystack.includes(keyword)) {
      return false;
    }

    if (month && extractMonth(item.performance_schedule) !== month) {
      return false;
    }

    if (location && item.normalized_location !== location) {
      return false;
    }

    return true;
  });

  renderCards(state.filteredItems);
  elements.countValue.textContent = String(state.items.length);

  const hasFilter = Boolean(keyword || month || location || elements.dateScopeFilter.value !== "upcoming");
  elements.resultSummary.textContent = `${state.filteredItems.length} 件を表示中 / 全 ${state.items.length} 件`;
  if (elements.clearFiltersButton) {
    elements.clearFiltersButton.hidden = !hasFilter;
  }

  syncEnhancedSelects();
  writeFiltersToUrl();
}

function getScopedItems() {
  if (elements.dateScopeFilter.value === "all") {
    return [...state.allItems];
  }
  return state.allItems.filter((item) => isUpcomingSchedule(item.performance_schedule));
}

function renderCards(items) {
  elements.scheduleGrid.innerHTML = "";

  if (!items.length) {
    elements.scheduleGrid.innerHTML = '<section class="empty-state"><p>条件に合う公演はありません。</p></section>';
    return;
  }

  items.forEach((item, index) => {
    const fragment = elements.cardTemplate.content.cloneNode(true);
    const card = fragment.querySelector(".event-card");
    card.style.animationDelay = `${Math.min(index * 55, 420)}ms`;
    if (item.event_id) {
      card.dataset.eventId = item.event_id;
      card.id = `event-${item.event_id}`;
    }
    if (state.initialEventId && item.event_id === state.initialEventId) {
      card.classList.add("is-highlighted");
    }

    const countdownChip = fragment.querySelector(".event-countdown");
    const countdown = buildCountdownLabel(item.performance_schedule);
    if (countdownChip) {
      if (countdown) {
        countdownChip.textContent = countdown.label;
        countdownChip.classList.add(`is-${countdown.tone}`);
      } else {
        countdownChip.remove();
      }
    }

    fragment.querySelector(".event-date").textContent = item.performance_schedule || "日程未設定";
    fragment.querySelector(".event-title").textContent = item.event_name || item.organization_name || "名称未設定";
    fragment.querySelector(".organization-name").textContent = item.organization_name || "未設定";
    fragment.querySelector(".venue-name").textContent = item.venue_name || "未設定";
    fragment.querySelector(".location-name").textContent = item.normalized_location || "未設定";

    const primaryLink = fragment.querySelector(".primary-link");
    if (hasOfficialReference(item)) {
      primaryLink.href = item.official_reference_url;
      primaryLink.textContent = buildReferenceCta(item.official_reference_type);
    } else {
      primaryLink.remove();
    }

    const organizationLink = fragment.querySelector(".organization-link");
    if (item.organization_id) {
      organizationLink.href = buildOrganizationLink(item.organization_id);
    } else {
      organizationLink.remove();
    }

    const secondaryLink = fragment.querySelector(".secondary-link");
    if (item.source_tweet_url) {
      secondaryLink.href = item.source_tweet_url;
    } else {
      secondaryLink.remove();
    }

    elements.scheduleGrid.append(fragment);
  });
}

function focusInitialEvent() {
  if (!state.initialEventId) return;
  const target = elements.scheduleGrid.querySelector(`[data-event-id="${cssEscape(state.initialEventId)}"]`);
  if (!target) return;
  requestAnimationFrame(() => {
    target.scrollIntoView({ behavior: "smooth", block: "center" });
  });
}

function cssEscape(value) {
  if (window.CSS && typeof window.CSS.escape === "function") {
    return window.CSS.escape(value);
  }
  return String(value).replace(/[^a-zA-Z0-9_-]/g, "\\$&");
}

function buildCountdownLabel(schedule) {
  const text = String(schedule || "");
  const allMatches = [...text.matchAll(/(\d{4})-(\d{2})-(\d{2})/g)];
  if (!allMatches.length) return null;
  const first = allMatches[0];
  const last = allMatches[allMatches.length - 1];
  const start = new Date(Number(first[1]), Number(first[2]) - 1, Number(first[3]));
  const end = new Date(Number(last[1]), Number(last[2]) - 1, Number(last[3]));

  const today = new Date();
  today.setHours(0, 0, 0, 0);

  const dayMs = 24 * 60 * 60 * 1000;
  const daysToStart = Math.round((start - today) / dayMs);
  const daysToEnd = Math.round((end - today) / dayMs);

  if (daysToEnd < 0) return { label: "終了", tone: "ended" };
  if (daysToStart <= 0 && daysToEnd >= 0) return { label: "開催中", tone: "live" };
  if (daysToStart === 1) return { label: "あす", tone: "soon" };
  if (daysToStart <= 7) return { label: `あと${daysToStart}日`, tone: "soon" };
  if (daysToStart <= 30) return { label: `あと${daysToStart}日`, tone: "near" };
  return null;
}

function buildReferenceLabel(referenceType) {
  if (referenceType.startsWith("organization_official") || referenceType.startsWith("venue_official")) {
    return "公式リンク";
  }
  return "";
}

function hasOfficialReference(item) {
  if (!item.official_reference_url || !item.official_reference_type) {
    return false;
  }
  return item.official_reference_type.startsWith("organization_official") || item.official_reference_type.startsWith("venue_official");
}

function buildReferenceCta(referenceType) {
  if (referenceType.startsWith("organization_official") || referenceType.startsWith("venue_official")) {
    return "公式情報を見る";
  }
  return "候補アカウントを見る";
}

function buildOrganizationLink(organizationId) {
  const params = new URLSearchParams({ type: "organizations", id: organizationId });
  return `./masters.html?${params.toString()}`;
}

function createOption(value, label) {
  const option = document.createElement("option");
  option.value = value;
  option.textContent = label;
  return option;
}

function extractMonth(schedule) {
  const match = String(schedule || "").match(/^(\d{4}-\d{2})/);
  return match ? match[1] : "";
}

function isUpcomingSchedule(schedule) {
  const text = String(schedule || "");
  const matches = [...text.matchAll(/(\d{4}-\d{2}-\d{2})/g)];
  if (!matches.length) return false;
  const last = matches[matches.length - 1][1];

  const today = new Date();
  const todayKey = [
    today.getFullYear(),
    String(today.getMonth() + 1).padStart(2, "0"),
    String(today.getDate()).padStart(2, "0"),
  ].join("-");

  return last >= todayKey;
}

function formatGeneratedAt(value) {
  if (!value) {
    return "-";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat("ja-JP", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function unique(values) {
  return [...new Set(values)].sort((left, right) => left.localeCompare(right, "ja"));
}

function escapeHtml(value) {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

const enhancedSelects = [];

function enhanceAllSelects() {
  document.querySelectorAll("select").forEach((select) => enhanceSelect(select));
}

function enhanceSelect(select) {
  const wrapper = document.createElement("div");
  wrapper.className = "custom-select";

  const button = document.createElement("button");
  button.type = "button";
  button.className = "custom-select-button";
  button.setAttribute("aria-haspopup", "listbox");
  button.setAttribute("aria-expanded", "false");

  const label = document.createElement("span");
  label.className = "custom-select-label";

  const chevron = document.createElement("span");
  chevron.className = "custom-select-chevron";
  chevron.setAttribute("aria-hidden", "true");

  button.append(label, chevron);

  const panel = document.createElement("div");
  panel.className = "custom-select-panel";
  panel.setAttribute("role", "listbox");
  panel.hidden = true;

  select.parentNode.insertBefore(wrapper, select);
  wrapper.append(select, button, panel);
  select.classList.add("is-enhanced");

  function sync() {
    const opt = select.options[select.selectedIndex];
    label.textContent = opt ? opt.textContent : "";
    panel.innerHTML = "";
    Array.from(select.options).forEach((option) => {
      const item = document.createElement("button");
      item.type = "button";
      item.className = "custom-select-option";
      item.setAttribute("role", "option");
      item.textContent = option.textContent;
      item.dataset.value = option.value;
      if (option.value === select.value) {
        item.classList.add("is-selected");
        item.setAttribute("aria-selected", "true");
      }
      item.addEventListener("click", () => {
        if (select.value !== option.value) {
          select.value = option.value;
          select.dispatchEvent(new Event("change", { bubbles: true }));
        }
        close();
        button.focus();
      });
      panel.append(item);
    });
  }

  function open() {
    sync();
    panel.hidden = false;
    button.setAttribute("aria-expanded", "true");
    wrapper.classList.add("is-open");
  }

  function close() {
    panel.hidden = true;
    button.setAttribute("aria-expanded", "false");
    wrapper.classList.remove("is-open");
  }

  button.addEventListener("click", (event) => {
    event.stopPropagation();
    if (panel.hidden) {
      // close other open panels
      enhancedSelects.forEach((entry) => entry !== api && entry.close());
      open();
    } else {
      close();
    }
  });

  document.addEventListener("click", (event) => {
    if (!wrapper.contains(event.target)) close();
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !panel.hidden) {
      close();
      button.focus();
    }
  });

  const api = { sync, close };
  enhancedSelects.push(api);
  sync();
}

function syncEnhancedSelects() {
  enhancedSelects.forEach((entry) => entry.sync());
}

main();
