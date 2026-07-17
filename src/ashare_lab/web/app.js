const state = {
  overview: null,
  result: null,
  chartMode: "equity",
  marketChart: null,
  equityChart: null,
};

const byId = (id) => document.getElementById(id);
const percent = new Intl.NumberFormat("zh-CN", { style: "percent", minimumFractionDigits: 2, maximumFractionDigits: 2 });
const money = new Intl.NumberFormat("zh-CN", { style: "currency", currency: "CNY", maximumFractionDigits: 2 });
const number = new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 2 });
const integer = new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 0 });
const riskRuleLabels = {
  max_position_weight: "单票仓位缩减",
  minimum_cash_weight: "现金缓冲缩减",
  volume_participation: "流动性缩减",
  max_drawdown: "组合回撤熔断",
  max_daily_loss: "单日亏损熔断",
  max_position_loss: "持仓止损",
  exit_blocked: "风险退出受阻",
};
const riskActionLabels = {
  resize: "订单已缩量",
  reject: "订单已拒绝",
  halt_and_liquidate: "停止新增风险并退出",
  retry_exit: "保留退出订单",
};

function setClock() {
  byId("clock").textContent = new Intl.DateTimeFormat("zh-CN", {
    hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false,
  }).format(new Date());
}

function showToast(message) {
  const toast = byId("toast");
  toast.textContent = message;
  toast.classList.add("visible");
  window.setTimeout(() => toast.classList.remove("visible"), 2600);
}

function signedPercent(value) {
  return `${value > 0 ? "+" : ""}${percent.format(value)}`;
}

function changeClass(element, value) {
  element.classList.remove("up", "down", "neutral");
  element.classList.add(value > 0 ? "up" : value < 0 ? "down" : "neutral");
}

function requireCharts() {
  if (!window.echarts) {
    showToast("图表组件加载失败，请检查网络后刷新");
    return false;
  }
  return true;
}

async function loadOverview() {
  const response = await fetch("/api/v1/market/overview");
  if (!response.ok) throw new Error(`overview request failed: ${response.status}`);
  state.overview = await response.json();
  renderOverview();
}

function renderOverview() {
  const overview = state.overview;
  if (!overview) return;
  byId("asOfDate").textContent = overview.as_of_date;
  byId("advancing").textContent = overview.advancing;
  byId("declining").textContent = overview.declining;
  byId("unchanged").textContent = overview.unchanged;
  const total = overview.advancing + overview.declining + overview.unchanged || 1;
  byId("advanceBar").style.width = `${(overview.advancing / total) * 100}%`;
  byId("flatBar").style.width = `${(overview.unchanged / total) * 100}%`;
  byId("declineBar").style.width = `${(overview.declining / total) * 100}%`;

  const points = overview.market_curve;
  const current = points.at(-1)?.value ?? 100;
  const first = points[0]?.value ?? 100;
  const change = current / first - 1;
  byId("marketValue").textContent = number.format(current);
  const changeElement = byId("marketChange");
  changeElement.textContent = `${signedPercent(change)} / 90日`;
  changeClass(changeElement, change);

  byId("watchCount").textContent = `${overview.watchlist.length} 只`;
  byId("watchlistBody").innerHTML = overview.watchlist.map((item) => `
    <tr>
      <td class="stock-name">${item.name}</td>
      <td class="stock-code">${item.symbol}</td>
      <td>${number.format(item.close)}</td>
      <td class="${item.change_percent >= 0 ? "up" : "down"}">${signedPercent(item.change_percent)}</td>
      <td>${integer.format(item.volume / 10000)} 万</td>
    </tr>`).join("");

  const symbol = byId("symbol");
  symbol.innerHTML = overview.watchlist.map((item) => `<option value="${item.symbol}">${item.name} · ${item.symbol}</option>`).join("");
  renderMarketChart();
}

function renderMarketChart() {
  if (!requireCharts() || !state.overview) return;
  const element = byId("marketChart");
  state.marketChart ??= window.echarts.init(element);
  const points = state.overview.market_curve;
  const up = (points.at(-1)?.value ?? 100) >= (points[0]?.value ?? 100);
  state.marketChart.setOption({
    animationDuration: 520,
    grid: { left: 20, right: 22, top: 18, bottom: 24, containLabel: true },
    tooltip: { trigger: "axis", borderWidth: 1, borderColor: "#dbe0da", backgroundColor: "#fff", textStyle: { color: "#17211c", fontSize: 11 }, valueFormatter: (value) => number.format(value) },
    xAxis: { type: "category", boundaryGap: false, data: points.map((point) => point.trading_date), axisLine: { lineStyle: { color: "#dbe0da" } }, axisTick: { show: false }, axisLabel: { color: "#7a857f", fontSize: 10, formatter: (value) => value.slice(5) } },
    yAxis: { type: "value", scale: true, splitNumber: 3, axisLabel: { color: "#7a857f", fontSize: 10 }, splitLine: { lineStyle: { color: "#edf0ec" } } },
    series: [{ type: "line", data: points.map((point) => point.value), symbol: "none", smooth: 0.16, lineStyle: { width: 2, color: up ? "#c83f44" : "#168061" }, areaStyle: { color: up ? "rgba(200,63,68,0.08)" : "rgba(22,128,97,0.08)" } }],
  });
}

