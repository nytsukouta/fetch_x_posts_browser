const DATA_URL = "../data/output/schedule_list.json";

const state = {
  items: [],
  filteredItems: [],
};

const elements = {
  countValue: document.getElementById("countValue"),
  generatedAt: document.getElementById("generatedAt"),
  monthFilter: document.getElementById("monthFilter"),
  locationFilter: document.getElementById("locationFilter"),
  searchInput: document.getElementById("searchInput"),
  resultSummary: document.getElementById("resultSummary"),
  scheduleGrid: document.getElementById("scheduleGrid"),
  cardTemplate: document.getElementById("cardTemplate"),
};

async function main() {
  bindEvents();

  try {
    const response = await fetch(DATA_URL, { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`failed to load schedule data: ${response.status}`);
    }

    const payload = await response.json();
    state.items = Array.isArray(payload.items) ? payload.items : [];
    elements.countValue.textContent = String(payload.count ?? state.items.length);
    elements.generatedAt.textContent = formatGeneratedAt(payload.generated_at);

    populateFilters(state.items);
    applyFilters();
  } catch (error) {
    elements.resultSummary.textContent = "データを読み込めませんでした。HTTP サーバー経由で開いているか確認してください。";
    elements.scheduleGrid.innerHTML = `<section class="empty-state"><p>${escapeHtml(String(error))}</p></section>`;
  }
}

function bindEvents() {
  elements.searchInput.addEventListener("input", applyFilters);
  elements.monthFilter.addEventListener("change", applyFilters);
  elements.locationFilter.addEventListener("change", applyFilters);
}

function populateFilters(items) {
  const months = unique(items.map((item) => extractMonth(item.performance_schedule)).filter(Boolean));
  const locations = unique(items.map((item) => item.normalized_location).filter(Boolean));

  for (const month of months) {
    elements.monthFilter.append(createOption(month, month));
  }

  for (const location of locations) {
    elements.locationFilter.append(createOption(location, location));
  }
}

function applyFilters() {
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
  elements.resultSummary.textContent = `${state.filteredItems.length} 件を表示中 / 全 ${state.items.length} 件`;
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

    fragment.querySelector(".event-chip").textContent = buildReferenceLabel(item.official_reference_type);
    fragment.querySelector(".event-date").textContent = item.performance_schedule || "日程未設定";
    fragment.querySelector(".event-title").textContent = item.event_name || item.organization_name || "名称未設定";
    fragment.querySelector(".organization-name").textContent = item.organization_name || "未設定";
    fragment.querySelector(".venue-name").textContent = item.venue_name || "未設定";
    fragment.querySelector(".location-name").textContent = item.normalized_location || "未設定";

    const primaryLink = fragment.querySelector(".primary-link");
    if (item.official_reference_url) {
      primaryLink.href = item.official_reference_url;
      primaryLink.textContent = buildReferenceCta(item.official_reference_type);
    } else {
      primaryLink.removeAttribute("href");
      primaryLink.textContent = "参照先なし";
      primaryLink.setAttribute("aria-disabled", "true");
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

function buildReferenceLabel(referenceType) {
  if (!referenceType) {
    return "参照先なし";
  }
  if (referenceType.startsWith("organization_official") || referenceType.startsWith("venue_official")) {
    return "公式リンク";
  }
  return "X候補";
}

function buildReferenceCta(referenceType) {
  if (referenceType.startsWith("organization_official") || referenceType.startsWith("venue_official")) {
    return "公式情報を見る";
  }
  return "候補アカウントを見る";
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

main();