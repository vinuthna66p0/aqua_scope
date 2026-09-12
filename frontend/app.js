const API = "/api";

let state = {
  cases: [],
  currentCase: null,
  selectedSlickId: null,
  map: null,
  layers: {}, // slick_id -> {marker, traj, uncertainty, backward}
  zoneLayers: [],
  vesselLayers: [],
  compareMap: null,
};

const CLASS_CLASS = {
  "Likely Oil": "oil", "Uncertain": "uncertain", "Likely Look-alike": "lookalike",
};
const CLASS_DOT = { "Likely Oil": "oil", "Uncertain": "uncertain", "Likely Look-alike": "lookalike" };

// ---------------------------------------------------------------- utils

function $(id) { return document.getElementById(id); }
function fmt(n, d = 4) { return (n === null || n === undefined) ? "—" : Number(n).toFixed(d); }

async function api(path, opts) {
  const res = await fetch(API + path, opts);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || "Request failed");
  }
  return res.json();
}

function updateClock() {
  const now = new Date();
  $("clock").textContent = now.toLocaleDateString("en-GB") + "  " + now.toLocaleTimeString();
}
setInterval(updateClock, 1000);
updateClock();

// ---------------------------------------------------------------- init

async function init() {
  initMap();
  initCompareMap();
  state.cases = await api("/cases");
  const sel = $("caseSelect");
  sel.innerHTML = state.cases.map(c => `<option value="${c.case_id}">${c.case_id.replace("CASE_", "Case ")} — ${c.scenario_tag}</option>`).join("");
  sel.addEventListener("change", () => loadCase(sel.value));
  await loadCase(state.cases[0].case_id);
  loadMetadataTable();

  $("btnRun").addEventListener("click", async () => {
    $("statusBadge").textContent = "● Running…";
    await api("/analyze", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ case_id: state.currentCase.case_id }) });
    await loadCase(state.currentCase.case_id);
    $("statusBadge").textContent = "● System Ready";
  });

  $("btnReset").addEventListener("click", async () => {
    await api(`/cases/${state.currentCase.case_id}/reset`, { method: "POST" });
    await loadCase(state.currentCase.case_id);
  });

  $("hourSlider").addEventListener("input", onHourChange);

  $("btnRecalc").addEventListener("click", onRecalculate);
  $("btnObserve").addEventListener("click", onSimulateObservation);
  $("btnCorrect").addEventListener("click", onApplyCorrection);

  document.querySelectorAll(".tab").forEach(t => t.addEventListener("click", () => switchTab(t.dataset.tab)));

  ["simWindSpeed", "simWindDir", "simCurSpeed", "simCurDir"].forEach(id => {
    $(id).addEventListener("input", () => $(id + "Val").textContent = $(id).value);
  });

  $("metaFilter").addEventListener("input", renderMetadataTable);
}

function switchTab(name) {
  document.querySelectorAll(".tab").forEach(t => t.classList.toggle("active", t.dataset.tab === name));
  document.querySelectorAll(".tab-content").forEach(c => c.classList.remove("active"));
  $("tab-" + name).classList.add("active");
  if (name === "compare" && state.compareMap) setTimeout(() => state.compareMap.invalidateSize(), 100);
  if (name === "map" && state.map) setTimeout(() => state.map.invalidateSize(), 100);
}

// ---------------------------------------------------------------- map

function initMap() {
  state.map = L.map("map", { zoomControl: true }).setView([15.4, 72.9], 8);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: "© OpenStreetMap contributors", maxZoom: 12,
  }).addTo(state.map);
}

function initCompareMap() {
  state.compareMap = L.map("compareMap", { zoomControl: true }).setView([15.4, 72.9], 8);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: "© OpenStreetMap contributors", maxZoom: 12,
  }).addTo(state.compareMap);
}

function clearMapLayers() {
  Object.values(state.layers).forEach(l => Object.values(l).forEach(layer => layer && state.map.removeLayer(layer)));
  state.layers = {};
  state.zoneLayers.forEach(z => state.map.removeLayer(z));
  state.zoneLayers = [];
  state.vesselLayers.forEach(v => state.map.removeLayer(v));
  state.vesselLayers = [];
}

const SLICK_COLORS = ["#ef5f5f", "#3c8dff", "#f2c94c", "#33d17a", "#c77dff", "#ff9f43"];

function colorForIndex(i) { return SLICK_COLORS[i % SLICK_COLORS.length]; }