function formPayload() {
  return {
    symbol: byId("symbol").value,
    strategy: byId("strategy").value,
    initial_cash: Number(byId("initialCash").value),
    short_window: Number(byId("shortWindow").value),
    long_window: Number(byId("longWindow").value),
    allocation: Number(byId("allocation").value) / 100,
    max_position_weight: Number(byId("maxPositionWeight").value) / 100,
    minimum_cash_weight: Number(byId("minimumCashWeight").value) / 100,
    max_volume_participation: Number(byId("maxVolumeParticipation").value) / 100,
    max_drawdown: Number(byId("riskMaxDrawdown").value) / 100,
    max_daily_loss: Number(byId("maxDailyLoss").value) / 100,
    max_position_loss: Number(byId("maxPositionLoss").value) / 100,
  };
}

async function runBacktest(event) {
  event?.preventDefault();
  const payload = formPayload();
  const error = byId("formError");
  if (payload.short_window >= payload.long_window) {
    error.textContent = "短周期必须小于长周期";
    return;
  }
  error.textContent = "";
  const button = byId("runButton");
  button.disabled = true;
  button.querySelector("span").textContent = "计算中...";
  try {
    const response = await fetch("/api/v1/backtests", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!response.ok) throw new Error(`backtest request failed: ${response.status}`);
    state.result = await response.json();
    renderBacktest();
    showToast("回测已完成，结果已按交易成本扣减");
  } catch (errorValue) {
    console.error(errorValue);
    error.textContent = "回测失败，请检查参数后重试";
  } finally {
    button.disabled = false;
    button.querySelector("span").textContent = "运行回测";
  }
}

function metricValue(id, value, formatter, classify = false) {
  const element = byId(id);
  element.textContent = formatter(value);
  if (classify) changeClass(element, value);
}

function renderBacktest() {
  const result = state.result;
  if (!result) return;
  const metrics = result.metrics;
  metricValue("totalReturn", metrics.total_return, percent.format, true);
  metricValue("annualReturn", metrics.annualized_return, percent.format, true);
  metricValue("maxDrawdown", metrics.max_drawdown, percent.format, false);
  metricValue("sharpeRatio", metrics.sharpe_ratio, (value) => number.format(value), false);
  byId("resultSymbol").textContent = `${result.name} · ${result.symbol}`;
  byId("resultTitle").textContent = state.chartMode === "equity" ? "策略净值" : "策略回撤";
  byId("tradeCount").textContent = metrics.trade_count;
  byId("winRate").textContent = percent.format(metrics.win_rate);
  byId("volatility").textContent = percent.format(metrics.annualized_volatility);
  byId("totalFees").textContent = money.format(metrics.total_fees);
  renderGovernance();
  renderEquityChart();
  renderTrades();
}

function drawdowns(curve) {
  let peak = curve[0]?.equity ?? 1;
  return curve.map((point) => {
    peak = Math.max(peak, point.equity);
    return point.equity / peak - 1;
  });
}

function renderEquityChart() {
  if (!requireCharts() || !state.result) return;
  state.equityChart ??= window.echarts.init(byId("equityChart"));
  const curve = state.result.equity_curve;
  const isEquity = state.chartMode === "equity";
  const values = isEquity ? curve.map((point) => point.equity) : drawdowns(curve);
  byId("resultTitle").textContent = isEquity ? "策略净值" : "策略回撤";
  state.equityChart.setOption({
    animationDuration: 480,
    grid: { left: 18, right: 24, top: 26, bottom: 30, containLabel: true },
    tooltip: { trigger: "axis", borderWidth: 1, borderColor: "#dbe0da", backgroundColor: "#fff", textStyle: { color: "#17211c", fontSize: 11 }, valueFormatter: (value) => isEquity ? money.format(value) : percent.format(value) },
    xAxis: { type: "category", boundaryGap: false, data: curve.map((point) => point.trading_date), axisLine: { lineStyle: { color: "#dbe0da" } }, axisTick: { show: false }, axisLabel: { color: "#7a857f", fontSize: 10, formatter: (value) => value.slice(2, 7) } },
    yAxis: { type: "value", scale: isEquity, axisLabel: { color: "#7a857f", fontSize: 10, formatter: (value) => isEquity ? `${number.format(value / 10000)}万` : percent.format(value) }, splitLine: { lineStyle: { color: "#edf0ec" } } },
    dataZoom: [{ type: "inside", start: 0, end: 100 }],
    series: [{ type: "line", data: values, symbol: "none", smooth: 0.08, lineStyle: { width: 2, color: isEquity ? "#285d7b" : "#168061" }, areaStyle: { color: isEquity ? "rgba(40,93,123,0.08)" : "rgba(22,128,97,0.09)" }, markLine: isEquity ? undefined : { symbol: "none", label: { show: false }, lineStyle: { color: "#bac4bc" }, data: [{ yAxis: 0 }] } }],
  }, true);
}

