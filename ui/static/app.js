/* Kalshi Trading Dashboard — client-side logic */

const POLL_MS = 3000;
let selectedTicker = null;
let priceChart = null;

// ── API helpers ──────────────────────────────────────────────────────────

async function api(path) {
  try {
    const resp = await fetch(path);
    if (!resp.ok) return null;
    return await resp.json();
  } catch {
    return null;
  }
}

// ── Format helpers ───────────────────────────────────────────────────────

function dollars(cents) {
  if (cents == null) return "--";
  return "$" + (cents / 100).toFixed(2);
}

function fmtDollars(val) {
  if (val == null) return "--";
  const sign = val >= 0 ? "+" : "";
  return `${sign}$${val.toFixed(2)}`;
}

function pnlClass(val) {
  if (val == null) return "";
  return val >= 0 ? "pnl-pos" : "pnl-neg";
}

function timeAgo(isoStr) {
  if (!isoStr) return "--";
  const d = new Date(isoStr);
  const secs = Math.floor((Date.now() - d.getTime()) / 1000);
  if (secs < 60) return secs + "s ago";
  if (secs < 3600) return Math.floor(secs / 60) + "m ago";
  if (secs < 86400) return Math.floor(secs / 3600) + "h ago";
  return Math.floor(secs / 86400) + "d ago";
}

// ── Balance ──────────────────────────────────────────────────────────────

async function refreshBalance() {
  const data = await api("/api/balance");
  if (data && !data.error) {
    document.getElementById("balance").textContent = "$" + data.balance_dollars.toFixed(2);
    document.getElementById("portfolio-value").textContent = "$" + data.portfolio_value_dollars.toFixed(2);
  }
}

// ── Watchers table ───────────────────────────────────────────────────────

async function refreshWatchers() {
  const data = await api("/api/watchers");
  const tbody = document.getElementById("watchers-body");

  if (!data || data.error || !data.watchers.length) {
    tbody.innerHTML = '<tr><td colspan="13" class="empty-msg">No active watchers</td></tr>';
    document.getElementById("watcher-count").textContent = "0";
    return;
  }

  document.getElementById("watcher-count").textContent = data.watchers.length;

  tbody.innerHTML = data.watchers.map(w => {
    const isSelected = w.ticker === selectedTicker;
    const rowClass = isSelected ? "selected" : "";
    const statusClass = w.status === "watching" ? "status-active" :
                        w.status === "stopped" ? "status-stopped" :
                        w.status === "tp_hit" ? "status-tp" : "";

    const grossStr = w.gross_pnl != null ? fmtDollars(w.gross_pnl) : "--";
    const feesStr = w.fees_worst != null ? fmtDollars(w.fees_worst) : "--";
    const netStr = w.net_pnl != null ? fmtDollars(w.net_pnl) : "--";

    return `<tr class="${rowClass}" data-ticker="${w.ticker}" onclick="selectWatcher('${w.ticker}')">
      <td class="ticker-cell">${w.ticker}</td>
      <td>${w.side}</td>
      <td>${w.entry_cents || "--"}c</td>
      <td>${w.yes_bid != null ? w.yes_bid + "c" : "--"}</td>
      <td>${w.yes_ask != null ? w.yes_ask + "c" : "--"}</td>
      <td>${w.spread != null ? w.spread + "c" : "--"}</td>
      <td class="${pnlClass(w.gross_pnl)}">${grossStr}</td>
      <td class="fees-cell">${feesStr}</td>
      <td class="${pnlClass(w.net_pnl)}">${netStr}</td>
      <td>${w.stop_cents || "--"}c</td>
      <td>${w.take_profit_cents || "--"}c</td>
      <td><span class="status-badge ${statusClass}">${w.status}</span></td>
      <td><button class="btn-remove" onclick="event.stopPropagation(); removeWatcher('${w.ticker}')">X</button></td>
    </tr>`;
  }).join("");
}

// ── Sync watchers from Kalshi positions/orders ───────────────────────────