function renderMapForCase(c) {
  clearMapLayers();
  const bounds = [];

  // sensitive zones
  (c.sensitive_zones || []).forEach(z => {
    const circle = L.circle([z.center_lat, z.center_lon], {
      radius: z.radius_km * 1000, color: "#2fd4c8", weight: 1.5, fillOpacity: 0.08, dashArray: "4,4",
    }).addTo(state.map).bindPopup(`<b>${z.name}</b><br/>${z.zone_type}<br/>radius ${z.radius_km} km`);
    state.zoneLayers.push(circle);
    bounds.push([z.center_lat, z.center_lon]);
  });

  // AIS vessels
  (c.vessels || []).forEach(v => {
    if (!v.track || !v.track.length) return;
    const latlngs = v.track.map(p => [p.latitude, p.longitude]);
    const color = v.is_dark_vessel ? "#ff2d2d" : "#8ea0c2";
    const line = L.polyline(latlngs, { color, weight: v.is_dark_vessel ? 3 : 1.5, dashArray: v.is_dark_vessel ? "2,4" : null }).addTo(state.map);
    const marker = L.circleMarker(latlngs[latlngs.length - 1], { radius: 5, color, fillColor: color, fillOpacity: 0.9 })
      .addTo(state.map)
      .bindPopup(`<b>${v.vessel_name}</b><br/>${v.vessel_type}<br/>MMSI: ${v.mmsi}${v.is_dark_vessel ? "<br/><b style='color:#ff5555'>UNMATCHED / DARK VESSEL</b>" : ""}${v.ais_gap ? "<br/><b style='color:#f2c94c'>AIS GAP DETECTED</b>" : ""}`);
    state.vesselLayers.push(line, marker);
    latlngs.forEach(ll => bounds.push(ll));
  });

  // slicks
  c.slicks.forEach((s, i) => {
    const color = colorForIndex(i);
    const cls = CLASS_CLASS[s.final_classification] || "uncertain";

    const detectMarker = L.circleMarker([s.center_latitude, s.center_longitude], {
      radius: 8, color: color, fillColor: color, fillOpacity: s.look_alike_status ? 0.25 : 0.85, weight: 2,
    }).addTo(state.map).bindPopup(`<b>${s.slick_id}</b><br/>${s.final_classification}<br/>Confidence: ${s.fusion_breakdown ? Object.values(s.fusion_breakdown).reduce((a,b)=>a+b,0).toFixed(1) : "—"}%`);
    detectMarker.on("click", () => selectSlick(s.slick_id));

    let trajLine = null, uncertaintyLine = null, backwardLine = null, movingMarker = null;

    if (!s.look_alike_status && s.trajectory && s.trajectory.length) {
      const latlngs = s.trajectory.map(p => [p.latitude, p.longitude]);
      trajLine = L.polyline(latlngs, { color, weight: 3, dashArray: "6,4" }).addTo(state.map);

      const uLatLngs = s.trajectory.map(p => [p.latitude + p.uncertainty_km / 111, p.longitude])
        .concat(s.trajectory.slice().reverse().map(p => [p.latitude - p.uncertainty_km / 111, p.longitude]));
      uncertaintyLine = L.polygon(uLatLngs, { color, weight: 0, fillOpacity: 0.08 }).addTo(state.map);

      if (s.backward_path && s.backward_path.length) {
        const bLatLngs = s.backward_path.map(p => [p.latitude, p.longitude]);
        backwardLine = L.polyline(bLatLngs, { color: "#ffffff", weight: 2, dashArray: "2,6", opacity: 0.6 }).addTo(state.map)
          .bindPopup(`Probable origin<br/>${fmt(s.origin_latitude)}, ${fmt(s.origin_longitude)}`);
      }

      movingMarker = L.circleMarker([s.trajectory[0].latitude, s.trajectory[0].longitude], {
        radius: 6, color: "#fff", fillColor: color, fillOpacity: 1, weight: 2,
      }).addTo(state.map);

      latlngs.forEach(ll => bounds.push(ll));
    }

    state.layers[s.slick_id] = { detectMarker, trajLine, uncertaintyLine, backwardLine, movingMarker };
    bounds.push([s.center_latitude, s.center_longitude]);
  });

  if (bounds.length) state.map.fitBounds(bounds, { padding: [30, 30] });
}

