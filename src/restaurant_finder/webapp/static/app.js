"use strict";

/**
 * Logique du panel web Restaurant Finder.
 *
 * Volontairement en JavaScript "vanilla" (pas de framework, pas de build) :
 * cohérent avec un projet Python léger, sans étape de compilation à gérer.
 */

const state = {
  cities: [],
  points: [], // { id, lat, lng, radius, marker, circle }
};

let map;
let nextPointId = 1;

// ---------------------------------------------------------------------------
// Initialisation
// ---------------------------------------------------------------------------

document.addEventListener("DOMContentLoaded", async () => {
  initMap();
  bindStaticControls();
  await loadCategories();
  await loadDefaults();
});

function initMap() {
  map = L.map("map").setView([46.6, 2.5], 6); // Centré sur la France.

  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: "&copy; contributeurs OpenStreetMap",
  }).addTo(map);

  map.on("click", (event) => addPoint(event.latlng.lat, event.latlng.lng));
}

function bindStaticControls() {
  document.getElementById("add-city-btn").addEventListener("click", addCityFromInput);
  document.getElementById("city-input").addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      addCityFromInput();
    }
  });

  document.getElementById("toggle-options").addEventListener("click", () => {
    const body = document.getElementById("options-body");
    const icon = document.getElementById("toggle-icon");
    body.classList.toggle("collapsed");
    icon.textContent = body.classList.contains("collapsed") ? "▸" : "▾";
  });

  document.getElementById("toggle-instagram").addEventListener("change", (event) => {
    document.getElementById("instagram-options").classList.toggle("hidden", !event.target.checked);
  });

  document.getElementById("search-btn").addEventListener("click", startSearch);
  document.getElementById("reset-btn").addEventListener("click", resetAll);
  document.getElementById("close-results").addEventListener("click", () => {
    document.getElementById("results-panel").classList.add("hidden");
  });
}

async function loadCategories() {
  try {
    const response = await fetch("/api/categories");
    const categories = await response.json();
    const container = document.getElementById("category-checkboxes");
    container.innerHTML = "";

    const defaultChecked = new Set(["restaurant", "cafe"]);
    for (const [value, label] of Object.entries(categories)) {
      const wrapper = document.createElement("label");
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.value = value;
      checkbox.className = "category-checkbox";
      checkbox.checked = defaultChecked.has(value);
      wrapper.appendChild(checkbox);
      wrapper.appendChild(document.createTextNode(" " + label));
      container.appendChild(wrapper);
    }
  } catch (error) {
    console.error("Impossible de charger les catégories.", error);
  }
}

async function loadDefaults() {
  try {
    const response = await fetch("/api/defaults");
    const defaults = await response.json();
    if (defaults.radius_meters) {
      document.getElementById("default-radius").value = defaults.radius_meters;
    }
    if (defaults.max_followers) {
      document.getElementById("max-followers-input").value = defaults.max_followers;
    }
    if (defaults.max_post_age_days) {
      document.getElementById("max-post-age-days-input").value = defaults.max_post_age_days;
    }
  } catch (error) {
    console.error("Impossible de charger les valeurs par défaut.", error);
  }
}

// ---------------------------------------------------------------------------
// Villes
// ---------------------------------------------------------------------------

function addCityFromInput() {
  const input = document.getElementById("city-input");
  const value = input.value.trim();
  if (!value) return;

  if (!state.cities.some((city) => city.toLowerCase() === value.toLowerCase())) {
    state.cities.push(value);
    renderCities();
  }
  input.value = "";
  input.focus();
}

function removeCity(city) {
  state.cities = state.cities.filter((item) => item !== city);
  renderCities();
}

function renderCities() {
  const list = document.getElementById("city-list");
  list.innerHTML = "";

  for (const city of state.cities) {
    const item = document.createElement("li");
    item.className = "chip";
    item.innerHTML = `<span>${escapeHtml(city)}</span>`;

    const removeBtn = document.createElement("button");
    removeBtn.type = "button";
    removeBtn.textContent = "×";
    removeBtn.title = "Retirer";
    removeBtn.addEventListener("click", () => removeCity(city));

    item.appendChild(removeBtn);
    list.appendChild(item);
  }
}

// ---------------------------------------------------------------------------
// Points sur la carte
// ---------------------------------------------------------------------------