async function syncWatchers() {
  const btn = document.getElementById("btn-sync");
  btn.disabled = true;
  btn.textContent = "Syncing...";

  try {
    const resp = await fetch("/api/watchers/sync", { method: "POST" });
    const data = await resp.json();
    if (data.error) {
      alert("Sync error: " + data.error);
    } else if (data.synced === 0) {
      btn.textContent = "Already synced";
    } else {
      btn.textContent = `Synced ${data.synced} new`;
      await refreshWatchers();
    }
  } catch (e) {
    alert("Sync failed: " + e);
  }

  setTimeout(() => {
    btn.disabled = false;
    btn.textContent = "Sync from Kalshi";
  }, 3000);
}

// ── Watcher selection → chart + orderbook ────────────────────────────────

async function selectWatcher(ticker) {
  selectedTicker = ticker;
  document.getElementById("chart-ticker").textContent = ticker;
  document.getElementById("ob-ticker").textContent = ticker;
  document.getElementById("chart-hint").style.display = "none";

  refreshWatchers();
  await Promise.all([loadChart(ticker), loadOrderbook(ticker)]);
}

async function removeWatcher(ticker) {
  await fetch(`/api/watchers/${ticker}`, { method: "DELETE" });
  if (selectedTicker === ticker) {
    selectedTicker = null;
    document.getElementById("chart-ticker").textContent = "";
    document.getElementById("ob-ticker").textContent = "";
    document.getElementById("chart-hint").style.display = "block";
    if (priceChart) { priceChart.destroy(); priceChart = null; }
  }
  refreshWatchers();
}

// ── Price chart (Chart.js) ───────────────────────────────────────────────

async function loadChart(ticker) {
  const data = await api(`/api/watchers/${ticker}`);
  if (!data || data.error) return;

  const history = data.history || [];
  const labels = history.map(h => {
    const d = new Date(h.ts);
    return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  });
  const bidData = history.map(h => h.yes_bid);
  const askData = history.map(h => h.yes_ask);

  const entry = data.entry_cents || null;
  const stop = data.stop_cents || null;
  const tp = data.take_profit_cents || null;

  const datasets = [
    {
      label: "YES Bid",
      data: bidData,
      borderColor: "#00e676",
      backgroundColor: "rgba(0,230,118,0.1)",
      borderWidth: 2,
      pointRadius: 0,
      fill: false,
    },
    {
      label: "YES Ask",
      data: askData,
      borderColor: "#ff5252",
      backgroundColor: "rgba(255,82,82,0.1)",
      borderWidth: 2,
      pointRadius: 0,
      fill: false,
    },
  ];

  // Horizontal reference lines
  if (entry) {
    datasets.push({
      label: "Entry",
      data: Array(labels.length).fill(entry),
      borderColor: "#ffd740",
      borderWidth: 1,
      borderDash: [6, 3],
      pointRadius: 0,
      fill: false,
    });
  }
  if (stop) {
    datasets.push({
      label: "Stop",
      data: Array(labels.length).fill(stop),
      borderColor: "#ff1744",
      borderWidth: 1,
      borderDash: [4, 4],
      pointRadius: 0,
      fill: false,
    });
  }
  if (tp) {
    datasets.push({
      label: "Take Profit",
      data: Array(labels.length).fill(tp),
      borderColor: "#00e5ff",
      borderWidth: 1,
      borderDash: [4, 4],
      pointRadius: 0,
      fill: false,
    });
  }

  const ctx = document.getElementById("price-chart").getContext("2d");

  if (priceChart) priceChart.destroy();

  priceChart = new Chart(ctx, {
    type: "line",
    data: { labels, datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      interaction: { intersect: false, mode: "index" },
      plugins: {
        legend: { labels: { color: "#b0bec5", font: { size: 11 } } },
        tooltip: {
          backgroundColor: "#263238",
          titleColor: "#eceff1",
          bodyColor: "#b0bec5",
        },
      },
      scales: {
        x: {
          ticks: { color: "#78909c", maxTicksLimit: 12 },
          grid: { color: "rgba(255,255,255,0.05)" },
        },
        y: {
          title: { display: true, text: "Price (cents)", color: "#78909c" },
          ticks: { color: "#78909c" },
          grid: { color: "rgba(255,255,255,0.05)" },
        },
      },
    },
  });
}

// ── Orderbook visualization ──────────────────────────────────────────────