function onHourChange() {
  const hour = parseInt($("hourSlider").value, 10);
  $("hourLabel").textContent = hour + "h";
  Object.entries(state.layers).forEach(([slickId, l]) => {
    if (!l.movingMarker) return;
    const s = state.currentCase.slicks.find(sl => sl.slick_id === slickId);
    if (!s || !s.trajectory) return;
    const pt = s.trajectory.find(p => p.hour === hour) || s.trajectory[s.trajectory.length - 1];
    l.movingMarker.setLatLng([pt.latitude, pt.longitude]);
  });
}

// ---------------------------------------------------------------- case loading

async function loadCase(caseId) {
  const c = await api(`/cases/${caseId}`);
  state.currentCase = c;
  $("caseSelect").value = caseId;

  renderKPIs(c);
  renderCaseSummary(c);
  renderSlickList(c);
  renderDetectionTable(c);
  renderMapForCase(c);

  // sync simulator sliders to this case's current environment
  $("simWindSpeed").value = c.environment.wind_speed; $("simWindSpeedVal").textContent = c.environment.wind_speed;
  $("simWindDir").value = c.environment.wind_direction; $("simWindDirVal").textContent = c.environment.wind_direction;
  $("simCurSpeed").value = c.environment.current_speed; $("simCurSpeedVal").textContent = c.environment.current_speed;
  $("simCurDir").value = c.environment.current_direction; $("simCurDirVal").textContent = c.environment.current_direction;
  $("recalcResult").innerHTML = "";

  const firstOil = c.slicks.find(s => !s.look_alike_status) || c.slicks[0];
  selectSlick(firstOil.slick_id);
  $("hourSlider").value = 0;
  onHourChange();
}

function renderKPIs(c) {
  const detected = c.slicks.length;
  const oil = c.slicks.filter(s => s.final_classification === "Likely Oil").length;
  const uncertain = c.slicks.filter(s => s.final_classification === "Uncertain").length;
  const lookalike = c.slicks.filter(s => s.look_alike_status).length;
  $("kpiStrip").innerHTML = `
    <div class="kpi"><div class="label">Detected Candidates</div><div class="value">${detected}</div><div class="sub">${lookalike} look-alike filtered</div></div>
    <div class="kpi"><div class="label">Likely Oil</div><div class="value">${oil}</div></div>
    <div class="kpi"><div class="label">Uncertain</div><div class="value">${uncertain}</div></div>
    <div class="kpi"><div class="label">Location</div><div class="value" style="font-size:13px">${c.location_name}</div></div>
    <div class="kpi"><div class="label">Acquisition</div><div class="value" style="font-size:13px">${c.acquisition_date}</div></div>
    <div class="kpi"><div class="label">Scenario</div><div class="value" style="font-size:13px">${c.scenario_tag}</div></div>
  `;
}

function renderCaseSummary(c) {
  $("caseSummary").innerHTML = `
    <div><span>Title</span><span class="v">${c.title}</span></div>
    <div><span>Location</span><span class="v">${c.location_name}</span></div>
    <div><span>Slicks</span><span class="v">${c.num_slicks}</span></div>
    <div><span>Wind</span><span class="v">${c.environment.wind_speed} m/s @ ${c.environment.wind_direction}°</span></div>
    <div><span>Current</span><span class="v">${c.environment.current_speed} m/s @ ${c.environment.current_direction}°</span></div>
    <div><span>Wave height</span><span class="v">${c.environment.wave_height} m</span></div>
    <div><span>Sea surface temp</span><span class="v">${c.environment.sea_surface_temp} °C</span></div>
    <p style="color:var(--muted);font-size:11px;margin-top:6px">${c.description}</p>
  `;
}

function renderSlickList(c) {
  $("slickList").innerHTML = c.slicks.map(s => `
    <div class="slick-item" data-id="${s.slick_id}">
      <span><span class="dot ${CLASS_DOT[s.final_classification]}"></span>${s.slick_id.split("_").slice(-1)[0]}</span>
      <span style="color:var(--muted);font-size:10.5px">${s.final_classification}</span>
    </div>`).join("");
  document.querySelectorAll(".slick-item").forEach(el => el.addEventListener("click", () => selectSlick(el.dataset.id)));
}

