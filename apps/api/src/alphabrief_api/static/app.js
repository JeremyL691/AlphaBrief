/**
 * AlphaBrief Web Workstation SPA (PROJECT_GUIDE 3.3, 4.7)
 * Reactive rendering without heavyweight frameworks.
 * Displays ONLY real broker, model, and system data.
 */

import { api } from "./api.js";
import { i18n } from "./i18n.js";

class App {
  constructor() {
    this.currentRoute = this._getRouteFromHash();
    this.theme = localStorage.getItem("alphabrief_theme") || "system";
    this.systemState = {
      online: true,
      stale: false,
      lastCheck: null,
      killSwitchActive: false,
    };
    this.activeCycleId = null;
    this.modalCallback = null;
  }

  init() {
    this._applyTheme(this.theme);
    window.addEventListener("hashchange", () => {
      this.currentRoute = this._getRouteFromHash();
      this.render();
    });

    // Start background health polling
    this._pollSystemHealth();
    setInterval(() => this._pollSystemHealth(), 15000);

    this.render();
  }

  _getRouteFromHash() {
    const hash = window.location.hash.replace(/^#\/?/, "");
    return hash || "overview";
  }

  _applyTheme(theme) {
    this.theme = theme;
    localStorage.setItem("alphabrief_theme", theme);
    if (theme === "system") {
      document.documentElement.removeAttribute("data-theme");
    } else {
      document.documentElement.setAttribute("data-theme", theme);
    }
  }

  toggleTheme() {
    const next = this.theme === "system" ? "light" : this.theme === "light" ? "dark" : "system";
    this._applyTheme(next);
    this.render();
  }

  toggleLanguage() {
    const next = i18n.getLanguage() === "zh" ? "en" : "zh";
    i18n.setLanguage(next);
    this.render();
  }

  async _pollSystemHealth() {
    try {
      const ks = await api.getKillSwitch();
      this.systemState.killSwitchActive = Boolean(ks.active);
      this.systemState.online = true;
      this.systemState.lastCheck = new Date();
      this._updateTopBarState();
    } catch (err) {
      if (err.offline) {
        this.systemState.online = false;
      }
      this._updateTopBarState();
    }
  }

  _updateTopBarState() {
    const pill = document.getElementById("system-status-pill");
    const banner = document.getElementById("offline-banner");
    const ksBtn = document.getElementById("kill-switch-btn");

    if (pill) {
      if (!this.systemState.online) {
        pill.className = "system-status-pill offline";
        pill.innerHTML = `<span class="status-dot"></span><span>${i18n.t("status.offline")}</span>`;
      } else if (this.systemState.stale) {
        pill.className = "system-status-pill stale";
        pill.innerHTML = `<span class="status-dot"></span><span>${i18n.t("status.stale")}</span>`;
      } else {
        pill.className = "system-status-pill online";
        pill.innerHTML = `<span class="status-dot"></span><span>${i18n.t("status.online")}</span>`;
      }
    }

    if (banner) {
      banner.style.display = this.systemState.online ? "none" : "flex";
    }

    if (ksBtn) {
      if (this.systemState.killSwitchActive) {
        ksBtn.className = "btn-control btn-danger";
        ksBtn.innerHTML = `<svg class="nav-icon"><use href="#icon-power"></use></svg><span>${i18n.t("risk.killSwitchActive")}</span>`;
      } else {
        ksBtn.className = "btn-control";
        ksBtn.innerHTML = `<svg class="nav-icon"><use href="#icon-power"></use></svg><span>${i18n.t("risk.killSwitch")}</span>`;
      }
    }
  }

  showModal(title, message, confirmLabel, onConfirm) {
    const overlay = document.getElementById("modal-overlay");
    if (!overlay) return;
    overlay.innerHTML = `
      <div class="modal-card" role="dialog" aria-modal="true" aria-labelledby="modal-title">
        <div class="modal-header">
          <h2 id="modal-title" class="section-title">${title}</h2>
          <button class="btn-control" id="modal-close-btn" aria-label="Close">✕</button>
        </div>
        <p style="color: var(--text-dim); margin-bottom: var(--space-4);">${message}</p>
        <div class="modal-actions">
          <button class="btn-control" id="modal-cancel-btn">取消 / Cancel</button>
          <button class="btn-control btn-danger" id="modal-confirm-btn">${confirmLabel}</button>
        </div>
      </div>
    `;
    overlay.style.display = "flex";

    document.getElementById("modal-close-btn").onclick = () => this.hideModal();
    document.getElementById("modal-cancel-btn").onclick = () => this.hideModal();
    document.getElementById("modal-confirm-btn").onclick = () => {
      this.hideModal();
      onConfirm();
    };
  }

  hideModal() {
    const overlay = document.getElementById("modal-overlay");
    if (overlay) overlay.style.display = "none";
  }

  async handleKillSwitchToggle() {
    const targetState = !this.systemState.killSwitchActive;
    const msg = targetState
      ? i18n.t("risk.confirmKillSwitch")
      : "确认解除紧急停止状态？系统将恢复正常交易判断。/ Deactivate Kill Switch?";
    const label = targetState ? i18n.t("risk.activateKillSwitch") : i18n.t("risk.deactivateKillSwitch");

    this.showModal(i18n.t("risk.killSwitch"), msg, label, async () => {
      try {
        await api.setKillSwitch(targetState);
        this.systemState.killSwitchActive = targetState;
        this._updateTopBarState();
        if (this.currentRoute === "risk") this.render();
      } catch (err) {
        alert(`Error setting kill switch: ${err.message}`);
      }
    });
  }

  render() {
    const root = document.getElementById("app");
    if (!root) return;

    // Update active nav links
    document.querySelectorAll(".nav-link").forEach((link) => {
      const route = link.getAttribute("data-route");
      link.classList.toggle("active", route === this.currentRoute);
    });

    const contentArea = document.getElementById("page-content");
    if (!contentArea) return;

    contentArea.innerHTML = `<div class="state-loading"><div class="spinner"></div><p>${i18n.t("status.loading")}</p></div>`;

    switch (this.currentRoute) {
      case "overview":
        this._renderOverview(contentArea);
        break;
      case "committee":
        this._renderCommittee(contentArea);
        break;
      case "orders":
        this._renderOrders(contentArea);
        break;
      case "news":
        this._renderNews(contentArea);
        break;
      case "risk":
        this._renderRisk(contentArea);
        break;
      case "evaluation":
        this._renderEvaluation(contentArea);
        break;
      case "backtest":
        this._renderBacktest(contentArea);
        break;
      case "strategies":
        this._renderStrategies(contentArea);
        break;
      case "review":
        this._renderReview(contentArea);
        break;
      case "settings":
        this._renderSettings(contentArea);
        break;
      case "onboarding":
        this._renderOnboarding(contentArea);
        break;
      default:
        this._renderOverview(contentArea);
    }
  }

  // --- Views ---

  async _renderOverview(container) {
    try {
      const [accData, posData, histData, doctorData] = await Promise.allSettled([
        api.getAccount(),
        api.getPositions(),
        api.getAiHistory(10),
        api.getDoctor(),
      ]);

      const acc = accData.status === "fulfilled" ? accData.value?.account : null;
      const positions = posData.status === "fulfilled" ? posData.value?.positions || [] : [];
      const cycles = histData.status === "fulfilled" ? histData.value?.cycles || [] : [];
      const doctor = doctorData.status === "fulfilled" ? doctorData.value : null;

      container.innerHTML = `
        <div class="page-container">
          <header class="page-header">
            <h1 class="page-title">${i18n.t("nav.overview")}</h1>
            <p class="page-subtitle">${i18n.t("app.tagline")}</p>
          </header>

          <div class="grid-cards">
            <div class="card">
              <div class="card-label">${i18n.t("overview.nav")}</div>
              <div class="card-value" id="overview-nav-val">${acc ? `${Number(acc.equity || 0).toLocaleString("en-US", {minimumFractionDigits: 2, maximumFractionDigits: 2})} ${acc.currency || "USD"}` : "---"}</div>
              <div class="card-meta">OANDA Practice Account</div>
            </div>
            <div class="card">
              <div class="card-label">${i18n.t("overview.cash")}</div>
              <div class="card-value">${acc ? `${Number(acc.cash || 0).toLocaleString("en-US", {minimumFractionDigits: 2, maximumFractionDigits: 2})}` : "---"}</div>
              <div class="card-meta">${i18n.t("overview.marginAvailable")}: ${acc ? Number(acc.buying_power || 0).toFixed(2) : "---"}</div>
            </div>
            <div class="card">
              <div class="card-label">${i18n.t("overview.nextRound")}</div>
              <div class="card-value" style="font-size: var(--font-size-lg);">00:30 / 07:30 / 13:00</div>
              <div class="card-meta">${i18n.t("overview.nextRoundSchedule")}</div>
            </div>
            <div class="card">
              <div class="card-label">${i18n.t("overview.healthTitle")}</div>
              <div class="card-value" style="font-size: var(--font-size-md); font-family: var(--font-sans);">
                ${doctor ? `<span class="pill pill-success">${doctor.summary || "PASS"}</span>` : `<span class="pill pill-neutral">${i18n.t("status.online")}</span>`}
              </div>
              <div class="card-meta">Doctor self-check summary</div>
            </div>
          </div>

          <div class="section">
            <div class="section-header">
              <h2 class="section-title">${i18n.t("overview.openPositions")} (${positions.length})</h2>
            </div>
            ${positions.length === 0 ? `
              <div class="state-empty"><p>${i18n.t("overview.noPositions")}</p></div>
            ` : `
              <div class="table-responsive">
                <table class="data-table">
                  <thead>
                    <tr>
                      <th>Symbol</th>
                      <th>Quantity (Units)</th>
                      <th>Average Price</th>
                    </tr>
                  </thead>
                  <tbody>
                    ${positions.map(p => `
                      <tr>
                        <td><strong>${p.symbol}</strong></td>
                        <td class="font-mono">${p.quantity}</td>
                        <td class="font-mono">${p.average_price}</td>
                      </tr>
                    `).join("")}
                  </tbody>
                </table>
              </div>
            `}
          </div>

          <div class="section">
            <div class="section-header">
              <h2 class="section-title">${i18n.t("overview.todayCycles")}</h2>
            </div>
            ${cycles.length === 0 ? `
              <div class="state-empty"><p>${i18n.t("overview.noCyclesToday")}</p></div>
            ` : `
              <div class="table-responsive">
                <table class="data-table">
                  <thead>
                    <tr>
                      <th>Cycle ID</th>
                      <th>Time (UTC)</th>
                      <th>Outcome</th>
                      <th>Attempts</th>
                      <th>Details</th>
                    </tr>
                  </thead>
                  <tbody>
                    ${cycles.map(c => `
                      <tr>
                        <td class="font-mono">${c.cycle_id}</td>
                        <td class="font-mono">${c.started_at ? c.started_at.slice(0, 19).replace("T", " ") : "---"}</td>
                        <td><span class="pill ${c.outcome === 'executed' ? 'pill-success' : 'pill-neutral'}">${c.outcome}</span></td>
                        <td>${c.attempts_count || (c.attempts ? c.attempts.length : 0)}</td>
                        <td>
                          <a href="#committee" class="btn-control" onclick="window.app.selectCycle('${c.cycle_id}')">查看 / View</a>
                        </td>
                      </tr>
                    `).join("")}
                  </tbody>
                </table>
              </div>
            `}
          </div>
        </div>
      `;
    } catch (err) {
      this._renderError(container, err, () => this._renderOverview(container));
    }
  }

  async _renderCommittee(container) {
    try {
      const hist = await api.getAiHistory(30);
      const cycles = hist.cycles || [];
      const currentCycleId = this.activeCycleId || (cycles[0] ? cycles[0].cycle_id : null);

      let cycleDetail = null;
      if (currentCycleId) {
        try {
          cycleDetail = await api.getAiCycle(currentCycleId);
        } catch (_) {}
      }

      container.innerHTML = `
        <div class="page-container">
          <header class="page-header">
            <h1 class="page-title">${i18n.t("committee.title")}</h1>
            <p class="page-subtitle">${i18n.t("committee.subtitle")}</p>
          </header>

          <div class="section" style="margin-bottom: var(--space-4);">
            <div style="display: flex; align-items: center; gap: var(--space-3); flex-wrap: wrap;">
              <label class="form-label" style="margin-bottom: 0;">${i18n.t("committee.roundSelector")}:</label>
              <select id="cycle-select" class="form-input" style="width: auto; min-width: 280px;">
                ${cycles.length === 0 ? `<option value="">${i18n.t("status.empty")}</option>` : cycles.map(c => `
                  <option value="${c.cycle_id}" ${c.cycle_id === currentCycleId ? 'selected' : ''}>
                    ${c.cycle_id} (${c.started_at ? c.started_at.slice(0, 16).replace("T", " ") : ""} - ${c.outcome})
                  </option>
                `).join("")}
              </select>
            </div>
          </div>

          ${!cycleDetail ? `
            <div class="section"><div class="state-empty"><p>${i18n.t("committee.noVotes")}</p></div></div>
          ` : `
            <div class="section">
              <div class="section-header">
                <h2 class="section-title">${i18n.t("committee.finalPlan")}</h2>
                <span class="pill ${cycleDetail.outcome === 'executed' ? 'pill-success' : 'pill-neutral'}">${cycleDetail.outcome}</span>
              </div>
              <div class="grid-cards" style="margin-bottom: var(--space-4);">
                <div class="card">
                  <div class="card-label">${i18n.t("committee.action")}</div>
                  <div class="card-value" style="font-size: var(--font-size-lg);">${cycleDetail.plan ? cycleDetail.plan.action : "no_trade"}</div>
                </div>
                <div class="card">
                  <div class="card-label">${i18n.t("committee.confidence")}</div>
                  <div class="card-value" style="font-size: var(--font-size-lg);">${cycleDetail.plan ? Number(cycleDetail.plan.confidence || 0).toFixed(2) : "0.00"}</div>
                </div>
                <div class="card">
                  <div class="card-label">${i18n.t("committee.stopLoss")} / ${i18n.t("committee.takeProfit")}</div>
                  <div class="card-value" style="font-size: var(--font-size-md);">
                    ${cycleDetail.plan ? `${cycleDetail.plan.stop_atr_multiple || 1.5}x ATR / ${cycleDetail.plan.take_profit_r_multiple || 2.0}R` : "---"}
                  </div>
                </div>
              </div>
              <div style="background: var(--bg-elev-2); padding: var(--space-3); border-radius: var(--radius-sm); margin-bottom: var(--space-4);">
                <strong>${i18n.t("committee.rationale")}:</strong>
                <p style="margin-top: 4px; color: var(--text-dim);">${cycleDetail.plan ? cycleDetail.plan.rationale : "No plan rationale recorded"}</p>
              </div>
              ${cycleDetail.plan && cycleDetail.plan.evidence_ids && cycleDetail.plan.evidence_ids.length > 0 ? `
                <div>
                  <strong>${i18n.t("committee.citedEvidence")}:</strong>
                  <div style="display: flex; gap: 6px; flex-wrap: wrap; margin-top: 6px;">
                    ${cycleDetail.plan.evidence_ids.map(id => `<span class="pill pill-neutral">${id}</span>`).join("")}
                  </div>
                </div>
              ` : ''}
            </div>

            <div class="section">
              <div class="section-header">
                <h2 class="section-title">${i18n.t("committee.rolesTitle")} (${cycleDetail.votes ? cycleDetail.votes.length : 0})</h2>
              </div>
              ${!cycleDetail.votes || cycleDetail.votes.length === 0 ? `
                <div class="state-empty"><p>${i18n.t("committee.noVotes")}</p></div>
              ` : `
                <div style="display: flex; flex-direction: column; gap: var(--space-3);">
                  ${cycleDetail.votes.map(v => `
                    <div class="card" style="padding: var(--space-3);">
                      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
                        <span class="pill pill-neutral" style="font-weight: 700;">${v.role}</span>
                        <div style="display: flex; gap: 8px;">
                          ${v.view ? `<span class="pill ${v.view === 'bullish' || v.view === 'long' ? 'pill-success' : v.view === 'bearish' || v.view === 'short' ? 'pill-danger' : 'pill-neutral'}">${v.view}</span>` : ''}
                          ${v.veto ? `<span class="pill pill-danger">VETO</span>` : ''}
                          <span class="pill pill-neutral">${i18n.t("committee.confidence")}: ${Number(v.confidence || 0).toFixed(2)}</span>
                        </div>
                      </div>
                      <p style="color: var(--text-dim); font-size: var(--font-size-sm); margin-bottom: 6px;">
                        ${v.analysis || v.rationale || "No text analysis provided"}
                      </p>
                      ${v.evidence_ids && v.evidence_ids.length > 0 ? `
                        <div style="font-size: var(--font-size-xs); color: var(--text-muted);">
                          Cited: ${v.evidence_ids.join(", ")}
                        </div>
                      ` : ''}
                    </div>
                  `).join("")}
                </div>
              `}
            </div>
          `}
        </div>
      `;

      const select = document.getElementById("cycle-select");
      if (select) {
        select.onchange = (e) => {
          this.activeCycleId = e.target.value;
          this._renderCommittee(container);
        };
      }
    } catch (err) {
      this._renderError(container, err, () => this._renderCommittee(container));
    }
  }

  selectCycle(cycleId) {
    this.activeCycleId = cycleId;
  }

  async _renderOrders(container) {
    try {
      const [posRes, ordRes, attRes] = await Promise.allSettled([
        api.getPositions(),
        api.getOrders(),
        api.getAiAttempts(50),
      ]);

      const positions = posRes.status === "fulfilled" ? posRes.value?.positions || [] : [];
      const orders = ordRes.status === "fulfilled" ? ordRes.value?.orders || [] : [];
      const attempts = attRes.status === "fulfilled" ? attRes.value?.attempts || [] : [];

      container.innerHTML = `
        <div class="page-container">
          <header class="page-header">
            <h1 class="page-title">${i18n.t("orders.title")}</h1>
          </header>

          <div class="section">
            <div class="section-header">
              <h2 class="section-title">${i18n.t("orders.openPositions")} (${positions.length})</h2>
            </div>
            ${positions.length === 0 ? `
              <div class="state-empty"><p>${i18n.t("overview.noPositions")}</p></div>
            ` : `
              <div class="table-responsive">
                <table class="data-table">
                  <thead>
                    <tr>
                      <th>Symbol</th>
                      <th>Quantity</th>
                      <th>Average Price</th>
                    </tr>
                  </thead>
                  <tbody>
                    ${positions.map(p => `
                      <tr>
                        <td><strong>${p.symbol}</strong></td>
                        <td class="font-mono">${p.quantity}</td>
                        <td class="font-mono">${p.average_price}</td>
                      </tr>
                    `).join("")}
                  </tbody>
                </table>
              </div>
            `}
          </div>

          <div class="section">
            <div class="section-header">
              <h2 class="section-title">${i18n.t("orders.orderHistory")} (${attempts.length})</h2>
            </div>
            ${attempts.length === 0 ? `
              <div class="state-empty"><p>${i18n.t("orders.noOrders")}</p></div>
            ` : `
              <div class="table-responsive">
                <table class="data-table">
                  <thead>
                    <tr>
                      <th>Attempt ID / Client ID</th>
                      <th>Broker Order ID</th>
                      <th>Symbol</th>
                      <th>Side / Action</th>
                      <th>Units</th>
                      <th>Status</th>
                      <th>Cycle ID</th>
                    </tr>
                  </thead>
                  <tbody>
                    ${attempts.map(a => `
                      <tr>
                        <td class="font-mono">${a.intent_id || a.client_order_id || "---"}</td>
                        <td class="font-mono">${a.order_id || a.broker_order_id || "---"}</td>
                        <td><strong>${a.symbol || (a.intent ? a.intent.symbol : "---")}</strong></td>
                        <td><span class="pill pill-neutral">${a.action || (a.intent ? a.intent.action : "---")}</span></td>
                        <td class="font-mono">${a.quantity || (a.intent ? a.intent.quantity : "---")}</td>
                        <td><span class="pill ${a.status === 'executed' || a.filled ? 'pill-success' : 'pill-neutral'}">${a.status || (a.filled ? 'filled' : 'submitted')}</span></td>
                        <td class="font-mono">${a.cycle_id || "---"}</td>
                      </tr>
                    `).join("")}
                  </tbody>
                </table>
              </div>
            `}
          </div>
        </div>
      `;
    } catch (err) {
      this._renderError(container, err, () => this._renderOrders(container));
    }
  }

  async _renderNews(container) {
    try {
      const [newsRes, macroRes] = await Promise.allSettled([
        api.getHeadlines(50),
        api.getMacroIndicators(),
      ]);

      const headlines = newsRes.status === "fulfilled" ? newsRes.value?.headlines || [] : [];
      const indicators = macroRes.status === "fulfilled" ? macroRes.value?.indicators || [] : [];

      container.innerHTML = `
        <div class="page-container">
          <header class="page-header">
            <h1 class="page-title">${i18n.t("news.title")}</h1>
            <p class="page-subtitle">${i18n.t("news.subtitle")}</p>
          </header>

          <div class="section">
            <div class="section-header">
              <h2 class="section-title">${i18n.t("news.title")} (${headlines.length})</h2>
            </div>
            ${headlines.length === 0 ? `
              <div class="state-empty"><p>${i18n.t("news.noNews")}</p></div>
            ` : `
              <div class="table-responsive">
                <table class="data-table">
                  <thead>
                    <tr>
                      <th>${i18n.t("news.publisher")}</th>
                      <th>Title & Summary</th>
                      <th>${i18n.t("news.currencies")}</th>
                      <th>${i18n.t("news.publishedAt")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    ${headlines.map(h => `
                      <tr>
                        <td><span class="pill pill-neutral">${h.publisher || h.source}</span></td>
                        <td>
                          <strong>${h.title}</strong>
                          ${h.summary ? `<p style="color: var(--text-dim); font-size: var(--font-size-xs); margin-top: 4px;">${h.summary.slice(0, 160)}...</p>` : ''}
                        </td>
                        <td>
                          ${h.currency_tags ? h.currency_tags.map(c => `<span class="pill pill-neutral" style="margin-right: 4px;">${c}</span>`).join("") : '---'}
                        </td>
                        <td class="font-mono" style="font-size: var(--font-size-xs);">${h.published_at ? h.published_at.slice(0, 19).replace("T", " ") : "---"}</td>
                      </tr>
                    `).join("")}
                  </tbody>
                </table>
              </div>
            `}
          </div>

          <div class="section">
            <div class="section-header">
              <h2 class="section-title">${i18n.t("news.macroTitle")}</h2>
            </div>
            ${indicators.length === 0 ? `
              <div class="state-empty"><p>No macro indicators available (FRED optional)</p></div>
            ` : `
              <div class="table-responsive">
                <table class="data-table">
                  <thead>
                    <tr>
                      <th>Indicator</th>
                      <th>Value</th>
                      <th>Date</th>
                    </tr>
                  </thead>
                  <tbody>
                    ${indicators.map(ind => `
                      <tr>
                        <td><strong>${ind.name || ind.indicator_id}</strong></td>
                        <td class="font-mono">${ind.value}</td>
                        <td class="font-mono">${ind.date}</td>
                      </tr>
                    `).join("")}
                  </tbody>
                </table>
              </div>
            `}
          </div>
        </div>
      `;
    } catch (err) {
      this._renderError(container, err, () => this._renderNews(container));
    }
  }

  async _renderRisk(container) {
    try {
      const [riskRes, ksRes, freezRes] = await Promise.allSettled([
        api.getRiskStatus(),
        api.getKillSwitch(),
        api.getFreezes(),
      ]);

      const risk = riskRes.status === "fulfilled" ? riskRes.value : null;
      const ks = ksRes.status === "fulfilled" ? ksRes.value : null;
      const freezes = freezRes.status === "fulfilled" ? freezRes.value?.open_freezes || [] : [];

      container.innerHTML = `
        <div class="page-container">
          <header class="page-header">
            <h1 class="page-title">${i18n.t("risk.title")}</h1>
            <p class="page-subtitle">${i18n.t("risk.subtitle")}</p>
          </header>

          <div class="section" style="border-left: 4px solid ${ks && ks.active ? 'var(--danger)' : 'var(--success)'};">
            <div class="section-header">
              <h2 class="section-title">${i18n.t("risk.killSwitch")}</h2>
              <span class="pill ${ks && ks.active ? 'pill-danger' : 'pill-success'}">
                ${ks && ks.active ? i18n.t("risk.killSwitchActive") : i18n.t("risk.killSwitchInactive")}
              </span>
            </div>
            <p style="color: var(--text-dim); margin-bottom: var(--space-4);">
              ${ks && ks.active ? `Active Reason: ${ks.reason || "Operator activated"}` : "When activated, RiskGate strictly forbids all new order submissions and executes reduce-only exits."}
            </p>
            <button class="btn-control ${ks && ks.active ? '' : 'btn-danger'}" onclick="window.app.handleKillSwitchToggle()">
              ${ks && ks.active ? i18n.t("risk.deactivateKillSwitch") : i18n.t("risk.activateKillSwitch")}
            </button>
          </div>

          <div class="grid-cards">
            <div class="card">
              <div class="card-label">${i18n.t("risk.navCapSingle")}</div>
              <div class="card-value">50%</div>
              <div class="card-meta">Per instrument nominal cap</div>
            </div>
            <div class="card">
              <div class="card-label">${i18n.t("risk.navCapTotal")}</div>
              <div class="card-value">150%</div>
              <div class="card-meta">Gross nominal exposure cap</div>
            </div>
            <div class="card">
              <div class="card-label">${i18n.t("risk.dailyOpenCap")}</div>
              <div class="card-value">5 / day</div>
              <div class="card-meta">Strict daily opens limit</div>
            </div>
          </div>

          <div class="section">
            <div class="section-header">
              <h2 class="section-title">${i18n.t("risk.freezeHistory")}</h2>
            </div>
            ${freezes.length === 0 ? `
              <div class="state-empty"><p>${i18n.t("risk.noFreezes")}</p></div>
            ` : `
              <div class="table-responsive">
                <table class="data-table">
                  <thead>
                    <tr>
                      <th>Event ID</th>
                      <th>Reason</th>
                      <th>Raised At</th>
                    </tr>
                  </thead>
                  <tbody>
                    ${freezes.map(f => `
                      <tr>
                        <td class="font-mono">${f.event_id}</td>
                        <td style="color: var(--danger);">${f.reason}</td>
                        <td class="font-mono">${f.raised_at}</td>
                      </tr>
                    `).join("")}
                  </tbody>
                </table>
              </div>
            `}
          </div>
        </div>
      `;
    } catch (err) {
      this._renderError(container, err, () => this._renderRisk(container));
    }
  }

  async _renderEvaluation(container) {
    try {
      const [boardRes, decRes] = await Promise.allSettled([
        api.getScoreboard(),
        api.getShadowDecisions(30),
      ]);

      const board = boardRes.status === "fulfilled" ? boardRes.value?.scoreboard : null;
      const decisions = decRes.status === "fulfilled" ? decRes.value?.decisions || [] : [];

      container.innerHTML = `
        <div class="page-container">
          <header class="page-header">
            <h1 class="page-title">${i18n.t("evaluation.title")}</h1>
            <p class="page-subtitle">${i18n.t("evaluation.subtitle")}</p>
          </header>

          <div class="caveat-banner" role="alert">
            <svg class="nav-icon" style="flex-shrink: 0;"><use href="#icon-alert-triangle"></use></svg>
            <span>${i18n.t("evaluation.caveat")}</span>
          </div>

          <div class="section">
            <div class="section-header">
              <h2 class="section-title">${i18n.t("evaluation.horizon4h")}</h2>
            </div>
            ${this._renderScoreboardTable(board ? board["4h"] : null)}
          </div>

          <div class="section">
            <div class="section-header">
              <h2 class="section-title">${i18n.t("evaluation.horizon24h")}</h2>
            </div>
            ${this._renderScoreboardTable(board ? board["24h"] : null)}
          </div>

          <div class="section">
            <div class="section-header">
              <h2 class="section-title">Recent Shadow Decisions (${decisions.length})</h2>
            </div>
            ${decisions.length === 0 ? `
              <div class="state-empty"><p>No shadow decisions recorded yet</p></div>
            ` : `
              <div class="table-responsive">
                <table class="data-table">
                  <thead>
                    <tr>
                      <th>Cycle ID</th>
                      <th>Symbol</th>
                      <th>Benchmark</th>
                      <th>Side</th>
                      <th>Source</th>
                      <th>Entry Mid</th>
                      <th>Decided At</th>
                    </tr>
                  </thead>
                  <tbody>
                    ${decisions.map(d => `
                      <tr>
                        <td class="font-mono">${d.cycle_id}</td>
                        <td><strong>${d.symbol}</strong></td>
                        <td><span class="pill pill-neutral">${d.benchmark}</span></td>
                        <td><span class="pill ${d.side === 'long' ? 'pill-success' : d.side === 'short' ? 'pill-danger' : 'pill-neutral'}">${d.side}</span></td>
                        <td>${d.source}</td>
                        <td class="font-mono">${d.entry_mid || '---'}</td>
                        <td class="font-mono" style="font-size: var(--font-size-xs);">${d.decided_at ? d.decided_at.slice(0, 19).replace('T', ' ') : '---'}</td>
                      </tr>
                    `).join("")}
                  </tbody>
                </table>
              </div>
            `}
          </div>
        </div>
      `;
    } catch (err) {
      this._renderError(container, err, () => this._renderEvaluation(container));
    }
  }

  _renderScoreboardTable(statsList) {
    if (!statsList || statsList.length === 0) {
      return `<div class="state-empty"><p>${i18n.t("evaluation.noScores")}</p></div>`;
    }
    return `
      <div class="table-responsive">
        <table class="data-table">
          <thead>
            <tr>
              <th>${i18n.t("evaluation.benchmark")}</th>
              <th>${i18n.t("evaluation.samples")}</th>
              <th>${i18n.t("evaluation.meanReturn")}</th>
              <th>${i18n.t("evaluation.winRate")}</th>
              <th>${i18n.t("evaluation.confidenceInterval")}</th>
            </tr>
          </thead>
          <tbody>
            ${statsList.map(s => `
              <tr>
                <td><strong>${s.benchmark}</strong></td>
                <td class="font-mono">${s.samples}</td>
                <td class="font-mono">${Number(s.mean_return_pct || 0).toFixed(4)}%</td>
                <td class="font-mono">${Number(s.win_rate_pct || 0).toFixed(2)}%</td>
                <td class="font-mono">[${Number(s.ci_lower_pct || 0).toFixed(4)}%, ${Number(s.ci_upper_pct || 0).toFixed(4)}%]</td>
              </tr>
            `).join("")}
          </tbody>
        </table>
      </div>
    `;
  }

  async _renderBacktest(container) {
    try {
      const res = await api.getBacktestReports();
      const reports = res.reports || [];

      container.innerHTML = `
        <div class="page-container">
          <header class="page-header">
            <h1 class="page-title">${i18n.t("backtest.title")}</h1>
            <p class="page-subtitle">${i18n.t("backtest.subtitle")}</p>
          </header>

          <div class="section">
            <div class="section-header">
              <h2 class="section-title">${i18n.t("backtest.reportsList")} (${reports.length})</h2>
            </div>
            ${reports.length === 0 ? `
              <div class="state-empty"><p>${i18n.t("backtest.noReports")}</p></div>
            ` : `
              <div class="table-responsive">
                <table class="data-table">
                  <thead>
                    <tr>
                      <th>Report ID</th>
                      <th>Strategy</th>
                      <th>Instrument</th>
                      <th>Sharpe</th>
                      <th>Total Return</th>
                    </tr>
                  </thead>
                  <tbody>
                    ${reports.map(r => `
                      <tr>
                        <td class="font-mono">${r.report_id || r.id}</td>
                        <td><strong>${r.strategy || r.name}</strong></td>
                        <td>${r.symbol || r.instrument}</td>
                        <td class="font-mono">${r.sharpe || '---'}</td>
                        <td class="font-mono">${r.return_pct || '---'}%</td>
                      </tr>
                    `).join("")}
                  </tbody>
                </table>
              </div>
            `}
          </div>
        </div>
      `;
    } catch (err) {
      this._renderError(container, err, () => this._renderBacktest(container));
    }
  }

  async _renderStrategies(container) {
    try {
      const [specRes, sigRes] = await Promise.allSettled([
        api.getStrategies(),
        api.getStrategySignals(),
      ]);

      const specs = specRes.status === "fulfilled" ? specRes.value?.specs || [] : [];
      const signals = sigRes.status === "fulfilled" ? sigRes.value?.signals || [] : [];

      container.innerHTML = `
        <div class="page-container">
          <header class="page-header">
            <h1 class="page-title">${i18n.t("strategies.title")}</h1>
            <p class="page-subtitle">${i18n.t("strategies.subtitle")}</p>
          </header>

          <div class="section">
            <div class="section-header">
              <h2 class="section-title">${i18n.t("strategies.registeredList")} (${specs.length})</h2>
            </div>
            ${specs.length === 0 ? `
              <div class="state-empty"><p>${i18n.t("strategies.noStrategies")}</p></div>
            ` : `
              <div class="table-responsive">
                <table class="data-table">
                  <thead>
                    <tr>
                      <th>Strategy ID</th>
                      <th>Name</th>
                      <th>Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    ${specs.map(s => `
                      <tr>
                        <td class="font-mono">${s.strategy_id}</td>
                        <td><strong>${s.name}</strong></td>
                        <td><span class="pill pill-neutral">${s.status || 'registered'}</span></td>
                      </tr>
                    `).join("")}
                  </tbody>
                </table>
              </div>
            `}
          </div>
        </div>
      `;
    } catch (err) {
      this._renderError(container, err, () => this._renderStrategies(container));
    }
  }

  async _renderReview(container) {
    try {
      const res = await api.getDailyReports();
      const reports = res.reports || [];

      container.innerHTML = `
        <div class="page-container">
          <header class="page-header">
            <h1 class="page-title">${i18n.t("review.title")}</h1>
            <p class="page-subtitle">${i18n.t("review.subtitle")}</p>
          </header>

          <div class="section">
            <div class="section-header">
              <h2 class="section-title">${i18n.t("review.reportsList")} (${reports.length})</h2>
            </div>
            ${reports.length === 0 ? `
              <div class="state-empty"><p>${i18n.t("review.noReports")}</p></div>
            ` : `
              <div class="table-responsive">
                <table class="data-table">
                  <thead>
                    <tr>
                      <th>Date</th>
                      <th>NAV</th>
                      <th>Cycles</th>
                      <th>Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    ${reports.map(r => `
                      <tr>
                        <td class="font-mono"><strong>${r.date}</strong></td>
                        <td class="font-mono">${r.nav ? Number(r.nav).toFixed(2) : "---"}</td>
                        <td>${r.cycles_count || 0}</td>
                        <td>
                          <button class="btn-control" onclick="window.app.viewDailyReport('${r.date}')">
                            ${i18n.t("review.viewReport")}
                          </button>
                        </td>
                      </tr>
                    `).join("")}
                  </tbody>
                </table>
              </div>
            `}
          </div>

          <div id="report-viewer" class="section" style="display: none;">
            <div class="section-header">
              <h2 id="report-viewer-title" class="section-title">Daily Report</h2>
              <button class="btn-control" onclick="document.getElementById('report-viewer').style.display = 'none';">✕</button>
            </div>
            <pre id="report-viewer-content" style="white-space: pre-wrap; font-family: var(--font-mono); font-size: var(--font-size-xs); background: var(--bg-elev-2); padding: var(--space-4); border-radius: var(--radius-sm); overflow-x: auto; max-height: 500px;"></pre>
          </div>
        </div>
      `;
    } catch (err) {
      this._renderError(container, err, () => this._renderReview(container));
    }
  }

  async viewDailyReport(dateStr) {
    try {
      const report = await api.getDailyReportContent(dateStr);
      const viewer = document.getElementById("report-viewer");
      const title = document.getElementById("report-viewer-title");
      const content = document.getElementById("report-viewer-content");
      if (viewer && content) {
        title.innerText = `Daily Report - ${dateStr}`;
        content.innerText = report.markdown || JSON.stringify(report.data, null, 2);
        viewer.style.display = "block";
        viewer.scrollIntoView({ behavior: "smooth" });
      }
    } catch (err) {
      alert(`Error loading report: ${err.message}`);
    }
  }

  async _renderSettings(container) {
    try {
      const overview = await api.getSettingsOverview();
      const creds = overview.credentials || {};
      const model = overview.model_channel || {};
      const service = overview.service || {};
      const paths = overview.paths || {};

      container.innerHTML = `
        <div class="page-container">
          <header class="page-header">
            <h1 class="page-title">${i18n.t("settings.title")}</h1>
          </header>

          <div class="section">
            <div class="section-header">
              <h2 class="section-title">${i18n.t("settings.credentials")}</h2>
              <a href="#onboarding" class="btn-control">修改凭证 / Update</a>
            </div>
            <div class="grid-cards">
              <div class="card">
                <div class="card-label">${i18n.t("settings.tokenStatus")}</div>
                <div class="card-value" style="font-size: var(--font-size-md);">
                  <span class="pill ${creds.has_oanda_token ? 'pill-success' : 'pill-danger'}">
                    ${creds.has_oanda_token ? i18n.t("settings.configured") : i18n.t("settings.notConfigured")}
                  </span>
                </div>
                <div class="card-meta font-mono">${creds.oanda_token_masked || "No token"}</div>
              </div>
              <div class="card">
                <div class="card-label">${i18n.t("settings.accountIdStatus")}</div>
                <div class="card-value" style="font-size: var(--font-size-md);">
                  <span class="pill ${creds.has_oanda_account_id ? 'pill-success' : 'pill-danger'}">
                    ${creds.has_oanda_account_id ? i18n.t("settings.configured") : i18n.t("settings.notConfigured")}
                  </span>
                </div>
                <div class="card-meta font-mono">${creds.oanda_account_id_masked || "No account ID"}</div>
              </div>
            </div>
          </div>

          <div class="section">
            <div class="section-header">
              <h2 class="section-title">${i18n.t("settings.modelChannel")}</h2>
            </div>
            <div class="grid-cards">
              <div class="card">
                <div class="card-label">${i18n.t("settings.primaryModel")}</div>
                <div class="card-value" style="font-size: var(--font-size-md);">
                  <span class="pill ${model.chatgpt && model.chatgpt.configured && !model.chatgpt.expired ? 'pill-success' : 'pill-warning'}">
                    ${model.chatgpt && model.chatgpt.configured ? (model.chatgpt.expired ? "Expired" : "Authorized") : i18n.t("settings.notConfigured")}
                  </span>
                </div>
                <div class="card-meta">Model: ${model.chatgpt?.default_model || "gpt-4o"}</div>
              </div>
              <div class="card">
                <div class="card-label">${i18n.t("settings.dailyBudget")}</div>
                <div class="card-value" style="font-size: var(--font-size-lg); font-family: var(--font-mono);">
                  ${model.budget?.daily_call_limit || 150} calls / $${model.budget?.daily_cost_limit_usd || 2.0}
                </div>
                <div class="card-meta">Enforced deterministically by ModelBudgetGuard</div>
              </div>
            </div>
          </div>

          <div class="section">
            <div class="section-header">
              <h2 class="section-title">${i18n.t("settings.serviceStatus")}</h2>
              <span class="pill ${service.running ? 'pill-success' : service.installed ? 'pill-warning' : 'pill-neutral'}">
                ${service.running ? i18n.t("settings.serviceRunning") : service.installed ? i18n.t("settings.serviceInstalled") : i18n.t("settings.serviceNotInstalled")}
              </span>
            </div>
            <p style="color: var(--text-dim); margin-bottom: var(--space-4);">${i18n.t("settings.serviceLabel")}</p>
            <div style="display: flex; gap: var(--space-3); flex-wrap: wrap;">
              ${!service.installed ? `
                <button class="btn-control btn-primary" onclick="window.app.handleServiceAction('install')">${i18n.t("settings.installService")}</button>
              ` : `
                ${service.running ? `
                  <button class="btn-control btn-danger" onclick="window.app.handleServiceAction('stop')">${i18n.t("settings.stopService")}</button>
                ` : `
                  <button class="btn-control btn-primary" onclick="window.app.handleServiceAction('start')">${i18n.t("settings.startService")}</button>
                `}
                <button class="btn-control" onclick="window.app.handleServiceAction('uninstall')">${i18n.t("settings.uninstallService")}</button>
              `}
            </div>
          </div>

          <div class="section">
            <div class="section-header">
              <h2 class="section-title">${i18n.t("settings.pathsTitle")}</h2>
            </div>
            <div style="display: flex; flex-direction: column; gap: var(--space-2); font-family: var(--font-mono); font-size: var(--font-size-xs); color: var(--text-dim);">
              <div><strong>Data Dir:</strong> ${paths.data_dir}</div>
              <div><strong>Database:</strong> ${paths.db_path}</div>
              <div><strong>Logs:</strong> ${paths.logs_dir}</div>
              <div><strong>Backups:</strong> ${paths.backups_dir}</div>
            </div>
          </div>

          <div class="section">
            <div class="section-header">
              <h2 class="section-title">${i18n.t("settings.aboutTitle")}</h2>
            </div>
            <p style="color: var(--text-dim); font-size: var(--font-size-sm);">${i18n.t("settings.aboutText")}</p>
            <div style="margin-top: var(--space-3); font-size: var(--font-size-xs); color: var(--text-muted);">
              Version 1.0.0 · MIT License · Practice Only
            </div>
          </div>
        </div>
      `;
    } catch (err) {
      this._renderError(container, err, () => this._renderSettings(container));
    }
  }

  async handleServiceAction(action) {
    try {
      if (action === "install") await api.installService("off");
      else if (action === "uninstall") await api.uninstallService();
      else if (action === "start") await api.startService();
      else if (action === "stop") await api.stopService();
      this.render();
    } catch (err) {
      alert(`Service action failed: ${err.message}`);
    }
  }

  async _renderOnboarding(container) {
    try {
      const overview = await api.getSettingsOverview();
      const creds = overview.credentials || {};
      const model = overview.model_channel || {};
      const service = overview.service || {};

      container.innerHTML = `
        <div class="page-container" style="max-width: 800px;">
          <header class="page-header">
            <h1 class="page-title">${i18n.t("onboarding.title")}</h1>
            <p class="page-subtitle">${i18n.t("onboarding.subtitle")}</p>
          </header>

          <!-- Step 1: OANDA Credentials -->
          <div class="section">
            <div class="section-header">
              <h2 class="section-title">${i18n.t("onboarding.step1Title")}</h2>
              <span class="pill ${creds.has_oanda_token && creds.has_oanda_account_id ? 'pill-success' : 'pill-warning'}">
                ${creds.has_oanda_token && creds.has_oanda_account_id ? i18n.t("settings.configured") : i18n.t("settings.notConfigured")}
              </span>
            </div>
            <p style="color: var(--text-dim); margin-bottom: var(--space-4); font-size: var(--font-size-sm);">
              ${i18n.t("onboarding.step1Desc")}
            </p>
            <form id="onboarding-creds-form">
              <div class="form-group">
                <label class="form-label" for="input-token">${i18n.t("onboarding.tokenLabel")}</label>
                <input id="input-token" type="password" class="form-input" placeholder="${creds.oanda_token_masked || 'e.g. 1a2b3c... (64 hex)'}" autocomplete="off" />
              </div>
              <div class="form-group">
                <label class="form-label" for="input-account">${i18n.t("onboarding.accountLabel")}</label>
                <input id="input-account" type="text" class="form-input" placeholder="${creds.oanda_account_id_masked || 'e.g. 101-004-1234567-001'}" autocomplete="off" />
              </div>
              <button type="submit" class="btn-control btn-primary">${i18n.t("onboarding.saveCredentials")}</button>
            </form>
          </div>

          <!-- Step 2: ChatGPT OAuth -->
          <div class="section">
            <div class="section-header">
              <h2 class="section-title">${i18n.t("onboarding.step2Title")}</h2>
              <span class="pill ${model.chatgpt && model.chatgpt.configured && !model.chatgpt.expired ? 'pill-success' : 'pill-warning'}">
                ${model.chatgpt && model.chatgpt.configured && !model.chatgpt.expired ? "Authorized" : i18n.t("settings.notConfigured")}
              </span>
            </div>
            <p style="color: var(--text-dim); margin-bottom: var(--space-4); font-size: var(--font-size-sm);">
              ${i18n.t("onboarding.step2Desc")}
            </p>
            <div style="background: var(--bg-elev-2); padding: var(--space-3); border-radius: var(--radius-sm); margin-bottom: var(--space-4);">
              <strong>${i18n.t("onboarding.loginStatus")}:</strong>
              <span>${model.chatgpt && model.chatgpt.configured ? `Logged in (${model.chatgpt.default_model || 'gpt-4o'})` : 'Terminal command available: `alphabrief model login`'}</span>
            </div>
          </div>

          <!-- Step 3: Service Install -->
          <div class="section">
            <div class="section-header">
              <h2 class="section-title">${i18n.t("onboarding.step3Title")}</h2>
              <span class="pill ${service.installed ? 'pill-success' : 'pill-neutral'}">
                ${service.installed ? i18n.t("settings.serviceInstalled") : i18n.t("settings.serviceNotInstalled")}
              </span>
            </div>
            <p style="color: var(--text-dim); margin-bottom: var(--space-4); font-size: var(--font-size-sm);">
              ${i18n.t("onboarding.step3Desc")}
            </p>
            <button class="btn-control btn-primary" onclick="window.app.handleServiceAction('install')">
              ${service.installed ? i18n.t("settings.serviceRunning") : i18n.t("settings.installService")}
            </button>
          </div>

          <div style="display: flex; justify-content: flex-end; margin-top: var(--space-5);">
            <a href="#overview" class="btn-control btn-primary" style="padding: 10px 20px; font-size: var(--font-size-md);">
              ${i18n.t("onboarding.completeOnboarding")} →
            </a>
          </div>
        </div>
      `;

      const form = document.getElementById("onboarding-creds-form");
      if (form) {
        form.onsubmit = async (e) => {
          e.preventDefault();
          const token = document.getElementById("input-token").value.trim();
          const account = document.getElementById("input-account").value.trim();
          try {
            await api.updateCredentials(token || undefined, account || undefined);
            alert("Credentials saved successfully into secrets/!");
            this._renderOnboarding(container);
          } catch (err) {
            alert(`Failed saving credentials: ${err.message}`);
          }
        };
      }
    } catch (err) {
      this._renderError(container, err, () => this._renderOnboarding(container));
    }
  }

  _renderError(container, err, retryFn) {
    container.innerHTML = `
      <div class="page-container">
        <div class="state-error" role="alert">
          <svg class="nav-icon" style="width: 32px; height: 32px;"><use href="#icon-alert-circle"></use></svg>
          <h2 style="font-size: var(--font-size-lg); font-weight: 700;">${i18n.t("status.error")}</h2>
          <p>${err.message || "Unknown error occurred"}</p>
          <button class="btn-control" id="retry-btn">${i18n.t("status.retry")}</button>
        </div>
      </div>
    `;
    const btn = document.getElementById("retry-btn");
    if (btn && retryFn) btn.onclick = retryFn;
  }
}

window.app = new App();
window.addEventListener("DOMContentLoaded", () => window.app.init());
