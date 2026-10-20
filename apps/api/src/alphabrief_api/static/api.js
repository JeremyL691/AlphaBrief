/**
 * AlphaBrief API client (PROJECT_GUIDE 4.7)
 * Strictly queries 127.0.0.1 backend endpoints.
 * Never generates or falls back to simulated/sample data.
 */

export class ApiClient {
  constructor(baseUrl = "") {
    this.baseUrl = baseUrl;
  }

  async _fetch(endpoint, options = {}) {
    const url = `${this.baseUrl}${endpoint}`;
    try {
      const resp = await fetch(url, {
        ...options,
        headers: {
          "Accept": "application/json",
          "Content-Type": "application/json",
          ...(options.headers || {}),
        },
      });

      if (!resp.ok) {
        let errDetail = `${resp.status} ${resp.statusText}`;
        try {
          const body = await resp.json();
          if (body.detail) {
            errDetail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
          }
        } catch (_) {}
        const err = new Error(errDetail);
        err.status = resp.status;
        err.offline = false;
        throw err;
      }

      return await resp.json();
    } catch (err) {
      if (err.status) throw err;
      // Network fetch error indicates backend offline
      const netErr = new Error("Backend offline or unreachable");
      netErr.offline = true;
      netErr.status = 0;
      throw netErr;
    }
  }

  // Diagnostics
  async getDoctor() {
    return this._fetch("/api/v1/doctor/run");
  }

  // Broker & Account
  async getAccount() {
    return this._fetch("/api/v1/broker/account");
  }

  async getPositions() {
    return this._fetch("/api/v1/broker/positions");
  }

  async getOrders() {
    return this._fetch("/api/v1/broker/orders");
  }

  // AI Trading Cycles
  async getAiStatus() {
    return this._fetch("/api/v1/ai/status");
  }

  async getAiHistory(limit = 20) {
    return this._fetch(`/api/v1/ai/history?limit=${limit}`);
  }

  async getAiCycle(cycleId) {
    return this._fetch(`/api/v1/ai/cycles/${cycleId}`);
  }

  async getAiAttempts(limit = 50) {
    return this._fetch(`/api/v1/ai/attempts?limit=${limit}`);
  }

  // Operational status (soak qualification and model channel budget).
  async getSoakStatus() {
    return this._fetch("/api/v1/soak/status");
  }

  async getModelStatus() {
    return this._fetch("/api/v1/models");
  }

  // Risk Gate & Kill Switch
  async getRiskStatus() {
    // The risk router exposes kill-switch, context and dashboard only; a
    // bare risk status path does not exist. The dashboard carries the live
    // switch state and the reviewed limits the Risk page renders.
    return this._fetch("/api/v1/risk/dashboard");
  }

  async getRiskContext() {
    return this._fetch("/api/v1/risk/context");
  }

  async getKillSwitch() {
    return this._fetch("/api/v1/risk/kill-switch");
  }

  async setKillSwitch(active, reason = "Dashboard manual operator control") {
    return this._fetch("/api/v1/risk/kill-switch", {
      method: "POST",
      body: JSON.stringify({
        active,
        confirmed: true,
        reason,
      }),
    });
  }

  async getFreezes() {
    return this._fetch("/api/v1/scheduler/freezes");
  }

  // News & Macro
  async getHeadlines(limit = 30) {
    return this._fetch(`/api/v1/news/headlines?limit=${limit}`);
  }

  async getMacroIndicators() {
    return this._fetch("/api/v1/macro/indicators");
  }

  // Evaluation
  async getScoreboard() {
    return this._fetch("/api/v1/evaluation/scoreboard");
  }

  async getShadowDecisions(limit = 50) {
    return this._fetch(`/api/v1/evaluation/decisions?limit=${limit}`);
  }

  // Backtest & Strategies
  async getBacktestReports() {
    return this._fetch("/api/v1/backtest/reports");
  }

  async getStrategies() {
    return this._fetch("/api/v1/strategies/specs");
  }

  async getStrategySignals() {
    return this._fetch("/api/v1/strategies/signals");
  }

  // Review & Reports
  async getDailyReports() {
    return this._fetch("/api/v1/review/reports");
  }

  async getDailyReportContent(dateStr) {
    return this._fetch(`/api/v1/review/reports/${dateStr}`);
  }

  // Settings & Onboarding
  async getSettingsOverview() {
    return this._fetch("/api/v1/settings/overview");
  }

  async updateCredentials(oandaToken, oandaAccountId) {
    const payload = {};
    if (oandaToken !== undefined) payload.oanda_token = oandaToken;
    if (oandaAccountId !== undefined) payload.oanda_account_id = oandaAccountId;
    return this._fetch("/api/v1/settings/credentials", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  }

  async installService(tradingMode = "off") {
    return this._fetch(`/api/v1/settings/service/install?trading_mode=${tradingMode}`, {
      method: "POST",
    });
  }

  async uninstallService() {
    return this._fetch("/api/v1/settings/service/uninstall", {
      method: "POST",
    });
  }

  async startService() {
    return this._fetch("/api/v1/settings/service/start", {
      method: "POST",
    });
  }

  async stopService() {
    return this._fetch("/api/v1/settings/service/stop", {
      method: "POST",
    });
  }
}

export const api = new ApiClient();