function renderDetectionTable(c) {
  const tbody = document.querySelector("#detectionTable tbody");
  tbody.innerHTML = c.slicks.map(s => `
    <tr>
      <td>${s.slick_id.split("_").slice(-1)[0]}</td>
      <td>${s.sar_classification}</td>
      <td>${s.eo_validation}</td>
      <td>${s.final_classification}</td>
      <td>${s.sar_confidence}%</td>
    </tr>`).join("");
}

// ---------------------------------------------------------------- slick selection

function selectSlick(slickId) {
  state.selectedSlickId = slickId;
  document.querySelectorAll(".slick-item").forEach(el => el.classList.toggle("selected", el.dataset.id === slickId));

  const s = state.currentCase.slicks.find(sl => sl.slick_id === slickId);
  if (!s) return;

  $("classBadge").textContent = s.final_classification;
  $("classBadge").className = "badge " + (CLASS_CLASS[s.final_classification] || "uncertain");

  $("slickDetails").innerHTML = `
    <div><span class="k">Event ID</span><span class="v">${s.event_id}</span></div>
    <div><span class="k">Latitude / Longitude</span><span class="v">${fmt(s.center_latitude)}, ${fmt(s.center_longitude)}</span></div>
    <div><span class="k">Length × Width</span><span class="v">${s.length_km} km × ${s.width_km} km</span></div>
    <div><span class="k">Area</span><span class="v">${s.area_km2} km²</span></div>
    <div><span class="k">Shape / Orientation</span><span class="v">${s.shape}, ${s.orientation_deg}°</span></div>
    <div><span class="k">Satellite / Sensor</span><span class="v">${s.satellite} (${s.sensor_mode})</span></div>
    <div><span class="k">Acquisition</span><span class="v">${s.acquisition_date} ${s.acquisition_time}</span></div>
    <div><span class="k">SAR confidence</span><span class="v">${s.sar_confidence}%</span></div>
    <div><span class="k">EO validation</span><span class="v">${s.eo_validation} (${s.eo_confidence}%)</span></div>
    <div><span class="k">Look-alike?</span><span class="v">${s.look_alike_status ? "Yes — " + s.look_alike_reason : "No"}</span></div>
    <div><span class="k">Spill window</span><span class="v">${s.estimated_spill_start} → ${s.estimated_spill_end}</span></div>
    <div><span class="k">Detection delay</span><span class="v">${s.detection_delay_minutes} min</span></div>
    <div><span class="k">Probable origin</span><span class="v">${fmt(s.origin_latitude)}, ${fmt(s.origin_longitude)}</span></div>
  `;

  if (s.fusion_breakdown) {
    const total = Object.values(s.fusion_breakdown).reduce((a, b) => a + b, 0);
    $("fusionBreakdown").innerHTML = Object.entries(s.fusion_breakdown).map(([k, v]) => `<div class="frow"><span>${k}</span><span>+${v}</span></div>`).join("")
      + `<div class="fusion-total"><span>Final confidence</span><span>${total.toFixed(1)}%</span></div>`;
  } else {
    $("fusionBreakdown").innerHTML = "<div class='frow'><span>Not available for look-alike objects</span></div>";
  }

  renderTrajTable(s);
  renderTimeline(s);
  renderAIS(s, state.currentCase);
  renderImpact(s);
  renderObservePanel(s);
  highlightSelectedOnMap(slickId);
  onHourChange();
}

function highlightSelectedOnMap(slickId) {
  Object.entries(state.layers).forEach(([id, l]) => {
    const weight = id === slickId ? 5 : 2;
    const opacity = id === slickId ? 1 : 0.35;
    if (l.trajLine) { l.trajLine.setStyle({ weight, opacity }); }
    if (l.movingMarker) { l.movingMarker.setStyle({ opacity, fillOpacity: opacity }); }
  });
}

function renderTrajTable(s) {
  const tbody = document.querySelector("#trajTable tbody");
  if (!s.trajectory) { tbody.innerHTML = "<tr><td colspan='6'>No trajectory (look-alike object)</td></tr>"; return; }
  tbody.innerHTML = s.trajectory.map(p => `
    <tr><td>${p.hour}h</td><td>${fmt(p.latitude)}</td><td>${fmt(p.longitude)}</td>
    <td>${p.direction_deg}°</td><td>${p.distance_km}</td><td>±${p.uncertainty_km}</td></tr>`).join("");
}