function renderTrades() {
  const trades = state.result?.trades ?? [];
  if (!trades.length) {
    byId("tradesBody").innerHTML = '<tr><td colspan="7" class="empty-cell">当前参数未产生有效成交</td></tr>';
    return;
  }
  byId("tradesBody").innerHTML = trades.slice().reverse().map((trade) => {
    const fees = trade.commission + trade.stamp_duty;
    const pnl = trade.realized_pnl;
    return `<tr>
      <td>${trade.trading_date}</td>
      <td><span class="${trade.side === "buy" ? "side-buy" : "side-sell"}">${trade.side === "buy" ? "买入" : "卖出"}</span></td>
      <td>${integer.format(trade.quantity)}</td>
      <td>${number.format(trade.price)}</td>
      <td>${money.format(trade.notional)}</td>
      <td>${money.format(fees)}</td>
      <td class="${pnl === null ? "" : pnl >= 0 ? "up" : "down"}">${pnl === null ? "--" : money.format(pnl)}</td>
    </tr>`;
  }).join("");
}

function renderGovernance() {
  const result = state.result;
  if (!result) return;
  const quality = result.data_quality;
  const methodology = result.methodology;
  const events = result.risk_events;
  const badge = byId("qualityBadge");
  badge.classList.remove("pending", "passed", "failed");
  badge.classList.add(quality.passed ? "passed" : "failed");
  badge.textContent = quality.passed ? "数据门禁通过" : "数据门禁失败";
  byId("rulebookVersion").textContent = `v${methodology.rulebook_version}`;
  byId("signalTiming").textContent = methodology.signal_timing === "close_to_next_open" ? "收盘 → 次日开盘" : methodology.signal_timing;
  byId("dataBasis").textContent = quality.price_basis === "raw" ? "原始成交价" : quality.price_basis;
  byId("pointInTime").textContent = quality.point_in_time ? "已通过" : "未通过";
  byId("riskEventCount").textContent = events.length;
  const halted = events.some((event) => event.action === "halt_and_liquidate");
  byId("riskState").textContent = halted ? "已熔断" : "正常";
  byId("riskState").className = halted ? "down" : "up";

  if (!events.length) {
    byId("riskEventList").innerHTML = '<div class="risk-empty"><i data-lucide="shield-check"></i><span>未触发缩量、拒单或熔断</span></div>';
    window.lucide?.createIcons();
    return;
  }
  byId("riskEventList").innerHTML = events.slice().reverse().map((event) => {
    const isCircuit = event.action === "halt_and_liquidate" || event.action === "retry_exit";
    const returnRule = ["max_drawdown", "max_daily_loss", "max_position_loss"].includes(event.rule);
    const detail = returnRule
      ? `观测 ${percent.format(event.observed)} / 阈值 -${percent.format(event.limit)}`
      : `${riskActionLabels[event.action] ?? event.action} / 限制 ${percent.format(event.limit)}`;
    return `<div class="risk-event ${isCircuit ? "circuit" : "adjustment"}">
      <time>${event.trading_date}</time>
      <strong>${riskRuleLabels[event.rule] ?? event.rule}</strong>
      <span>${detail}</span>
    </div>`;
  }).join("");
}

function bindEvents() {
  byId("backtestForm").addEventListener("submit", runBacktest);
  byId("allocation").addEventListener("input", (event) => { byId("allocationOutput").textContent = `${event.target.value}%`; });
  byId("resetButton").addEventListener("click", () => {
    byId("backtestForm").reset();
    byId("allocationOutput").textContent = "95%";
    byId("formError").textContent = "";
  });
  document.querySelectorAll("[data-chart-mode]").forEach((button) => {
    button.addEventListener("click", () => {
      state.chartMode = button.dataset.chartMode;
      document.querySelectorAll("[data-chart-mode]").forEach((item) => {
        item.classList.toggle("active", item === button);
        item.setAttribute("aria-selected", String(item === button));
      });
      renderEquityChart();
    });
  });
  document.querySelectorAll(".nav-item").forEach((item) => {
    item.addEventListener("click", () => {
      document.querySelectorAll(".nav-item").forEach((nav) => nav.classList.remove("active"));
      item.classList.add("active");
    });
  });
  window.addEventListener("resize", () => {
    state.marketChart?.resize();
    state.equityChart?.resize();
  });
}

async function init() {
  setClock();
  window.setInterval(setClock, 1000);
  bindEvents();
  window.lucide?.createIcons();
  try {
    await loadOverview();
    await runBacktest();
  } catch (error) {
    console.error(error);
    showToast("研究台初始化失败，请确认本地服务正在运行");
  }
}

init();
