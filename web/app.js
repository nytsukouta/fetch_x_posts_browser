const DATA_URL = "../data/output/schedule_list.json";

const URL_PARAM_KEYS = {
  search: "q",
  location: "loc",
  scope: "scope",
  view: "view",
  event: "event",
};

const VIEW_STORAGE_KEY = "schedule.view";
const VALID_VIEWS = new Set(["dayGridMonth", "listMonth"]);
const PREFECTURE_PATTERN = /北海道|東京都|京都府|大阪府|(?:青森|岩手|宮城|秋田|山形|福島|茨城|栃木|群馬|埼玉|千葉|神奈川|新潟|富山|石川|福井|山梨|長野|岐阜|静岡|愛知|三重|滋賀|兵庫|奈良|和歌山|鳥取|島根|岡山|広島|山口|徳島|香川|愛媛|高知|福岡|佐賀|長崎|熊本|大分|宮崎|鹿児島|沖縄)県/g;
const MUNICIPALITY_PREFECTURES = new Map([
  ["金沢市", "石川県"], ["七尾市", "石川県"], ["白山市", "石川県"],
  ["小松市", "石川県"], ["加賀市", "石川県"], ["野々市市", "石川県"],
  ["輪島市", "石川県"], ["珠洲市", "石川県"], ["羽咋市", "石川県"],
  ["富山市", "富山県"], ["高岡市", "富山県"], ["射水市", "富山県"],
  ["黒部市", "富山県"], ["砺波市", "富山県"], ["魚津市", "富山県"],
  ["氷見市", "富山県"], ["南砺市", "富山県"],
  ["福井市", "福井県"], ["鯖江市", "福井県"], ["越前市", "福井県"],
  ["坂井市", "福井県"], ["敦賀市", "福井県"], ["大野市", "福井県"],
  ["勝山市", "福井県"], ["小浜市", "福井県"],
]);

const state = {
  allItems: [],
  itemById: new Map(),
  initialEventId: "",
  initialView: "",
  pendingLocation: "",
  calendar: null,
};

const elements = {
  countValue: document.getElementById("countValue"),
  generatedAt: document.getElementById("generatedAt"),
  dateScopeFilter: document.getElementById("dateScopeFilter"),
  locationFilter: document.getElementById("locationFilter"),
  searchInput: document.getElementById("searchInput"),
  resultSummary: document.getElementById("resultSummary"),
  clearFiltersButton: document.getElementById("clearFiltersButton"),
  calendarRoot: document.getElementById("calendarRoot"),
  dialog: document.getElementById("eventDialog"),
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
    state.itemById.clear();
    for (const item of state.allItems) {
      if (item.event_id) state.itemById.set(item.event_id, item);
    }
    elements.generatedAt.textContent = formatGeneratedAt(payload.generated_at);

    if (state.initialEventId) {
      const target = state.itemById.get(state.initialEventId);
      if (target && elements.dateScopeFilter.value === "upcoming" && !isUpcomingSchedule(target.performance_schedule)) {
        elements.dateScopeFilter.value = "all";
      }
    }

    populateLocations(state.allItems);
    initCalendar();
    applyFilters();
    focusInitialEvent();
  } catch (error) {
    elements.resultSummary.textContent = "データを読み込めませんでした。HTTP サーバー経由で開いているか確認してください。";
    elements.calendarRoot.innerHTML = `<section class="empty-state"><p>${escapeHtml(String(error))}</p></section>`;
  }
}

function bindEvents() {
  elements.searchInput.addEventListener("input", applyFilters);
  elements.dateScopeFilter.addEventListener("change", applyFilters);
  elements.locationFilter.addEventListener("change", applyFilters);
  if (elements.clearFiltersButton) {
    elements.clearFiltersButton.addEventListener("click", clearFilters);
  }
  if (elements.dialog) {
    elements.dialog.addEventListener("close", () => {
      state.initialEventId = "";
      writeFiltersToUrl();
    });
    elements.dialog.addEventListener("click", (event) => {
      if (event.target === elements.dialog) {
        elements.dialog.close();
      }
    });
  }
}