function renderTimeline(s) {
  const nodes = [
    ["Last clean", s.last_clean_observation],
    ["First suspicious", s.first_suspicious_observation],
    ["Detected", s.first_detection_time],
  ];
  $("timeline").innerHTML = nodes.map(([label, t], i) => `
    <div class="tl-node"><div class="tl-dot"></div><div class="tl-time">${t ? t.split("T")[1] || t : "—"}</div><div class="tl-label">${label}</div></div>
    ${i < nodes.length - 1 ? '<div class="tl-line"></div>' : ''}
  `).join("") + `<div style="margin-left:10px;color:var(--muted)">Detection delay: <b style="color:#fff">${s.detection_delay_minutes} min</b></div>`;
}

function renderAIS(s, c) {
  const tbody = document.querySelector("#aisTable tbody");
  if (s.look_alike_status || !s.ais_candidates || !s.ais_candidates.length) {
    tbody.innerHTML = "<tr><td colspan='7'>No candidates (not a confirmed slick)</td></tr>";
  } else {
    tbody.innerHTML = s.ais_candidates.map(v => `
      <tr><td>#${v.candidate_rank}</td><td>${v.vessel_name}</td><td>${v.mmsi}</td>
      <td>${v.distance_km}</td><td>${v.temporal_match ? "✓" : "✗"}</td>
      <td>${v.trajectory_consistency}</td><td><b>${v.candidate_score}%</b></td></tr>`).join("");
  }
  const dark = (c.vessels || []).filter(v => v.is_dark_vessel);
  $("darkVesselFlag").innerHTML = dark.length
    ? dark.map(v => `<div class="flag">⚠ UNMATCHED / DARK-VESSEL CANDIDATE — ${v.vessel_name} (no AIS transmission near reconstructed origin)</div>`).join("")
    : "";
}

function renderImpact(s) {
  if (!s.impact || !s.impact.top) {
    $("impactPanel").innerHTML = "<div><span class='k'>No impact data</span></div>";
    return;
  }
  const t = s.impact.top;
  $("impactPanel").innerHTML = `
    <div><span class="k">Nearest sensitive zone</span><span class="v">${t.zone_name}</span></div>
    <div><span class="k">Zone type</span><span class="v">${t.zone_type}</span></div>
    <div><span class="k">Distance</span><span class="v">${t.distance_km} km</span></div>
    <div><span class="k">Status</span><span class="v">${t.status}</span></div>
    <div><span class="k">Est. arrival</span><span class="v">${t.estimated_arrival_hours !== null ? t.estimated_arrival_hours + "h" : "—"}</span></div>
    <div><span class="k">Potential impact</span><span class="v">${t.potential_impact ? "YES" : "No"}</span></div>
    <div><span class="k">Priority</span><span class="v" style="color:${t.priority === 'HIGH' ? '#ef5f5f' : t.priority === 'MEDIUM' ? '#f2c94c' : '#33d17a'}">${t.priority}</span></div>
  `;
}

function renderObservePanel(s) {
  if (s.observed_latitude !== null && s.observed_latitude !== undefined) {
    $("observePanel").innerHTML = `
      <div><span class="k">Predicted</span><span class="v">${fmt(s.predicted_latitude)}, ${fmt(s.predicted_longitude)}</span></div>
      <div><span class="k">Observed</span><span class="v">${fmt(s.observed_latitude)}, ${fmt(s.observed_longitude)}</span></div>
      <div><span class="k">Error</span><span class="v">${s.prediction_error_km} km</span></div>
      <div><span class="k">Status</span><span class="v">${s.correction_status}</span></div>
    `;
    $("btnCorrect").disabled = s.correction_applied;
  } else {
    $("observePanel").innerHTML = `<div><span class="k">Status</span><span class="v">${s.correction_status || "Not yet observed"}</span></div>`;
    $("btnCorrect").disabled = true;
  }
}

// ---------------------------------------------------------------- actions