async function loadOrderbook(ticker) {
  const data = await api(`/api/orderbook/${ticker}?depth=10`);
  if (!data || data.error) return;

  const yesBids = (data.yes || []).slice().reverse();  // highest first
  const noBids = (data.no || []).slice().reverse();

  const maxQty = Math.max(
    ...yesBids.map(l => l[1]),
    ...noBids.map(l => l[1]),
    1
  );

  const yesBidsEl = document.getElementById("ob-yes-bids");
  const noBidsEl = document.getElementById("ob-no-bids");

  yesBidsEl.innerHTML = yesBids.map(([price, qty]) => {
    const pct = (qty / maxQty * 100).toFixed(1);
    return `<div class="ob-row">
      <div class="ob-bar ob-bar-bid" style="width:${pct}%"></div>
      <span class="ob-price">${price}c</span>
      <span class="ob-qty">${qty}</span>
    </div>`;
  }).join("") || '<div class="empty-msg">No bids</div>';

  noBidsEl.innerHTML = noBids.map(([price, qty]) => {
    const askCents = 100 - price;
    const pct = (qty / maxQty * 100).toFixed(1);
    return `<div class="ob-row">
      <div class="ob-bar ob-bar-ask" style="width:${pct}%"></div>
      <span class="ob-price">${price}c (ask ${askCents}c)</span>
      <span class="ob-qty">${qty}</span>
    </div>`;
  }).join("") || '<div class="empty-msg">No bids</div>';

  const summary = document.getElementById("ob-summary");
  if (data.best_yes_bid != null && data.best_yes_ask != null) {
    summary.innerHTML = `Bid: <strong>${data.best_yes_bid}c</strong> &mdash; Ask: <strong>${data.best_yes_ask}c</strong> &mdash; Spread: <strong>${data.spread}c</strong>`;
  } else {
    summary.innerHTML = "No book data";
  }
}

// ── Orders table ─────────────────────────────────────────────────────────

async function refreshOrders() {
  const data = await api("/api/orders");
  const tbody = document.getElementById("orders-body");

  if (!data || data.error || !data.orders || !data.orders.length) {
    tbody.innerHTML = '<tr><td colspan="8" class="empty-msg">No resting orders</td></tr>';
    return;
  }

  tbody.innerHTML = data.orders.map(o => {
    const price = o.yes_price != null ? o.yes_price + "c (YES)" :
                  o.no_price != null ? o.no_price + "c (NO)" : "--";
    const created = o.created_time ? new Date(o.created_time).toLocaleTimeString([], {hour:"2-digit",minute:"2-digit",second:"2-digit"}) : "--";
    const statusClass = o.status === "resting" ? "status-active" : "";

    return `<tr>
      <td class="ticker-cell">${o.ticker}</td>
      <td>${o.side || "--"}</td>
      <td>${o.action || "--"}</td>
      <td>${price}</td>
      <td>${o.count || 0}</td>
      <td>${o.remaining_count || 0}</td>
      <td><span class="status-badge ${statusClass}">${o.status}</span></td>
      <td>${created}</td>
    </tr>`;
  }).join("");
}

// ── Positions table ──────────────────────────────────────────────────────

async function refreshPositions() {
  const data = await api("/api/positions");
  const tbody = document.getElementById("positions-body");

  if (!data || data.error || !data.positions || !data.positions.length) {
    tbody.innerHTML = '<tr><td colspan="7" class="empty-msg">No positions</td></tr>';
    return;
  }

  tbody.innerHTML = data.positions.map(p => `
    <tr>
      <td class="ticker-cell">${p.ticker}</td>
      <td>${p.position}</td>
      <td>${p.resting_order_count || 0}</td>
      <td>${p.total_cost != null ? dollars(p.total_cost) : "--"}</td>
      <td>${p.fees_paid != null ? dollars(p.fees_paid) : "--"}</td>
      <td class="${pnlClass(p.realized_pnl)}">${p.realized_pnl != null ? dollars(p.realized_pnl) : "--"}</td>
      <td>${p.market_result || "--"}</td>
    </tr>
  `).join("");
}

// ── Poll loop ────────────────────────────────────────────────────────────

async function tick() {
  await Promise.all([
    refreshBalance(),
    refreshWatchers(),
    refreshOrders(),
    refreshPositions(),
  ]);

  if (selectedTicker) {
    await Promise.all([
      loadChart(selectedTicker),
      loadOrderbook(selectedTicker),
    ]);
  }

  document.getElementById("last-updated").textContent =
    new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

// Start
tick();
setInterval(tick, POLL_MS);