function addPoint(lat, lng) {
  const defaultRadius = Number(document.getElementById("default-radius").value) || 800;
  const id = nextPointId++;

  const marker = L.marker([lat, lng]).addTo(map);
  const circle = L.circle([lat, lng], {
    radius: defaultRadius,
    color: "#ff6b35",
    fillColor: "#ff6b35",
    fillOpacity: 0.12,
    weight: 2,
  }).addTo(map);

  marker.bindPopup(buildPopupContent(id));
  marker.on("click", () => map.panTo([lat, lng]));

  const point = { id, lat, lng, radius: defaultRadius, marker, circle };
  state.points.push(point);
  renderPoints();
}

function buildPopupContent(id) {
  const wrapper = document.createElement("div");
  const button = document.createElement("button");
  button.textContent = "Supprimer ce lieu";
  button.className = "btn btn--ghost btn--small";
  button.addEventListener("click", () => removePoint(id));
  wrapper.appendChild(button);
  return wrapper;
}

function removePoint(id) {
  const point = state.points.find((item) => item.id === id);
  if (!point) return;

  map.removeLayer(point.marker);
  map.removeLayer(point.circle);
  state.points = state.points.filter((item) => item.id !== id);
  renderPoints();
}

function updatePointRadius(id, radius) {
  const point = state.points.find((item) => item.id === id);
  if (!point) return;

  point.radius = radius;
  point.circle.setRadius(radius);
}

function renderPoints() {
  const list = document.getElementById("point-list");
  list.innerHTML = "";

  if (state.points.length === 0) {
    const hint = document.createElement("li");
    hint.className = "empty-hint";
    hint.textContent = "Aucun lieu ajouté pour l'instant.";
    list.appendChild(hint);
    return;
  }

  state.points.forEach((point, index) => {
    const item = document.createElement("li");
    item.className = "point-item";

    const coords = document.createElement("span");
    coords.className = "point-item__coords";
    coords.textContent = `#${index + 1} (${point.lat.toFixed(4)}, ${point.lng.toFixed(4)})`;

    const radiusInput = document.createElement("input");
    radiusInput.type = "number";
    radiusInput.min = "50";
    radiusInput.step = "50";
    radiusInput.value = point.radius;
    radiusInput.title = "Rayon en mètres";
    radiusInput.addEventListener("change", () => {
      const value = Math.max(50, Number(radiusInput.value) || point.radius);
      radiusInput.value = value;
      updatePointRadius(point.id, value);
    });

    const unit = document.createElement("span");
    unit.className = "unit";
    unit.textContent = "m";

    const removeBtn = document.createElement("button");
    removeBtn.type = "button";
    removeBtn.textContent = "×";
    removeBtn.title = "Retirer ce lieu";
    removeBtn.addEventListener("click", () => removePoint(point.id));

    item.append(coords, radiusInput, unit, removeBtn);
    list.appendChild(item);
  });
}

// ---------------------------------------------------------------------------
// Réinitialisation
// ---------------------------------------------------------------------------

function resetAll() {
  for (const point of state.points) {
    map.removeLayer(point.marker);
    map.removeLayer(point.circle);
  }
  state.points = [];
  state.cities = [];
  renderPoints();
  renderCities();
  document.getElementById("results-panel").classList.add("hidden");
  document.getElementById("status-card").classList.add("hidden");
  document.getElementById("error-card").classList.add("hidden");
}

// ---------------------------------------------------------------------------
// Recherche
// ---------------------------------------------------------------------------

function collectPayload() {
  const categories = Array.from(document.querySelectorAll(".category-checkbox:checked")).map(
    (checkbox) => checkbox.value
  );
  const formats = [];
  if (document.getElementById("format-csv").checked) formats.push("csv");
  if (document.getElementById("format-xlsx").checked) formats.push("xlsx");

  const limitValue = document.getElementById("limit-input").value;

  return {
    cities: state.cities,
    points: state.points.map((point) => ({
      latitude: point.lat,
      longitude: point.lng,
      radius_meters: point.radius,
    })),
    categories,
    limit: limitValue ? Number(limitValue) : null,
    formats,
    enrich_instagram: document.getElementById("toggle-instagram").checked,
    only_with_instagram: document.getElementById("only-with-instagram").checked,
    include_chains: document.getElementById("include-chains").checked,
    max_followers: Number(document.getElementById("max-followers-input").value) || 1000,
    keep_unknown_followers: document.getElementById("keep-unknown-followers").checked,
    max_post_age_days: (() => {
      const ageInput = document.getElementById("max-post-age-days-input");
      if (!ageInput) return null;
      const rawAge = String(ageInput.value || "").trim();
      if (!rawAge) return null;
      const parsed = Number(rawAge);
      return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
    })(),
  };
}

