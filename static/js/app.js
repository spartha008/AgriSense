/* ==========================================================================
   AgriSense - Intelligent Farming Assistant  (front end)
   ========================================================================== */
(function () {
  "use strict";

  /* ------------------------------------------------------------------ utils */

  const $ = (sel, root) => (root || document).querySelector(sel);
  const $$ = (sel, root) => Array.from((root || document).querySelectorAll(sel));

  const state = {
    overview: null,
    crops: [],
    cropDetail: {},
    diseaseMeta: null,
    irrigation: null,
    weather: null,
    weatherParams: null,
    location: null,
    diagImage: null,
    storageKey: "agrisense.v1",
  };

  function esc(value) {
    return String(value === null || value === undefined ? "" : value)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  function num(value, digits) {
    if (value === null || value === undefined || value === "") return "—";
    const n = Number(value);
    if (Number.isNaN(n)) return "—";
    return n.toFixed(digits === undefined ? 1 : digits).replace(/\.0+(?=$)/, "");
  }

  function titleCase(text) {
    return String(text || "").replace(/\b\w/g, (c) => c.toUpperCase());
  }

  async function api(path, options) {
    const response = await fetch(path, options);
    let data = null;
    try { data = await response.json(); } catch (e) { data = null; }
    if (!response.ok || (data && data.ok === false)) {
      const message = (data && (data.error || (data.detail && data.detail.error)))
        || ("Request failed (" + response.status + ")");
      throw new Error(message);
    }
    return data;
  }

  let toastTimer = null;
  function toast(message, isError) {
    const node = $("#toast");
    node.textContent = message;
    node.className = "toast" + (isError ? " err" : "");
    node.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { node.hidden = true; }, 4200);
  }

  function spinner(label) {
    return '<div class="loader"><span class="spinner"></span>' + esc(label || "Working…") + "</div>";
  }

  function saveState() {
    try {
      localStorage.setItem(state.storageKey, JSON.stringify({
        location: state.location,
        crop: $("#advCrop") ? $("#advCrop").value : "",
      }));
    } catch (e) { /* storage disabled */ }
  }

  function loadState() {
    try { return JSON.parse(localStorage.getItem(state.storageKey) || "{}"); }
    catch (e) { return {}; }
  }

  /* ------------------------------------------------------------------ nav */

  const VIEW_TITLES = {
    dashboard: "Dashboard",
    crops: "Crop Guide",
    weather: "Weather Advisory",
    irrigation: "Irrigation Planner",
    disease: "Disease Centre",
    tips: "Tips & Season",
  };

  function goto(view) {
    $$(".view").forEach((node) => node.classList.toggle("active", node.id === "view-" + view));
    $$(".nav-item").forEach((node) => node.classList.toggle("active", node.dataset.view === view));
    $("#topbarTitle").textContent = VIEW_TITLES[view] || "AgriSense";
    $("#sidebar").classList.remove("open");
    window.scrollTo({ top: 0, behavior: "smooth" });
    if (location.hash.slice(1) !== view) history.replaceState(null, "", "#" + view);
  }

  document.addEventListener("click", (event) => {
    const navBtn = event.target.closest(".nav-item");
    if (navBtn) { goto(navBtn.dataset.view); return; }
    const gotoBtn = event.target.closest("[data-goto]");
    if (gotoBtn) { goto(gotoBtn.dataset.goto); return; }
    if (event.target.closest("[data-close]")) { closeModal(); }
    if (event.target === $("#modal")) { closeModal(); }
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeModal();
  });

  $("#menuBtn").addEventListener("click", () => $("#sidebar").classList.toggle("open"));

  /* ------------------------------------------------------------------ modal */

  function openModal(html) {
    $("#modalBody").innerHTML = html;
    $("#modal").hidden = false;
    document.body.style.overflow = "hidden";
  }

  function closeModal() {
    $("#modal").hidden = true;
    document.body.style.overflow = "";
  }

  /* ------------------------------------------------------------------ boot */

  async function boot() {
    try {
      state.overview = await api("/api/overview");
    } catch (error) {
      toast("Could not load the knowledge base: " + error.message, true);
      return;
    }

    state.crops = state.overview.crops || [];
    renderDashboard(state.overview);
    fillCropSelects();
    renderQuickPlaces(state.overview.locations || []);

    const hash = location.hash.slice(1);
    if (VIEW_TITLES[hash]) goto(hash);

    const saved = loadState();
    if (saved.location && saved.location.label) {
      state.location = saved.location;
      $("#locInput").value = saved.location.label;
    }
    if (saved.crop && $("#advCrop")) $("#advCrop").value = saved.crop;

    initCrops();
    initWeather();
    initIrrigation();
    initDisease();
    initTips();
  }

  function fillCropSelects() {
    const options = state.crops
      .map((c) => '<option value="' + esc(c.id) + '">' + esc(c.emoji + "  " + c.name) + "</option>")
      .join("");
    [["#advCrop", "Any crop"], ["#diagCrop", "Detect from image / any crop"],
     ["#disCrop", "All crops"]].forEach(([sel, label]) => {
      const node = $(sel);
      if (node) node.innerHTML = '<option value="">' + esc(label) + "</option>" + options;
    });
    const irr = $("#irrCrop");
    if (irr) irr.innerHTML = '<option value="">General / no crop</option>' + options;
    const cat = $("#cropCategory");
    if (cat) {
      const cats = Array.from(new Set(state.crops.map((c) => c.category))).sort();
      cat.innerHTML = '<option value="">All categories</option>' +
        cats.map((c) => '<option value="' + esc(c) + '">' + esc(c) + "</option>").join("");
    }
  }

  /* ------------------------------------------------------------------ dashboard */

  function renderDashboard(data) {
    const stats = data.stats || {};
    $("#statRow").innerHTML = [
      ["Crops covered", stats.crops, "🌾"],
      ["Diseases documented", stats.diseases, "🔬"],
      ["Practical tips", stats.tips, "💡"],
      ["Season months", stats.months, "📅"],
    ].map(([label, value, icon]) =>
      '<div class="stat"><div class="val">' + esc(value) + "</div>" +
      '<div class="lbl">' + esc(icon + " " + label) + "</div></div>").join("");

    const season = data.seasonal || {};
    $("#seasonTag").textContent = season.season || "";
    $("#seasonBody").innerHTML =
      '<div class="season-meta">' +
        '<span class="badge">' + esc(season.month_name) + "</span>" +
        '<span class="badge neutral">' + esc(season.season) + " season</span>" +
        (season.is_current_month && season.days_left
          ? '<span class="badge soft">' + esc(season.days_left) + " days left</span>" : "") +
      "</div>" +
      '<p class="season-focus">' + esc(season.focus) + "</p>" +
      '<div class="season-block"><h4>Do now</h4><ul class="season-list">' +
        (season.care || []).slice(0, 4).map((x) => "<li>" + esc(x) + "</li>").join("") +
      "</ul></div>" +
      '<div class="season-block"><h4>Watch out for</h4><ul class="season-list">' +
        (season.watch || []).slice(0, 3).map((x) => "<li>" + esc(x) + "</li>").join("") +
      "</ul></div>" +
      (season.irrigation_hint
        ? '<div class="disclaimer">💧 ' + esc(season.irrigation_hint) + "</div>" : "");

    $("#dashTips").innerHTML = '<div class="grid two">' + (data.tips || []).map(tipCard).join("") + "</div>";

    updateTopbar(null);
  }

  function tipCard(tip) {
    return '<article class="tip-card"><span class="tip-cat">' + esc(tip.category) + "</span>" +
      "<h3>" + esc(tip.title) + "</h3><p>" + esc(tip.body) + "</p></article>";
  }

  function updateTopbar(summary) {
    const dot = $("#liveDot");
    const sub = $("#topbarSub");
    if (!summary) {
      dot.className = "live-dot";
      sub.textContent = "Knowledge base ready";
      return;
    }
    if (summary.estimated) {
      dot.className = "live-dot demo";
      sub.textContent = summary.label + " (offline estimate)";
    } else {
      dot.className = "live-dot on";
      sub.textContent = summary.label + " · " + num(summary.temp, 0) + "°C";
    }
  }

  /* ------------------------------------------------------------------ crops */

  function initCrops() {
    $("#cropSearch").addEventListener("input", renderCropGrid);
    $("#cropCategory").addEventListener("change", renderCropGrid);
    renderCropGrid();
  }

  function renderCropGrid() {
    const query = $("#cropSearch").value.trim().toLowerCase();
    const category = $("#cropCategory").value;
    const items = state.crops.filter((c) => {
      if (category && c.category !== category) return false;
      if (!query) return true;
      return [c.name, c.local_names, c.scientific, c.category, c.season]
        .join(" ").toLowerCase().indexOf(query) !== -1;
    });

    $("#cropGrid").innerHTML = items.length
      ? items.map(cropCard).join("")
      : '<div class="empty">No crop matches that search.</div>';

    $$("#cropGrid .crop-card").forEach((card) =>
      card.addEventListener("click", () => openCrop(card.dataset.id)));
  }

  function cropCard(crop) {
    const water = String(crop.water_requirement || "medium");
    const waterClass = /very/i.test(water) ? "very"
      : /\blow\b/i.test(water) ? "low"
      : /\bhigh\b/i.test(water) ? "high" : "medium";
    return '<article class="crop-card" data-id="' + esc(crop.id) + '">' +
      '<div class="crop-top"><div class="crop-emoji">' + esc(crop.emoji) + "</div>" +
      "<div><div class=\"crop-name\">" + esc(crop.name) + "</div>" +
      '<div class="crop-sub">' + esc(crop.scientific) + "</div></div></div>" +
      '<div class="crop-local">' + esc(crop.local_names) + "</div>" +
      '<div class="crop-tags">' +
        '<span class="badge soft">' + esc(crop.category) + "</span>" +
        '<span class="water-tag ' + esc(waterClass) + '">' + esc(water) + " water</span>" +
        (crop.duration_days ? '<span class="badge soft">' + esc(crop.duration_days) + "</span>" : "") +
      "</div></article>";
  }

  async function openCrop(id) {
    goto("crops");
    openModal('<div class="modal-body">' + spinner("Loading crop guide…") + "</div>");
    let crop = state.cropDetail[id];
    try {
      if (!crop) {
        const data = await api("/api/crops/" + encodeURIComponent(id));
        crop = data.crop;
        state.cropDetail[id] = crop;
      }
    } catch (error) {
      openModal('<div class="empty">Could not load this crop: ' + esc(error.message) + "</div>");
      return;
    }
    renderCropModal(crop);
  }

  function renderCropModal(crop) {
    const fert = (crop.fertilizer || []).map((f) =>
      '<tr><td><b>' + esc(f.stage) + "</b></td><td>" + esc(f.dose) + "</td><td>" + esc(f.notes) + "</td></tr>").join("");
    const irr = crop.irrigation || {};

    const html =
      '<div class="modal-hero"><div class="crop-emoji">' + esc(crop.emoji) + "</div>" +
      "<div><h2>" + esc(crop.name) + "</h2>" +
      '<div class="crop-sub">' + esc(crop.scientific) + "</div>" +
      '<div class="crop-local">' + esc(crop.local_names) + "</div></div></div>" +

      '<div class="tab-row" data-tabs>' +
        '<button class="tab active" data-tab="overview">Overview</button>' +
        '<button class="tab" data-tab="care">Care &amp; fertiliser</button>' +
        '<button class="tab" data-tab="water">Irrigation</button>' +
        '<button class="tab" data-tab="health">Pests &amp; diseases</button>' +
      "</div>" +

      '<div class="tab-panel" data-panel="overview">' +
        '<div class="kv">' +
          kv("Season", crop.season) + kv("Sowing window", crop.sowing_window) +
          kv("Harvest", crop.harvest_window) + kv("Crop duration", crop.duration_days) +
          kv("Soil", crop.soil) + kv("Soil pH", crop.soil_ph) +
          kv("Climate", crop.climate) + kv("Rainfall need", crop.rainfall_mm + " mm") +
          kv("Water requirement", titleCase(crop.water_requirement)) +
          kv("Spacing", crop.spacing) + kv("Seed rate", crop.seed_rate) +
          kv("Sowing depth", crop.sowing_depth) +
        "</div>" +
        '<div class="field-label" style="margin-top:16px">Field notes</div>' +
        '<ul class="season-list">' + (crop.tips || []).map((t) => "<li>" + esc(t) + "</li>").join("") + "</ul>" +
        '<div class="disclaimer">Expected yield: <b>' + esc(crop.expected_yield) + "</b></div>" +
      "</div>" +

      '<div class="tab-panel" data-panel="care" hidden>' +
        '<div class="field-label">Fertiliser schedule</div>' +
        '<div style="overflow-x:auto"><table class="tbl"><thead><tr><th>Stage</th><th>Dose</th><th>Notes</th></tr></thead>' +
        "<tbody>" + fert + "</tbody></table></div>" +
        '<div class="field-label" style="margin-top:18px">Crop care practices</div>' +
        '<ul class="advice-list">' + (crop.care || []).map((c) => "<li><span>" + esc(c) + "</span></li>").join("") + "</ul>" +
      "</div>" +

      '<div class="tab-panel" data-panel="water" hidden>' +
        '<div class="kv">' +
          kv("Method", irr.method) +
          kv("Water need", titleCase(crop.water_requirement)) +
          kv("Critical stages", (irr.critical_stages || []).join(", ")) +
        "</div>" +
        '<div class="field-label" style="margin-top:16px">Irrigation guidance</div>' +
        '<ul class="advice-list">' + (irr.tips || []).map((t) => "<li><span>" + esc(t) + "</span></li>").join("") + "</ul>" +
        '<div style="margin-top:16px"><button class="btn primary" data-goto="irrigation" type="button">Open the irrigation planner</button></div>' +
      "</div>" +

      '<div class="tab-panel" data-panel="health" hidden>' +
        '<div class="field-label">Common pests</div>' +
        '<div class="chip-row">' + (crop.common_pests || []).map((p) =>
          '<span class="badge neutral">' + esc(p) + "</span>").join("") + "</div>" +
        '<div class="field-label" style="margin-top:18px">Diseases to watch (' +
          (crop.disease_details || []).length + ")</div>" +
        '<div class="dis-list">' + (crop.disease_details || []).map((d) =>
          '<div class="dis-card" data-disease="' + esc(d.id) + '">' +
            '<div class="d-name">' + esc(d.name) + "</div>" +
            '<div class="d-path">' + esc(d.pathogen_type) + " &middot; " + esc(d.pathogen) + "</div>" +
            '<div class="d-over">' + esc(d.overview) + "</div>" +
            '<div class="d-foot"><span class="badge ' + esc(d.severity) + '">' + esc(d.severity) + " impact</span></div>" +
          "</div>").join("") + "</div>" +
        '<div class="field-label" style="margin-top:18px">Harvest</div>' +
        '<p class="muted">' + esc(crop.harvest_notes) + "</p>" +
      "</div>";

    openModal(html);

    $$("#modalBody [data-tabs] .tab").forEach((tab) => {
      tab.addEventListener("click", () => {
        $$("#modalBody [data-tabs] .tab").forEach((t) => t.classList.toggle("active", t === tab));
        $$("#modalBody .tab-panel").forEach((panel) =>
          { panel.hidden = panel.dataset.panel !== tab.dataset.tab; });
      });
    });
    $$("#modalBody [data-disease]").forEach((card) =>
      card.addEventListener("click", () => openDisease(card.dataset.disease)));
  }

  function kv(key, value) {
    return '<div><div class="k">' + esc(key) + '</div><div class="v">' +
      esc(value === null || value === undefined || value === "" ? "—" : value) + "</div></div>";
  }

  /* ------------------------------------------------------------------ weather */

  function renderQuickPlaces(locations) {
    $("#quickPlaces").innerHTML = locations.slice(0, 7).map((loc, index) =>
      '<button class="chip" data-place="' + index + '">📍 ' + esc(loc.label.split(",").slice(0, 2).join(",")) + "</button>"
    ).join("");
    $$("#quickPlaces .chip").forEach((chip) =>
      chip.addEventListener("click", () => {
        const loc = locations[Number(chip.dataset.place)];
        state.location = loc;
        $("#locInput").value = loc.label;
        loadWeather();
      }));
  }

  function initWeather() {
    $("#weatherBtn").addEventListener("click", () => {
      const text = $("#locInput").value.trim();
      if (text && (!state.location || state.location.label !== text)) state.location = null;
      loadWeather(text);
    });
    $("#locInput").addEventListener("keydown", (event) => {
      if (event.key === "Enter") { event.preventDefault(); $("#weatherBtn").click(); }
    });
    $("#geoBtn").addEventListener("click", useGeolocation);
    $("#advCrop").addEventListener("change", () => { if (state.weather) loadWeather(); });
    $("#advStage").addEventListener("change", () => { if (state.weather) loadWeather(); });

    let debounce = null;
    $("#locInput").addEventListener("input", () => {
      state.location = null;
      clearTimeout(debounce);
      const value = $("#locInput").value.trim();
      if (value.length < 2) { closeSuggest(); return; }
      debounce = setTimeout(() => suggest(value), 320);
    });
    document.addEventListener("click", (event) => {
      if (!event.target.closest(".ac-wrap")) closeSuggest();
    });
  }

  function closeSuggest() { $("#locSuggest").classList.remove("open"); }

  async function suggest(query) {
    let results = [];
    try {
      const data = await api("/api/locations?q=" + encodeURIComponent(query));
      results = data.locations || [];
    } catch (error) { results = (state.overview.locations || []); }
    if (!results.length) { closeSuggest(); return; }
    const box = $("#locSuggest");
    box.innerHTML = results.map((loc, index) =>
      '<div class="ac-item" data-i="' + index + '">' + esc(loc.name || loc.label) +
      "<small>" + esc([loc.admin1, loc.country].filter(Boolean).join(", ") || loc.label) + "</small></div>").join("");
    box.classList.add("open");
    box._results = results;
    $$(".ac-item", box).forEach((item) => item.addEventListener("click", () => {
      const loc = results[Number(item.dataset.i)];
      state.location = loc;
      $("#locInput").value = loc.label || loc.name;
      closeSuggest();
      loadWeather();
    }));
  }

  function useGeolocation() {
    if (!navigator.geolocation) { toast("Geolocation is not available in this browser.", true); return; }
    toast("Requesting your location…");
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        state.location = {
          label: "My location",
          latitude: pos.coords.latitude,
          longitude: pos.coords.longitude,
        };
        $("#locInput").value = "My location";
        loadWeather();
      },
      () => toast("Could not get your location. Please type a place name instead.", true),
      { timeout: 10000 }
    );
  }

  async function loadWeather(explicitText) {
    const text = explicitText !== undefined ? explicitText : $("#locInput").value.trim();
    const params = new URLSearchParams();
    if (state.location && state.location.latitude !== undefined && state.location.latitude !== null) {
      params.set("lat", state.location.latitude);
      params.set("lon", state.location.longitude);
      params.set("label", state.location.label || "Selected location");
    } else if (text) {
      params.set("location", text);
    } else {
      toast("Enter a place name first.", true);
      return;
    }
    const crop = $("#advCrop").value;
    const stage = $("#advStage").value;
    if (crop) params.set("crop", crop);
    if (stage) params.set("stage", stage);

    $("#weatherOut").innerHTML = spinner("Fetching the forecast and building your advisory…");
    try {
      const data = await api("/api/weather?" + params.toString());
      state.weather = data;
      state.weatherParams = { crop, stage };
      if (!state.location || !state.location.label) {
        state.location = {
          label: data.forecast.location.label,
          latitude: data.forecast.location.latitude,
          longitude: data.forecast.location.longitude,
        };
      }
      if (data.forecast.estimated) {
        $("#liveDot").className = "live-dot demo";
      }
      renderWeather(data);
      updateTopbar({
        estimated: data.forecast.estimated,
        label: data.forecast.location.label,
        temp: data.forecast.current.temperature,
      });
      updateSidebarWeather(data);
      saveState();
      autoFillIrrigation(data);
    } catch (error) {
      $("#weatherOut").innerHTML = '<div class="empty">⚠️ ' + esc(error.message) + "</div>";
    }
  }

  function updateSidebarWeather(data) {
    const c = data.forecast.current;
    $("#sidebarWeather").innerHTML =
      '<div class="mini-title">' + esc(data.forecast.location.label.split(",")[0]) + "</div>" +
      '<div class="mini-body"><div class="big">' + esc(num(c.temperature, 0)) + "°C " +
      esc(c.weather.icon) + "</div>" +
      esc(c.weather.label) + "<br>Humidity " + esc(num(c.humidity, 0)) + "% · Wind " +
      esc(num(c.wind_speed, 0)) + " km/h</div>";
  }

  function renderWeather(data) {
    const f = data.forecast;
    const c = f.current;
    const out = [];

    if (f.estimated) {
      out.push('<div class="wx-banner"><span>📴</span><div><b>Offline climate-normal estimate.</b> ' +
        "The live weather service could not be reached, so typical conditions for this place and " +
        "month are shown instead. " + esc(f.estimate_reason || "") +
        " Treat these numbers as indicative, not as a forecast.</div></div>");
    }

    out.push('<div class="wx-current">' +
      '<div class="wx-now">' +
        '<div class="wx-loc">📍 ' + esc(f.location.label) +
          (f.location.timezone ? " · " + esc(f.location.timezone) : "") + "</div>" +
        '<div class="wx-temp">' + esc(num(c.temperature, 1)) + '<small>°C</small></div>' +
        '<div class="wx-desc">' + esc(c.weather.icon + "  " + c.weather.label) +
          " · feels like " + esc(num(c.feels_like, 1)) + "°C</div>" +
      "</div>" +
      '<div class="wx-metrics">' +
        wxMetric("Humidity", num(c.humidity, 0) + " %") +
        wxMetric("Wind", num(c.wind_speed, 0) + " km/h") +
        wxMetric("Gusts", num(c.wind_gusts, 0) + " km/h") +
        wxMetric("Cloud", num(c.cloud_cover, 0) + " %") +
        wxMetric("Rain now", num(c.precipitation, 1) + " mm") +
        wxMetric("Soil temp", num(c.soil_temperature, 1) + " °C") +
        wxMetric("ET₀ today", num(c.et0, 1) + " mm") +
        wxMetric("Pressure", num(c.pressure, 0) + " hPa") +
      "</div></div>");

    out.push('<div class="day-row">' + f.daily.slice(0, 7).map((d, index) => {
      const advice = data.daily[index] || {};
      return '<div class="day ' + esc(advice.level || "good") + '">' +
        '<div class="d-name">' + esc(d.is_today ? "Today" : d.weekday) + "</div>" +
        '<div class="d-date">' + esc(d.day + " " + d.month) + "</div>" +
        '<div class="d-ico">' + esc(d.weather.icon) + "</div>" +
        '<div class="d-temp">' + esc(num(d.temp_max, 0)) + "° / " + esc(num(d.temp_min, 0)) + "°</div>" +
        '<div class="d-rain">💧 ' + esc(num(d.precipitation_sum, 1)) + " mm" +
          (d.precipitation_probability_max !== null && d.precipitation_probability_max !== undefined
            ? " (" + esc(num(d.precipitation_probability_max, 0)) + "%)" : "") + "</div>" +
        '<div class="d-wind">🌬 ' + esc(num(d.wind_max, 0)) + " km/h</div>" +
      "</div>";
    }).join("") + "</div>");

    out.push('<div class="card"><div class="card-head"><h2>Field advisory</h2>' +
      '<span class="muted">' + esc(data.alerts.length) + " alerts</span></div><div class=\"card-body\">" +
      '<div class="score-ring" style="margin-bottom:18px">' +
        '<div class="ring" style="--p:' + esc(data.score) + '"><span>' + esc(data.score) + "</span></div>" +
        "<div><h3 style=\"margin:0\">" + esc(data.headline) + "</h3>" +
        '<p class="muted" style="margin:4px 0 0">Working-conditions score for the next 7 days' +
        (data.crop ? " · tuned for " + esc(data.crop) : "") + "</p></div>" +
      "</div>" +
      '<div class="alert-list">' + (data.alerts.length ? data.alerts.map(alertHtml).join("")
        : '<div class="alert good"><span class="a-ico">✅</span><div><div class="a-title">No cautions</div>' +
          '<div class="a-msg">Conditions look normal for the week ahead.</div></div></div>') +
      "</div></div></div>");

    out.push('<div class="grid two">' +
      '<div class="card"><div class="card-head"><h2>Best spray windows</h2>' +
        '<span class="muted">Next 48 hours</span></div><div class="card-body">' +
        (data.spray_windows.length
          ? '<div class="alert-list">' + data.spray_windows.map((w) =>
              '<div class="alert good"><span class="a-ico">🕒</span><div>' +
              '<div class="a-title">' + esc(w.day) + " " + esc(w.date.slice(8)) + " · " + esc(w.window) + "</div>" +
              '<div class="a-msg">' + esc(w.reason) + "</div>" +
              '<div class="a-act">' + esc(w.hours) + " hour window with low wind and low rain risk.</div>" +
              "</div></div>").join("") + "</div>"
          : '<div class="empty">No good spray window in the next 48 hours. Wind, rain or humidity is unfavourable — postpone spraying.</div>') +
      "</div></div>" +

      '<div class="card"><div class="card-head"><h2>Disease pressure forecast</h2>' +
        '<span class="muted">Fungal/bacterial risk index</span></div><div class="card-body">' +
        '<div class="risk-bars">' + data.disease_risk.map((r) =>
          '<div class="risk-bar"><span>' + esc(r.weekday) + " " + esc(r.day) + "</span>" +
          '<div class="risk-track"><div class="risk-fill ' + esc(r.level) + '" style="width:' +
            esc(r.index || 0) + '%"></div></div>' +
          "<span>" + esc(r.index === null ? "—" : r.index) + "</span></div>").join("") +
        "</div>" +
        '<p class="muted" style="margin-top:12px">High values mean warm, humid weather with wet ' +
        "leaves — the conditions in which blight, blast, rust and downy mildew spread fastest. " +
        "Consider a preventive bio-fungicide or copper spray on susceptible crops.</p>" +
      "</div></div>" +

      '<div class="card"><div class="card-head"><h2>Water balance, next 7 days</h2></div>' +
      '<div class="card-body"><div class="kv">' +
        kv("Rain forecast", num(f.summary.rain_next_7d_mm, 1) + " mm") +
        kv("Rain last 3 days", f.summary.rain_past_3d_mm === null ? "—" : num(f.summary.rain_past_3d_mm, 1) + " mm") +
        kv("Crop water demand (ET₀)", num(f.summary.et0_next_7d_mm, 1) + " mm") +
        kv("Net balance", num(f.summary.water_balance_7d_mm, 1) + " mm") +
      "</div>" +
        '<p class="muted" style="margin-top:12px">A negative balance means the crop will need ' +
        "irrigation. Open the irrigation planner to convert this into a depth, an interval and a volume.</p>" +
        '<div style="margin-top:10px"><button class="btn ghost" data-goto="irrigation" type="button">Plan irrigation →</button></div>' +
      "</div></div>" +

      '<div class="card"><div class="card-head"><h2>Next 48 hours</h2></div><div class="card-body">' +
        '<div class="hour-strip">' + f.hourly.slice(0, 24).map((h) =>
          '<div class="hour"><div class="h-time">' + esc(h.hour) + "</div>" +
          '<div class="h-ico">' + esc(h.is_day ? "☀️" : "🌙") + "</div>" +
          '<div class="h-temp">' + esc(num(h.temperature, 0)) + "°</div>" +
          '<div class="h-rain">' + esc(num(h.precipitation_probability, 0)) + "%</div></div>").join("") +
        "</div></div></div>" + "</div>");

    out.push('<div class="card"><div class="card-head"><h2>Day-by-day action plan</h2></div>' +
      '<div class="card-body" style="overflow-x:auto"><table class="tbl"><thead><tr>' +
      "<th>Day</th><th>Weather</th><th>Max/Min</th><th>Rain</th><th>Wind</th><th>ET₀</th><th>What to do</th>" +
      "</tr></thead><tbody>" + data.daily.map((d) =>
        '<tr class="' + (d.is_today ? "irrigate" : "") + '"><td><b>' + esc(d.is_today ? "Today" : d.weekday) +
        "</b><br><small>" + esc(d.day + " " + d.month) + "</small></td>" +
        "<td>" + esc(d.icon + " " + d.label) + "</td>" +
        "<td>" + esc(num(d.temp_max, 0)) + "° / " + esc(num(d.temp_min, 0)) + "°</td>" +
        "<td>" + esc(num(d.rain, 1)) + " mm" +
          (d.rain_chance !== null && d.rain_chance !== undefined ? " <small>(" + esc(num(d.rain_chance, 0)) + "%)</small>" : "") + "</td>" +
        "<td>" + esc(num(d.wind, 0)) + " km/h</td>" +
        "<td>" + esc(d.et0 === null ? "—" : num(d.et0, 1)) + " mm</td>" +
        "<td>" + d.notes.map(esc).join("<br>") + "</td></tr>").join("") +
      "</tbody></table></div></div>");

    out.push('<p class="disclaimer">Weather data: ' + esc(f.source_label) +
      " (fetched " + esc(f.fetched_at.replace("T", " ")) + "). Advisory rules are guidance only — " +
      "always combine them with your own field observations and local extension advice.</p>");

    $("#weatherOut").innerHTML = out.join("");
  }

  function wxMetric(key, value) {
    return '<div class="wx-metric"><div class="k">' + esc(key) + '</div><div class="v">' + esc(value) + "</div></div>";
  }

  function alertHtml(alert) {
    return '<div class="alert ' + esc(alert.level) + '"><span class="a-ico">' + esc(alert.icon) + "</span><div>" +
      '<div class="a-title">' + esc(alert.title) + "</div>" +
      '<div class="a-msg">' + esc(alert.message) + "</div>" +
      '<div class="a-act">→ ' + esc(alert.action) + "</div></div></div>";
  }

  /* ------------------------------------------------------------------ irrigation */

  function initIrrigation() {
    api("/api/irrigation/options").then((data) => {
      const options = data.options;
      $("#irrStage").innerHTML = options.stages
        .map((s) => '<option value="' + esc(s.id) + '">' + esc(s.name) + "</option>").join("");
      $("#irrStage").value = "vegetative";
      $("#irrSoil").innerHTML = options.soils
        .map((s) => '<option value="' + esc(s.id) + '"' + (s.id === "loam" ? " selected" : "") + ">" +
          esc(s.label + " (" + s.awc + " mm/m)") + "</option>").join("");
      $("#irrMethod").innerHTML = options.methods
        .map((m) => '<option value="' + esc(m.id) + '"' + (m.id === "furrow" ? " selected" : "") + ">" +
          esc(m.label + " · " + m.efficiency + "% efficient") + "</option>").join("");
      $("#irrUnit").innerHTML = options.area_units
        .map((u) => '<option value="' + esc(u.id) + '">' + esc(u.label) + "</option>").join("");
    }).catch((error) => toast("Could not load irrigation options: " + error.message, true));

    $("#irrForm").addEventListener("submit", (event) => {
      event.preventDefault();
      runIrrigation();
    });

    $("#irrFromWeather").addEventListener("click", () => {
      if (!state.weather) { toast("Load a location in the Weather tab first.", true); return; }
      autoFillIrrigation(state.weather);
      toast("Filled in from " + state.weather.forecast.location.label);
    });
  }

  function autoFillIrrigation(data) {
    const d = data.irrigation_defaults || {};
    if (d.et0 !== null && d.et0 !== undefined) $("#irrEt0").value = Number(d.et0).toFixed(1);
    if (d.rain_forecast_mm !== null && d.rain_forecast_mm !== undefined) {
      $("#irrRain").value = Math.round(d.rain_forecast_mm);
    }
    if (d.rain_recent_mm !== null && d.rain_recent_mm !== undefined) {
      $("#irrRainRecent").value = Math.round(d.rain_recent_mm);
    }
    if (state.weatherParams && state.weatherParams.crop) $("#irrCrop").value = state.weatherParams.crop;
    if (state.weatherParams && state.weatherParams.stage) $("#irrStage").value = state.weatherParams.stage;
    $("#irrSync").textContent = "Synced with the forecast for " +
      (data.forecast ? data.forecast.location.label : "your location") +
      " (ET₀ " + num(d.et0, 1) + " mm, rain " + num(d.rain_forecast_mm, 0) + " mm next 7 days).";
  }

  async function runIrrigation() {
    const payload = {};
    const form = $("#irrForm");
    new FormData(form).forEach((value, key) => { payload[key] = value; });
    ["area", "et0", "rain_forecast_mm", "rain_recent_mm", "last_irrigation_days_ago"].forEach((key) => {
      payload[key] = payload[key] === "" ? null : Number(payload[key]);
    });
    payload.horizon_days = 7;

    $("#irrOut").innerHTML = spinner("Computing the water balance…");
    try {
      const data = await api("/api/irrigation", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      renderIrrigation(data.plan);
    } catch (error) {
      $("#irrOut").innerHTML = '<div class="empty">⚠️ ' + esc(error.message) + "</div>";
    }
  }

  function renderIrrigation(plan) {
    const rec = plan.recommendation;
    const use = plan.water_use;
    const soil = plan.soil;

    const statusMap = {
      irrigate_now: ["amber", "Irrigate now", "Soil moisture at the root zone is at or below the safe threshold."],
      scheduled: ["green", "Next irrigation in " + rec.days_to_irrigation + " day(s)", "Plan for " + rec.next_irrigation_date],
      no_irrigation: ["green", "No irrigation needed", "Forecast rainfall covers crop water demand right now."],
    };
    const [tone, big, small] = statusMap[rec.status] || statusMap.scheduled;

    const schedRows = plan.schedule.map((s) => {
      const cls = s.moisture_pct >= 60 ? "" : (s.moisture_pct >= 35 ? "warn" : "bad");
      return '<tr class="' + (s.irrigate ? "irrigate" : "") + '">' +
        "<td><b>" + esc(s.weekday) + "</b> <small>" + esc(s.day + " " + s.month) + "</small></td>" +
        "<td>" + esc(num(s.depletion_mm, 1)) + " mm</td>" +
        '<td><div class="moist-track"><div class="moist-fill ' + cls + '" style="width:' + esc(s.moisture_pct) + '%"></div></div></td>' +
        "<td>" + esc(s.moisture_pct) + "%</td>" +
        "<td>" + (s.irrigate ? "💧 " + esc(num(s.irrigation_mm, 0)) + " mm" : "—") + "</td></tr>";
    }).join("");

    $("#irrOut").innerHTML =
      '<div class="irr-hero">' +
        '<div class="irr-big ' + tone + '"><div class="k">Recommendation</div>' +
          '<div class="v">' + esc(big) + "</div><div class=\"s\">" + esc(small || "") + "</div></div>" +
        '<div class="irr-big"><div class="k">Water per application</div>' +
          '<div class="v">' + esc(num(rec.gross_depth_mm, 1)) + " mm</div>" +
          '<div class="s">' + esc(num(rec.gross_volume_m3, 1)) + " m³ for " +
          esc(num(plan.inputs.area, 2)) + " " + esc(plan.inputs.area_unit) + "(s)</div></div>" +
        '<div class="irr-big green"><div class="k">Interval</div>' +
          '<div class="v">' + esc(rec.interval_days === null ? "—" : num(rec.interval_days, 1)) + " days</div>" +
          '<div class="s">' + esc(plan.inputs.method_label) + " · " + esc(plan.inputs.efficiency_pct) + "% efficient</div></div>" +
      "</div>" +

      '<div class="card"><div class="card-head"><h2>Water balance working</h2>' +
        '<span class="muted">' + esc(plan.crop.name) + " · " + esc(plan.stage.name) + "</span></div>" +
        '<div class="card-body"><div class="kv">' +
          kv("Crop coefficient Kc", num(use.kc, 2)) +
          kv("Reference ET₀", num(plan.inputs.et0, 2) + " mm/day") +
          kv("Crop water use ETc", num(use.etc_mm_day, 2) + " mm/day") +
          kv("Effective rainfall", num(use.effective_rain_mm_day, 2) + " mm/day") +
          kv("Net demand", num(use.net_demand_mm_day, 2) + " mm/day") +
          kv("Soil type", titleCase(soil.type)) +
          kv("Root zone depth", num(soil.root_depth_m, 2) + " m") +
          kv("Total available water", num(soil.taw_mm, 1) + " mm") +
          kv("Readily available water", num(soil.raw_mm, 1) + " mm") +
          kv("Current depletion", num(soil.current_depletion_mm, 1) + " mm") +
          kv("Root zone moisture", num(soil.moisture_pct, 0) + " %") +
          kv("Net depth per irrigation", num(rec.net_depth_mm, 1) + " mm") +
          kv("Gross depth", num(rec.gross_depth_mm, 1) + " mm") +
          kv("Water per acre", num(rec.gross_volume_per_acre_m3, 1) + " m³") +
          kv("Total volume", num(rec.gross_volume_m3, 1) + " m³") +
        "</div>" +
        (plan.warnings.length
          ? '<div class="field-label" style="margin-top:16px">Assumptions &amp; cautions</div><ul class="warn-list">' +
            plan.warnings.map((w) => "<li><span>" + esc(w) + "</span></li>").join("") + "</ul>"
          : "") +
      "</div></div>" +

      '<div class="card"><div class="card-head"><h2>10-day schedule</h2>' +
        '<span class="muted">' + esc(rec.best_time) + "</span></div>" +
        '<div class="card-body" style="overflow-x:auto"><table class="tbl"><thead><tr>' +
        "<th>Day</th><th>Depletion</th><th>Moisture</th><th></th><th>Irrigation</th>" +
        "</tr></thead><tbody>" + schedRows + "</tbody></table></div></div>" +

      '<div class="card"><div class="card-head"><h2>Recommendations</h2></div>' +
        '<div class="card-body"><ul class="advice-list">' +
        plan.advice.map((a) => "<li><span>" + esc(a) + "</span></li>").join("") + "</ul>" +
        '<div class="disclaimer">Model: irrigation requirement = (Kc × ET₀ − effective rainfall) ' +
        "limited by the soil's readily available water, divided by application efficiency. " +
        "Use it as a planning baseline and confirm with a soil-moisture check in the field.</div>" +
      "</div></div>";
  }

  /* ------------------------------------------------------------------ disease */

  function initDisease() {
    api("/api/disease/meta").then((data) => {
      state.diseaseMeta = data;
      $("#symptomList").innerHTML = data.symptoms.map((s) =>
        '<label class="sym"><input type="checkbox" value="' + esc(s.id) + '"><span>' + esc(s.label) + "</span></label>"
      ).join("");
      $("#disType").innerHTML = '<option value="">All types</option>' +
        data.types.map((t) => '<option value="' + esc(t) + '">' + esc(t) + "</option>").join("");
    }).catch((error) => toast("Could not load the disease catalogue: " + error.message, true));

    const zone = $("#dropzone");
    const input = $("#diagImage");
    zone.addEventListener("click", () => input.click());
    zone.addEventListener("dragover", (event) => { event.preventDefault(); zone.classList.add("drag"); });
    zone.addEventListener("dragleave", () => zone.classList.remove("drag"));
    zone.addEventListener("drop", (event) => {
      event.preventDefault();
      zone.classList.remove("drag");
      if (event.dataTransfer.files && event.dataTransfer.files[0]) {
        input.files = event.dataTransfer.files;
        handleImage(event.dataTransfer.files[0]);
      }
    });
    input.addEventListener("change", () => { if (input.files[0]) handleImage(input.files[0]); });
    $("#clearImage").addEventListener("click", clearImage);
    $("#diagBtn").addEventListener("click", runDiagnose);
    $("#diagReset").addEventListener("click", () => {
      clearImage();
      $$("#symptomList input").forEach((cb) => { cb.checked = false; });
      $("#diagCrop").value = "";
      $("#diagOut").innerHTML = "";
    });

    ["#disSearch", "#disCrop", "#disType"].forEach((sel) => {
      $(sel).addEventListener(sel === "#disSearch" ? "input" : "change", renderDiseaseList);
    });
    let timer = null;
    $("#disSearch").addEventListener("input", () => {
      clearTimeout(timer);
      timer = setTimeout(renderDiseaseList, 250);
    });
    renderDiseaseList();
  }

  function handleImage(file) {
    if (!/^image\//.test(file.type)) { toast("Please choose an image file.", true); return; }
    if (file.size > 12 * 1024 * 1024) { toast("That image is larger than 12 MB.", true); return; }
    state.diagImage = file;
    const url = URL.createObjectURL(file);
    const preview = $("#dzPreview");
    preview.src = url;
    $("#dropzone").classList.add("has-image");
    $("#clearImage").hidden = false;
  }

  function clearImage() {
    state.diagImage = null;
    $("#diagImage").value = "";
    $("#dzPreview").src = "";
    $("#dropzone").classList.remove("has-image");
    $("#clearImage").hidden = true;
  }

  async function runDiagnose() {
    const symptoms = $$("#symptomList input:checked").map((cb) => cb.value);
    if (!state.diagImage && !symptoms.length) {
      toast("Add a leaf photo or tick at least one symptom.", true);
      return;
    }
    const form = new FormData();
    if (state.diagImage) form.append("image", state.diagImage);
    form.append("crop_id", $("#diagCrop").value);
    symptoms.forEach((s) => form.append("symptoms", s));

    $("#diagOut").innerHTML = spinner("Analysing the image…");
    try {
      const data = await api("/api/diagnose", { method: "POST", body: form });
      renderDiagnosis(data);
    } catch (error) {
      $("#diagOut").innerHTML = '<div class="empty">⚠️ ' + esc(error.message) + "</div>";
    }
  }

  function renderDiagnosis(result) {
    const severity = result.severity || {};
    const metrics = result.metrics || {};
    const image = result.image || {};
    const out = [];

    const sevClass = { none: "good", low: "good", moderate: "warning", high: "danger", severe: "danger" }[severity.level] || "soft";

    out.push('<div class="card result-card"><div class="card-head"><h2>Assessment</h2>' +
      '<span class="badge ' + sevClass + '">' + esc(severity.label) + "</span></div>" +
      '<div class="card-body">' +
      '<p style="font-size:1.02rem">' + esc(result.assessment) + "</p>" +
      (result.mode === "image"
        ? '<div class="kv" style="margin:14px 0">' +
            kv("Leaf area analysed", num(image.leaf_coverage_pct, 1) + " %") +
            kv("Healthy green", num(metrics.healthy_green_pct, 1) + " %") +
            kv("Chlorosis (yellowing)", num(metrics.chlorosis_pct, 1) + " %") +
            kv("Necrotic / rusted tissue", num(metrics.lesion_pct, 1) + " %") +
            kv("Dark necrosis", num(metrics.necrosis_pct, 1) + " %") +
            kv("Rust/orange tissue", num(metrics.rust_pct, 1) + " %") +
            kv("White powdery tissue", num(metrics.white_powder_pct, 1) + " %") +
            kv("Distinct spots detected", num(image.spot_count, 0)) +
            kv("Mosaic / mottle index", num(metrics.mottle_index, 1)) +
            kv("Image sharpness", num(image.sharpness, 1)) +
          "</div>"
        : '<p class="muted">No image was analysed — this result is based only on the symptoms you selected.</p>') +
      (result.quality_flags.length
        ? '<ul class="warn-list">' + result.quality_flags.map((f) => "<li><span>" + esc(f) + "</span></li>").join("") + "</ul>"
        : "") +
      "</div></div>");

    if (result.matches.length) {
      out.push('<div class="card"><div class="card-head"><h2>Ranked matches</h2>' +
        '<span class="muted">' + esc(result.matches.length) + " candidates</span></div><div class=\"card-body\">" +
        result.matches.map((m, index) => matchHtml(m, index === 0)).join("") +
        '<div class="disclaimer">' + esc(result.disclaimer) + "</div></div></div>");
    } else {
      out.push('<div class="empty">Not enough signal to rank any candidate. Try a sharper close-up ' +
        "with the leaf filling the frame.</div>");
    }

    if (result.tags.length) {
      out.push('<div class="card"><div class="card-head"><h2>Visual evidence detected</h2>' +
        '<span class="muted">Explainable signals from the image and your answers</span></div>' +
        '<div class="card-body"><div class="tag-grid">' +
        result.tags.map((t) =>
          '<div class="tag-item"><div class="t-top"><span>' + esc(t.label) + "</span><b>" + esc(t.score) + "</b></div>" +
          '<div class="t-bar"><i style="width:' + esc(t.score) + '%"></i></div></div>').join("") +
        "</div></div></div>");
    }

    $("#diagOut").innerHTML = out.join("");
    $("#diagOut").scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function matchHtml(match, isTop) {
    const sevClass = { high: "danger", medium: "warning", low: "good" }[match.severity] || "soft";
    const actions = match.actions || {};
    const actionBlock = (title, items) => (items && items.length)
      ? "<h4>" + esc(title) + "</h4><ul>" + items.map((i) => "<li>" + esc(i) + "</li>").join("") + "</ul>" : "";

    return '<div class="match' + (isTop ? " top" : "") + '">' +
      '<div class="match-head"><h3>' + esc(match.name) + "</h3>" +
        '<span class="badge ' + esc(sevClass) + '">' + esc(match.pathogen_type) + "</span>" +
        '<span class="pct">' + esc(match.match_pct) + "%</span></div>" +
      '<div class="match-bar"><i style="width:' + esc(Math.min(100, match.match_pct)) + '%"></i></div>' +
      (match.pathogen && match.pathogen !== "-" ? '<p class="muted" style="margin:0">' + esc(match.pathogen) + "</p>" : "") +
      (match.crops && match.crops.length ? '<p class="muted" style="margin:4px 0 0">Affects: ' + esc(match.crops.join(", ")) + "</p>" : "") +
      "<p style=\"margin-top:10px\">" + esc(match.overview) + "</p>" +
      (match.matched_signatures && match.matched_signatures.length
        ? "<h4>Signals that contributed</h4><ul>" + match.matched_signatures.map((s) =>
            "<li>" + esc(s.label) + " — " + esc(s.score) + "%</li>").join("") + "</ul>"
        : "") +
      actionBlock("Cultural control", actions.cultural) +
      actionBlock("Organic / biological", actions.organic) +
      actionBlock("Chemical (follow label and local rules)", actions.chemical) +
      actionBlock("Prevention", actions.prevention) +
      (match.image_cues ? '<div class="disclaimer">📷 ' + esc(match.image_cues) + "</div>" : "") +
      "</div>";
  }

  function renderDiseaseList() {
    const query = $("#disSearch").value.trim();
    const crop = $("#disCrop").value;
    const type = $("#disType").value;
    const params = new URLSearchParams();
    if (query) params.set("q", query);
    if (crop) params.set("crop", crop);
    if (type) params.set("type", type);

    api("/api/diseases?" + params.toString()).then((data) => {
      $("#disList").innerHTML = data.diseases.length
        ? data.diseases.map((d) =>
            '<article class="dis-card" data-id="' + esc(d.id) + '">' +
              '<div class="d-name">' + esc(d.name) + "</div>" +
              '<div class="d-path">' + esc(d.pathogen_type) + (d.pathogen ? " &middot; " + esc(d.pathogen) : "") + "</div>" +
              '<div class="d-over">' + esc(d.overview) + "</div>" +
              '<div class="d-foot"><span class="badge ' + esc(d.severity) + '">' + esc(d.severity) + " impact</span>" +
                d.crops.slice(0, 3).map((c) => '<span class="badge soft">' + esc(c) + "</span>").join("") +
              "</div></article>").join("")
        : '<div class="empty">No disease matches those filters.</div>';
      $$("#disList .dis-card").forEach((card) =>
        card.addEventListener("click", () => openDisease(card.dataset.id)));
    }).catch((error) => {
      $("#disList").innerHTML = '<div class="empty">⚠️ ' + esc(error.message) + "</div>";
    });
  }

  async function openDisease(id) {
    openModal(spinner("Loading disease details…"));
    try {
      const data = await api("/api/diseases/" + encodeURIComponent(id));
      renderDiseaseModal(data.disease);
    } catch (error) {
      openModal('<div class="empty">⚠️ ' + esc(error.message) + "</div>");
    }
  }

  function renderDiseaseModal(d) {
    const mgmt = d.management || {};
    const list = (items) => (items && items.length)
      ? '<ul class="advice-list">' + items.map((i) => "<li><span>" + esc(i) + "</span></li>").join("") + "</ul>"
      : '<p class="muted">—</p>';

    const sevClass = { high: "danger", medium: "warning", low: "good" }[d.severity] || "soft";

    openModal(
      '<div class="modal-hero"><div class="crop-emoji">🧫</div><div>' +
        "<h2>" + esc(d.name) + "</h2>" +
        '<div class="crop-sub">' + esc(d.pathogen) + "</div>" +
        '<div class="chip-row" style="margin-top:8px">' +
          '<span class="badge ' + esc(sevClass) + '">' + esc(d.severity) + " impact</span>" +
          '<span class="badge neutral">' + esc(d.pathogen_type) + "</span>" +
          d.crops.map((c) => '<span class="badge soft">' + esc(c) + "</span>").join("") +
        "</div></div></div>" +
      "<p>" + esc(d.overview) + "</p>" +

      '<div class="grid two">' +
        '<div><div class="field-label">Symptoms to look for</div><ul class="season-list">' +
          (d.symptoms || []).map((s) => "<li>" + esc(s) + "</li>").join("") + "</ul></div>" +
        '<div><div class="field-label">Conditions that favour it</div><ul class="season-list">' +
          (d.favourable || []).map((s) => "<li>" + esc(s) + "</li>").join("") + "</ul>" +
          '<div class="field-label">How it spreads</div><p class="muted">' + esc(d.spread) + "</p></div>" +
      "</div>" +

      '<div class="field-label" style="margin-top:18px">Integrated management</div>' +
      '<div class="grid two">' +
        '<div><h4 style="font-size:.8rem;text-transform:uppercase;letter-spacing:.06em;color:var(--ink-3)">Cultural</h4>' +
          list(mgmt.cultural) + "</div>" +
        '<div><h4 style="font-size:.8rem;text-transform:uppercase;letter-spacing:.06em;color:var(--ink-3)">Organic / biological</h4>' +
          list(mgmt.organic) + "</div>" +
      "</div>" +
      '<div class="field-label">Chemical control</div>' + list(mgmt.chemical) +
      '<div class="field-label">Prevention</div>' +
      '<ul class="advice-list">' + (d.prevention || []).map((p) => "<li><span>" + esc(p) + "</span></li>").join("") + "</ul>" +
      (d.image_cues ? '<div class="disclaimer">📷 ' + esc(d.image_cues) + "</div>" : "") +
      '<div class="disclaimer">Always read and follow the product label. Where a chemical is ' +
      "mentioned, confirm it is registered for this crop and pest in your area, and respect the " +
      "pre-harvest interval and safety precautions.</div>"
    );
  }

  /* ------------------------------------------------------------------ tips */

  function initTips() {
    api("/api/tips").then((data) => {
      $("#tipChips").innerHTML = '<button class="chip active" data-cat="">All</button>' +
        data.categories.map((c) => '<button class="chip" data-cat="' + esc(c) + '">' + esc(c) + "</button>").join("");
      $$("#tipChips .chip").forEach((chip) => chip.addEventListener("click", () => {
        $$("#tipChips .chip").forEach((c) => c.classList.toggle("active", c === chip));
        renderTips();
      }));
      $("#tipSearch").addEventListener("input", () => {
        clearTimeout(initTips._t);
        initTips._t = setTimeout(renderTips, 250);
      });
      renderTips(data.tips);
    }).catch((error) => toast("Could not load tips: " + error.message, true));

    api("/api/seasonal").then((data) => {
      renderCalendar(data);
    }).catch(() => { /* non fatal */ });
  }

  function renderTips(preloaded) {
    const category = ($("#tipChips .chip.active") || {}).dataset;
    const cat = category ? category.cat : "";
    const query = $("#tipSearch") ? $("#tipSearch").value.trim() : "";

    if (preloaded && !cat && !query) { $("#tipGrid").innerHTML = preloaded.map(tipCard).join(""); return; }

    const params = new URLSearchParams();
    if (cat) params.set("category", cat);
    if (query) params.set("q", query);
    api("/api/tips?" + params.toString()).then((data) => {
      $("#tipGrid").innerHTML = data.tips.length
        ? data.tips.map(tipCard).join("")
        : '<div class="empty">No tips match that filter.</div>';
    });
  }

  function renderCalendar(data) {
    const months = data.calendar;
    const current = data.current;
    $("#calTag").textContent = "Current season: " + current.season;
    $("#monthStrip").innerHTML = months.map((m) =>
      '<button class="month-btn' + (m.month === current.month ? " active" : "") +
      (m.month === new Date().getMonth() + 1 ? " now" : "") + '" data-month="' + esc(m.month) + '">' +
      esc(m.name) + "</button>").join("");
    $$("#monthStrip .month-btn").forEach((btn) => btn.addEventListener("click", () => {
      $$("#monthStrip .month-btn").forEach((b) => b.classList.toggle("active", b === btn));
      loadMonth(Number(btn.dataset.month));
    }));
    loadMonth(current.month);
  }

  function loadMonth(month) {
    api("/api/seasonal?month=" + month).then((data) => {
      const m = data.current;
      $("#monthDetail").innerHTML =
        '<div class="month-col" style="grid-column:1/-1">' +
          '<div class="chip-row"><span class="badge">' + esc(m.month_name) + "</span>" +
          '<span class="badge neutral">' + esc(m.season) + " season</span></div>" +
          '<p style="margin-top:10px" class="season-focus">' + esc(m.focus) + "</p></div>" +
        '<div class="month-col"><h4>🌱 Sow / plant</h4><ul>' +
          (m.sow || []).map((s) => "<li>" + esc(s) + "</li>").join("") + "</ul></div>" +
        '<div class="month-col"><h4>✅ Field work</h4><ul>' +
          (m.care || []).map((s) => "<li>" + esc(s) + "</li>").join("") + "</ul></div>" +
        '<div class="month-col"><h4>⚠️ Watch out for</h4><ul>' +
          (m.watch || []).map((s) => "<li>" + esc(s) + "</li>").join("") + "</ul></div>" +
        (m.irrigation_hint
          ? '<div class="month-col" style="grid-column:1/-1"><div class="disclaimer">💧 ' +
            esc(m.irrigation_hint) + "</div></div>" : "");
    });
  }

  /* ------------------------------------------------------------------ start */

  window.addEventListener("hashchange", () => {
    const hash = location.hash.slice(1);
    if (VIEW_TITLES[hash]) goto(hash);
  });

  boot().catch((error) => {
    console.error("AgriSense failed to start:", error);
    toast("Something went wrong while starting: " + error.message, true);
  });
})();