function restoreFiltersFromUrl() {
  const params = new URLSearchParams(window.location.search);
  const search = params.get(URL_PARAM_KEYS.search);
  const location = params.get(URL_PARAM_KEYS.location);
  const scope = params.get(URL_PARAM_KEYS.scope);
  const view = params.get(URL_PARAM_KEYS.view);
  const eventId = params.get(URL_PARAM_KEYS.event);

  if (search) elements.searchInput.value = search;
  if (scope === "all" || scope === "upcoming") elements.dateScopeFilter.value = scope;
  state.pendingLocation = location || "";
  state.initialEventId = (eventId || "").trim();

  let resolvedView = "";
  if (view && VALID_VIEWS.has(view)) {
    resolvedView = view;
  } else {
    try {
      const stored = window.localStorage.getItem(VIEW_STORAGE_KEY);
      if (stored && VALID_VIEWS.has(stored)) resolvedView = stored;
    } catch (_e) { /* ignore */ }
  }
  if (!resolvedView) {
    resolvedView = isMobileViewport() ? "listMonth" : "dayGridMonth";
  }
  state.initialView = resolvedView;
}

function writeFiltersToUrl() {
  const params = new URLSearchParams();
  const keyword = elements.searchInput.value.trim();
  if (keyword) params.set(URL_PARAM_KEYS.search, keyword);
  if (elements.dateScopeFilter.value && elements.dateScopeFilter.value !== "upcoming") {
    params.set(URL_PARAM_KEYS.scope, elements.dateScopeFilter.value);
  }
  if (elements.locationFilter.value) params.set(URL_PARAM_KEYS.location, elements.locationFilter.value);
  if (state.calendar) {
    const currentView = state.calendar.view ? state.calendar.view.type : "";
    if (currentView && currentView !== "dayGridMonth") {
      params.set(URL_PARAM_KEYS.view, currentView);
    }
  }
  if (state.initialEventId) params.set(URL_PARAM_KEYS.event, state.initialEventId);

  const query = params.toString();
  const newUrl = query ? `${window.location.pathname}?${query}` : window.location.pathname;
  window.history.replaceState(null, "", newUrl);
}

function clearFilters() {
  elements.searchInput.value = "";
  elements.dateScopeFilter.value = "upcoming";
  elements.locationFilter.value = "";
  state.initialEventId = "";
  applyFilters();
}

function populateLocations(items) {
  const requestedLocation = elements.locationFilter.value || state.pendingLocation || "";
  const selectedLocation = extractPrefecture(requestedLocation) || requestedLocation;
  state.pendingLocation = "";

  const locations = unique(items.map(getItemPrefecture).filter(Boolean));
  elements.locationFilter.innerHTML = "<option value=\"\">すべて</option>";
  for (const location of locations) {
    elements.locationFilter.append(createOption(location, location));
  }
  if (selectedLocation && locations.includes(selectedLocation)) {
    elements.locationFilter.value = selectedLocation;
  }
}

function getFilteredItems() {
  const keyword = elements.searchInput.value.trim().toLowerCase();
  const location = elements.locationFilter.value;
  const scope = elements.dateScopeFilter.value;

  return state.allItems.filter((item) => {
    if (scope === "upcoming" && !isUpcomingSchedule(item.performance_schedule)) {
      return false;
    }
    if (location && getItemPrefecture(item) !== location) {
      return false;
    }
    if (keyword) {
      const haystack = [
        item.event_name,
        item.organization_name,
        item.venue_name,
        getItemPrefecture(item),
        normalizeLocation(item.normalized_location),
      ]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      if (!haystack.includes(keyword)) return false;
    }
    return true;
  });
}

function applyFilters() {
  const items = getFilteredItems();
  const totalScope = state.allItems.filter((item) =>
    elements.dateScopeFilter.value === "upcoming" ? isUpcomingSchedule(item.performance_schedule) : true,
  );

  refreshCalendarEvents(items);

  elements.countValue.textContent = String(totalScope.length);

  const keyword = elements.searchInput.value.trim();
  const location = elements.locationFilter.value;
  const hasFilter = Boolean(keyword || location || elements.dateScopeFilter.value !== "upcoming");
  elements.resultSummary.textContent = `${items.length} 件を表示中 / 全 ${totalScope.length} 件`;
  if (elements.clearFiltersButton) {
    elements.clearFiltersButton.hidden = !hasFilter;
  }

  syncEnhancedSelects();
  writeFiltersToUrl();
}

