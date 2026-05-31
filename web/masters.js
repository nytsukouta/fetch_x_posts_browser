const DATA_URL = "./data/master_data.json";

const state = {
  payload: null,
  items: [],
  filteredItems: [],
  focusedId: "",
};

const elements = {
  organizationCount: document.getElementById("organizationCount"),
  venueCount: document.getElementById("venueCount"),
  generatedAt: document.getElementById("generatedAt"),
  typeFilter: document.getElementById("typeFilter"),
  locationFilter: document.getElementById("locationFilter"),
  searchInput: document.getElementById("searchInput"),
  resultSummary: document.getElementById("resultSummary"),
  masterGrid: document.getElementById("masterGrid"),
  masterCardTemplate: document.getElementById("masterCardTemplate"),
};

async function main() {
  bindEvents();
  readInitialQuery();
  enhanceAllSelects();

  try {
    const response = await fetch(DATA_URL, { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`failed to load master data: ${response.status}`);
    }

    state.payload = await response.json();
    elements.organizationCount.textContent = String(state.payload.counts?.organizations ?? 0);
    elements.venueCount.textContent = String(state.payload.counts?.venues ?? 0);
    elements.generatedAt.textContent = formatGeneratedAt(state.payload.generated_at);

    syncItems();
    applyFilters();
  } catch (error) {
    elements.resultSummary.textContent = "データを読み込めませんでした。master_data.json が生成されているか確認してください。";
    elements.masterGrid.innerHTML = `<section class="empty-state"><p>${escapeHtml(String(error))}</p></section>`;
  }
}

function bindEvents() {
  elements.typeFilter.addEventListener("change", () => {
    clearFocusedId();
    syncItems();
    applyFilters();
  });
  elements.locationFilter.addEventListener("change", () => {
    clearFocusedId();
    applyFilters();
  });
  elements.searchInput.addEventListener("input", () => {
    clearFocusedId();
    applyFilters();
  });
}

function readInitialQuery() {
  const params = new URLSearchParams(window.location.search);
  const type = params.get("type");
  const id = params.get("id");
  if (type === "organizations" || type === "venues") {
    elements.typeFilter.value = type;
  }
  if (id) {
    state.focusedId = id;
  }
}

function clearFocusedId() {
  state.focusedId = "";
}

function syncItems() {
  const type = elements.typeFilter.value;
  state.items = Array.isArray(state.payload?.[type]) ? state.payload[type] : [];
  populateLocations(state.items);
}

function populateLocations(items) {
  const currentValue = elements.locationFilter.value;
  const locations = unique(items.map((item) => item.location).filter(Boolean));
  elements.locationFilter.innerHTML = '<option value="">すべて</option>';
  for (const location of locations) {
    elements.locationFilter.append(createOption(location, location));
  }
  if (locations.includes(currentValue)) {
    elements.locationFilter.value = currentValue;
  }
  syncEnhancedSelects();
}

function applyFilters() {
  const keyword = elements.searchInput.value.trim().toLowerCase();
  const location = elements.locationFilter.value;

  state.filteredItems = state.items.filter((item) => {
    if (state.focusedId && item.id !== state.focusedId) {
      return false;
    }

    const haystack = [item.name, item.location, item.id].filter(Boolean).join(" ").toLowerCase();

    if (keyword && !haystack.includes(keyword)) {
      return false;
    }

    if (location && item.location !== location) {
      return false;
    }

    return true;
  });

  renderCards(state.filteredItems, elements.typeFilter.value);
  const typeLabel = elements.typeFilter.value === "organizations" ? "劇団" : "劇場";
  if (state.focusedId) {
    elements.resultSummary.textContent = `${typeLabel} 1 件をピン表示中 / 全 ${state.items.length} 件`;
    return;
  }
  elements.resultSummary.textContent = `${typeLabel} ${state.filteredItems.length} 件を表示中 / 全 ${state.items.length} 件`;
}

function renderCards(items, type) {
  elements.masterGrid.innerHTML = "";

  if (!items.length) {
    elements.masterGrid.innerHTML = '<section class="empty-state"><p>条件に合う項目はありません。</p></section>';
    return;
  }

  items.forEach((item, index) => {
    const fragment = elements.masterCardTemplate.content.cloneNode(true);
    const card = fragment.querySelector(".master-card");
    card.style.animationDelay = `${Math.min(index * 40, 360)}ms`;

    fragment.querySelector(".master-chip").textContent = type === "organizations" ? "劇団マスター" : "劇場マスター";
    fragment.querySelector(".master-id").textContent = item.id || "ID未設定";
    fragment.querySelector(".master-title").textContent = item.name || "名称未設定";
    fragment.querySelector(".location-name").textContent = item.location || "未設定";

    fillLinkValue(fragment.querySelector(".website-value"), item.official_website, "公式サイトを開く");

    const xRow = fragment.querySelector(".x-row");
    const queryRow = fragment.querySelector(".query-row");
    if (type === "organizations") {
      fillLinkValue(fragment.querySelector(".x-value"), item.official_x, "公式Xを開く");
      fragment.querySelector(".query-value").textContent = item.query_include ? "対象" : "通常";
    } else {
      xRow.remove();
      queryRow.remove();
    }

    elements.masterGrid.append(fragment);
  });
}

function fillLinkValue(container, href, label) {
  if (!href) {
    container.textContent = "未設定";
    return;
  }
  const link = document.createElement("a");
  link.href = href;
  link.target = "_blank";
  link.rel = "noreferrer";
  link.textContent = label;
  container.replaceChildren(link);
}

function createOption(value, label) {
  const option = document.createElement("option");
  option.value = value;
  option.textContent = label;
  return option;
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