async function startSearch() {
  hideError();

  if (state.cities.length === 0 && state.points.length === 0) {
    showError("Ajoute au moins une ville ou clique sur la carte pour ajouter un lieu.");
    return;
  }

  const payload = collectPayload();
  if (payload.formats.length === 0) {
    showError("Choisis au moins un format d'export (CSV et/ou Excel).");
    return;
  }

  setSearching(true);
  showStatus("Lancement de la recherche...", 0, 0);
  document.getElementById("results-panel").classList.add("hidden");

  try {
    const response = await fetch("/api/search", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.detail || "La recherche n'a pas pu démarrer.");
    }

    const { job_id: jobId } = await response.json();
    await pollJob(jobId);
  } catch (error) {
    showError(error.message || String(error));
    setSearching(false);
  }
}

function pollJob(jobId) {
  return new Promise((resolve) => {
    const interval = setInterval(async () => {
      try {
        const response = await fetch(`/api/jobs/${jobId}`);
        if (!response.ok) {
          throw new Error("Recherche introuvable.");
        }
        const job = await response.json();

        showStatus(job.message, job.progress_done, job.progress_total);

        if (job.status === "done") {
          clearInterval(interval);
          setSearching(false);
          hideStatus();
          renderResults(jobId, job);
          resolve();
        } else if (job.status === "error") {
          clearInterval(interval);
          setSearching(false);
          hideStatus();
          showError(job.error || "Une erreur inconnue est survenue.");
          resolve();
        }
      } catch (error) {
        clearInterval(interval);
        setSearching(false);
        hideStatus();
        showError(error.message || String(error));
        resolve();
      }
    }, 1000);
  });
}

// ---------------------------------------------------------------------------
// Affichage : statut, erreurs, résultats
// ---------------------------------------------------------------------------

function setSearching(isSearching) {
  document.getElementById("search-btn").disabled = isSearching;
}

function showStatus(message, done, total) {
  const card = document.getElementById("status-card");
  card.classList.remove("hidden");
  document.getElementById("status-message").textContent = message || "En cours...";

  const fill = document.getElementById("progress-fill");
  const percent = total > 0 ? Math.min(100, Math.round((done / total) * 100)) : 0;
  fill.style.width = `${percent}%`;
}

function hideStatus() {
  document.getElementById("status-card").classList.add("hidden");
}

function showError(message) {
  const card = document.getElementById("error-card");
  card.classList.remove("hidden");
  document.getElementById("error-message").textContent = message;
}

function hideError() {
  document.getElementById("error-card").classList.add("hidden");
}

function renderResults(jobId, job) {
  const panel = document.getElementById("results-panel");
  const title = document.getElementById("results-title");
  const body = document.getElementById("results-body");
  const downloadButtons = document.getElementById("download-buttons");

  title.textContent = `Résultats (${job.results.length})`;
  body.innerHTML = "";

  for (const row of job.results) {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${escapeHtml(row.name)}</td>
      <td>${row.instagram ? "@" + escapeHtml(row.instagram) : "—"}</td>
      <td>${row.instagram_followers ?? "—"}</td>
      <td>${escapeHtml(row.instagram_confidence) || "—"}</td>
      <td>${escapeHtml(row.activity_status) || "—"}</td>
      <td>${escapeHtml(row.city)}</td>
      <td>${escapeHtml(row.category)}</td>
    `;
    body.appendChild(tr);
  }

  downloadButtons.innerHTML = "";
  for (const format of job.formats) {
    const link = document.createElement("a");
    link.href = `/api/jobs/${jobId}/download/${format}`;
    link.className = "btn btn--secondary btn--small";
    link.textContent = format === "xlsx" ? "Télécharger Excel" : "Télécharger CSV";
    downloadButtons.appendChild(link);
  }

  panel.classList.remove("hidden");
}

function escapeHtml(value) {
  const div = document.createElement("div");
  div.textContent = value ?? "";
  return div.innerHTML;
}