function initCalendar() {
  if (!window.FullCalendar) {
    elements.calendarRoot.innerHTML = '<section class="empty-state"><p>カレンダーライブラリの読み込みに失敗しました。</p></section>';
    return;
  }

  const calendar = new FullCalendar.Calendar(elements.calendarRoot, {
    locale: "ja",
    initialView: state.initialView || "dayGridMonth",
    headerToolbar: {
      left: "prev,next today",
      center: "title",
      right: "dayGridMonth,listMonth",
    },
    buttonText: {
      today: "今日",
      month: "月",
      list: "リスト",
    },
    height: "auto",
    expandRows: true,
    fixedWeekCount: false,
    dayMaxEventRows: 4,
    displayEventTime: false,
    noEventsContent: "条件に合う公演はありません。",
    events: [],
    eventClick: (info) => {
      info.jsEvent.preventDefault();
      const eventId = info.event.id;
      if (eventId) openEventDialog(eventId);
    },
    viewDidMount: () => {
      try {
        window.localStorage.setItem(VIEW_STORAGE_KEY, calendar.view.type);
      } catch (_e) { /* ignore */ }
      writeFiltersToUrl();
    },
  });

  state.calendar = calendar;
  calendar.render();
  bindCalendarSwipe();
}

function bindCalendarSwipe() {
  let startX = 0;
  let startY = 0;
  let tracking = false;

  elements.calendarRoot.addEventListener("touchstart", (event) => {
    if (event.touches.length !== 1 || event.target.closest("button, a, input, select")) {
      tracking = false;
      return;
    }

    const touch = event.touches[0];
    startX = touch.clientX;
    startY = touch.clientY;
    tracking = true;
  }, { passive: true });

  elements.calendarRoot.addEventListener("touchmove", (event) => {
    if (!tracking || event.touches.length !== 1) return;

    const touch = event.touches[0];
    const deltaX = touch.clientX - startX;
    const deltaY = touch.clientY - startY;
    if (Math.abs(deltaX) > 10 && Math.abs(deltaX) > Math.abs(deltaY)) {
      event.preventDefault();
    }
  }, { passive: false });

  elements.calendarRoot.addEventListener("touchend", (event) => {
    if (!tracking || event.changedTouches.length !== 1 || !state.calendar) {
      tracking = false;
      return;
    }

    const touch = event.changedTouches[0];
    const deltaX = touch.clientX - startX;
    const deltaY = touch.clientY - startY;
    const horizontalDistance = Math.abs(deltaX);
    const verticalDistance = Math.abs(deltaY);
    tracking = false;

    if (horizontalDistance < 60 || horizontalDistance <= verticalDistance * 1.2) return;
    if (deltaX < 0) {
      state.calendar.next();
    } else {
      state.calendar.prev();
    }
  }, { passive: true });

  elements.calendarRoot.addEventListener("touchcancel", () => {
    tracking = false;
  }, { passive: true });
}

function refreshCalendarEvents(items) {
  if (!state.calendar) return;
  const events = items.map(toCalendarEvent).filter(Boolean);
  state.calendar.removeAllEvents();
  state.calendar.addEventSource(events);
}

function toCalendarEvent(item) {
  const range = parseScheduleRange(item.performance_schedule);
  if (!range) return null;
  const tone = buildCountdownTone(item.performance_schedule);
  const classes = ["event-pill"];
  if (tone) classes.push(`event-pill--${tone}`);
  return {
    id: item.event_id || "",
    title: item.event_name || item.organization_name || "名称未設定",
    start: range.start,
    end: range.end,
    allDay: true,
    classNames: classes,
    extendedProps: { item },
  };
}

function parseScheduleRange(schedule) {
  const text = String(schedule || "");
  const matches = [...text.matchAll(/(\d{4})-(\d{2})-(\d{2})/g)];
  if (!matches.length) return null;
  const first = matches[0];
  const last = matches[matches.length - 1];
  const start = `${first[1]}-${first[2]}-${first[3]}`;
  const lastDate = `${last[1]}-${last[2]}-${last[3]}`;
  if (lastDate === start) {
    return { start, end: undefined };
  }
  // FullCalendar all-day end is exclusive — add 1 day to last date.
  const endExclusive = addOneDay(lastDate);
  return { start, end: endExclusive };
}

function addOneDay(dateStr) {
  const [y, m, d] = dateStr.split("-").map(Number);
  const date = new Date(Date.UTC(y, m - 1, d));
  date.setUTCDate(date.getUTCDate() + 1);
  const yy = date.getUTCFullYear();
  const mm = String(date.getUTCMonth() + 1).padStart(2, "0");
  const dd = String(date.getUTCDate()).padStart(2, "0");
  return `${yy}-${mm}-${dd}`;
}

