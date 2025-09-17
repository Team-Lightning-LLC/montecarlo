// frontend/app.js
const API_BASE = "http://localhost:8000";

let currentPortfolioJSON = null;

function setStatus(id, msg, isErr=false) {
  const el = document.getElementById(id);
  el.textContent = msg;
  el.className = isErr ? "status error" : "status";
}

document.getElementById("parseBtn").addEventListener("click", async () => {
  const file = document.getElementById("docxFile").files[0];
  if (!file) { setStatus("parseStatus", "Please choose a .docx file", true); return; }
  setStatus("parseStatus", "Parsing…");
  const form = new FormData();
  form.append("file", file);
  try {
    const r = await fetch(`${API_BASE}/parse-docx`, { method: "POST", body: form });
    if (!r.ok) throw new Error(`Parse failed: ${r.status}`);
    const data = await r.json();
    currentPortfolioJSON = data.portfolio;
    document.getElementById("jsonInput").value = JSON.stringify(currentPortfolioJSON, null, 2);
    setStatus("parseStatus", "Parsed successfully ✓");
  } catch (e) {
    console.error(e);
    setStatus("parseStatus", "Failed to parse document", true);
  }
});

document.getElementById("useJsonBtn").addEventListener("click", () => {
  try {
    const txt = document.getElementById("jsonInput").value.trim();
    currentPortfolioJSON = JSON.parse(txt);
    alert("Portfolio JSON loaded.");
  } catch {
    alert("Invalid JSON.");
  }
});

document.getElementById("clearJsonBtn").addEventListener("click", () => {
  document.getElementById("jsonInput").value = "";
  currentPortfolioJSON = null;
});

document.getElementById("simulateBtn").addEventListener("click", async () => {
  if (!currentPortfolioJSON) { alert("Load a portfolio first (parse or paste JSON)."); return; }
  const nPaths = Number(document.getElementById("nPaths").value || 10000);
  const seed = Number(document.getElementById("seed").value || 42);

  document.getElementById("simSummary").textContent = "Simulating…";
  try {
    const r = await fetch(`${API_BASE}/simulate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ portfolio: currentPortfolioJSON, n_paths: nPaths, seed })
    });
    if (!r.ok) throw new Error(`Sim failed: ${r.status}`);
    const data = await r.json();
    renderResults(data);
  } catch (e) {
    console.error(e);
    document.getElementById("simSummary").textContent = "Simulation failed.";
  }
});

function renderResults(data) {
  // Summary text
  const probLines = Object.entries(data.prob_by_goal)
    .map(([k,v]) => `${k}: ${(v*100).toFixed(1)}%`).join("\n");
  const s = data.summary;
  const summary = [
    "Goal Probabilities",
    probLines,
    "",
    `Median terminal: $${Math.round(s.median_terminal).toLocaleString()}`,
    `5th–95th: $${Math.round(s.p5_terminal).toLocaleString()} – $${Math.round(s.p95_terminal).toLocaleString()}`
  ].join("\n");
  document.getElementById("simSummary").textContent = summary;

  // Probability block
  document.getElementById("probGoals").innerHTML = Object.entries(data.prob_by_goal)
    .map(([k,v]) => `<div class="pill"><b>${k}</b> ${(v*100).toFixed(1)}%</div>`).join("");

  // Fan chart
  const p10 = data.ptiles_over_time.p10;
  const p50 = data.ptiles_over_time.p50;
  const p90 = data.ptiles_over_time.p90;
  const months = [...Array(p50.length).keys()];
  const years = months.map(m => (m/12).toFixed(1));

  const traceBand = {
    x: years, y: p90, mode: 'lines', line: {width:0},
    showlegend: false, name: '90th', hoverinfo: 'skip'
  };
  const traceBand2 = {
    x: years, y: p10, mode: 'lines', fill: 'tonexty',
    fillcolor: 'rgba(33,150,243,0.15)', line: {width:0},
    showlegend: false, name: '10th', hoverinfo: 'skip'
  };
  const traceMedian = {
    x: years, y: p50, mode: 'lines', line: {color:'#2196F3', width:2},
    name: 'Median'
  };
  Plotly.newPlot('fanChart', [traceBand, traceBand2, traceMedian], {
    title: 'Projected Wealth (Percentiles)',
    xaxis: { title: 'Years', zeroline: false },
    yaxis: { title: 'Portfolio Value ($)', tickformat: ',.0f' },
    margin: {t:40, r:10, b:50, l:60}
  }, {displayModeBar:false});

  // Histogram of terminal
  // (approx from percentiles → fake samples for demo? Ideally, return full sample or bin server-side.
  // For MVP we’ll just visualize the three percentiles as markers.)
  const terminalMarkers = [
    {name:'P5', y:[s.p5_terminal], marker:{color:'#aaa'}},
    {name:'Median', y:[s.median_terminal], marker:{color:'#2196F3'}},
    {name:'P95', y:[s.p95_terminal], marker:{color:'#aaa'}}
  ];
  Plotly.newPlot('histChart', terminalMarkers.map((m,i)=>({
    x:[i], y:m.y, type:'bar', name:m.name, marker:m.marker
  })), {
    title:'Terminal Wealth Markers',
    xaxis:{showticklabels:false},
    yaxis:{title:'$'},
    barmode:'group', margin:{t:40, r:10, b:30, l:60}
  }, {displayModeBar:false});
}