async function onRecalculate() {
  const slickId = state.selectedSlickId;
  const body = {
    slick_id: slickId,
    wind_speed: parseFloat($("simWindSpeed").value),
    wind_direction: parseFloat($("simWindDir").value),
    current_speed: parseFloat($("simCurSpeed").value),
    current_direction: parseFloat($("simCurDir").value),
  };
  const result = await api("/trajectory/recalculate", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  $("recalcResult").innerHTML = `New trajectory computed. <b>Deviation from previous forecast: ${result.deviation_km} km</b>`;

  // update local state + redraw
  const s = state.currentCase.slicks.find(sl => sl.slick_id === slickId);
  s.trajectory = result.new_trajectory;
  s.impact = result.impact;
  renderMapForCase(state.currentCase);
  selectSlick(slickId);

  // compare tab
  drawCompare(result.previous_trajectory, result.new_trajectory);
  $("compareInfo").innerHTML = `<b>${slickId}</b> — Original vs new trajectory after environmental change. Deviation at +10h: <b>${result.deviation_km} km</b>`;
}

function drawCompare(prev, next) {
  state.compareMap.eachLayer(l => { if (l instanceof L.Polyline || l instanceof L.CircleMarker) state.compareMap.removeLayer(l); });
  const prevLL = prev.map(p => [p.latitude, p.longitude]);
  const nextLL = next.map(p => [p.latitude, p.longitude]);
  L.polyline(prevLL, { color: "#ef5f5f", weight: 3, dashArray: "6,4" }).addTo(state.compareMap).bindPopup("Original trajectory");
  L.polyline(nextLL, { color: "#3c8dff", weight: 3 }).addTo(state.compareMap).bindPopup("New trajectory");
  state.compareMap.fitBounds(prevLL.concat(nextLL), { padding: [30, 30] });
}

async function onSimulateObservation() {
  const slickId = state.selectedSlickId;
  const hour = parseInt($("hourSlider").value, 10) || 5;
  const result = await api("/observation/update", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ slick_id: slickId, hour }),
  });
  const s = state.currentCase.slicks.find(sl => sl.slick_id === slickId);
  s.predicted_latitude = result.predicted.latitude; s.predicted_longitude = result.predicted.longitude;
  s.observed_latitude = result.observed.latitude; s.observed_longitude = result.observed.longitude;
  s.prediction_error_km = result.prediction_error_km;
  s.correction_status = `New observation received at +${hour}h — correction pending`;
  s.correction_applied = false;
  renderObservePanel(s);

  // show markers on map
  if (state.layers[slickId]) {
    if (state.layers[slickId].observedMarker) state.map.removeLayer(state.layers[slickId].observedMarker);
    state.layers[slickId].observedMarker = L.marker([result.observed.latitude, result.observed.longitude], {
      icon: L.divIcon({ className: '', html: '<div style="background:#33d17a;width:14px;height:14px;border-radius:50%;border:2px solid #fff"></div>' }),
    }).addTo(state.map).bindPopup(`Observed position (+${hour}h)<br/>Error: ${result.prediction_error_km} km`).openPopup();
  }
}

async function onApplyCorrection() {
  const slickId = state.selectedSlickId;
  const result = await api("/trajectory/correct", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ slick_id: slickId }) });
  const s = state.currentCase.slicks.find(sl => sl.slick_id === slickId);
  s.trajectory = result.corrected_trajectory;
  s.correction_applied = true;
  s.correction_status = result.correction_status;
  s.impact = result.impact;
  renderMapForCase(state.currentCase);
  selectSlick(slickId);
}

// ---------------------------------------------------------------- metadata table

let metaRows = [];
let metaSortKey = null, metaSortDir = 1;

async function loadMetadataTable() {
  metaRows = await api("/metadata_table");
  const cols = Object.keys(metaRows[0] || {});
  $("metaThead").innerHTML = "<tr>" + cols.map(c => `<th data-col="${c}">${c}</th>`).join("") + "</tr>";
  document.querySelectorAll("#metaThead th").forEach(th => th.addEventListener("click", () => {
    const col = th.dataset.col;
    metaSortDir = metaSortKey === col ? -metaSortDir : 1;
    metaSortKey = col;
    renderMetadataTable();
  }));
  renderMetadataTable();
}

function renderMetadataTable() {
  const filter = $("metaFilter").value.toLowerCase();
  let rows = metaRows.filter(r => JSON.stringify(r).toLowerCase().includes(filter));
  if (metaSortKey) {
    rows = rows.slice().sort((a, b) => {
      const av = a[metaSortKey], bv = b[metaSortKey];
      if (av === null || av === undefined) return 1;
      if (bv === null || bv === undefined) return -1;
      return av > bv ? metaSortDir : av < bv ? -metaSortDir : 0;
    });
  }
  const cols = Object.keys(metaRows[0] || {});
  $("metaTbody").innerHTML = rows.map(r => "<tr>" + cols.map(c => `<td>${r[c] === null || r[c] === undefined ? "—" : r[c]}</td>`).join("") + "</tr>").join("");
}

init();