function openEventDialog(eventId) {
  const item = state.itemById.get(eventId);
  if (!item || !elements.dialog) return;

  const dialog = elements.dialog;
  const setText = (selector, value) => {
    const node = dialog.querySelector(selector);
    if (node) node.textContent = value || "未設定";
  };
  const setLink = (selector, href, text) => {
    const node = dialog.querySelector(selector);
    if (!node) return;
    if (href) {
      node.href = href;
      if (text) node.textContent = text;
      node.hidden = false;
    } else {
      node.hidden = true;
      node.removeAttribute("href");
    }
  };

  const countdown = buildCountdownLabel(item.performance_schedule);
  const countdownEl = dialog.querySelector(".event-dialog-countdown");
  if (countdownEl) {
    countdownEl.className = "event-dialog-countdown";
    if (countdown) {
      countdownEl.textContent = countdown.label;
      countdownEl.classList.add(`is-${countdown.tone}`);
      countdownEl.hidden = false;
    } else {
      countdownEl.textContent = "";
      countdownEl.hidden = true;
    }
  }

  setText(".event-dialog-date", item.performance_schedule || "日程未設定");
  setText(".event-dialog-title", item.event_name || item.organization_name || "名称未設定");
  setText(".event-dialog-org", item.organization_name);
  setText(".event-dialog-venue", item.venue_name);
  setText(".event-dialog-location", normalizeLocation(item.normalized_location));

  if (hasOfficialReference(item)) {
    setLink(".primary-link", item.official_reference_url, buildReferenceCta(item.official_reference_type));
  } else {
    setLink(".primary-link", "");
  }

  if (item.organization_id) {
    setLink(".organization-link", buildOrganizationLink(item.organization_id), "劇団情報を見る");
  } else {
    setLink(".organization-link", "");
  }

  if (item.source_tweet_url) {
    setLink(".secondary-link", item.source_tweet_url, "元投稿を見る");
  } else {
    setLink(".secondary-link", "");
  }

  state.initialEventId = eventId;
  writeFiltersToUrl();

  if (typeof dialog.showModal === "function" && !dialog.open) {
    dialog.showModal();
  } else if (!dialog.open) {
    dialog.setAttribute("open", "");
  }
}

function focusInitialEvent() {
  if (!state.initialEventId) return;
  const item = state.itemById.get(state.initialEventId);
  if (!item) return;
  if (state.calendar) {
    const range = parseScheduleRange(item.performance_schedule);
    if (range && range.start) {
      try { state.calendar.gotoDate(range.start); } catch (_e) { /* ignore */ }
    }
  }
  openEventDialog(state.initialEventId);
}

function isMobileViewport() {
  if (typeof window.matchMedia !== "function") return false;
  return window.matchMedia("(max-width: 760px)").matches;
}

function buildCountdownTone(schedule) {
  const info = buildCountdownLabel(schedule);
  return info ? info.tone : "";
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

function hasOfficialReference(item) {
  if (!item.official_reference_url || !item.official_reference_type) return false;
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

function normalizeLocation(value) {
  const tokens = String(value || "")
    .split("/")
    .map((token) => token.trim())
    .filter(Boolean);
  const cities = [];
  const fallback = [];
  for (const token of tokens) {
    const match = token.match(/^(.+?[都道府県])(.+?[市区町村])/);
    if (match) {
      const key = `${match[1]}${match[2]}`;
      if (!cities.includes(key)) cities.push(key);
    } else if (!fallback.includes(token)) {
      fallback.push(token);
    }
  }
  return (cities.length ? cities : fallback).join(" / ");
}

function extractPrefecture(value) {
  const text = String(value || "").trim();
  if (!text) return "";
  const explicit = unique(text.match(PREFECTURE_PATTERN) || []);
  if (explicit.length === 1) return explicit[0];
  if (explicit.length > 1) return "";

  const inferred = unique(
    [...MUNICIPALITY_PREFECTURES.entries()]
      .filter(([municipality]) => text.includes(municipality))
      .map(([, prefecture]) => prefecture),
  );
  return inferred.length === 1 ? inferred[0] : "";
}

function getItemPrefecture(item) {
  return String(item.prefecture || "").trim() || extractPrefecture(item.normalized_location);
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
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
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
