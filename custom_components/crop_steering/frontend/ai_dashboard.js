/**
 * AI Decision Dashboard for Crop Steering System
 * 
 * Modern React-based dashboard for monitoring AI decision making, ML model performance,
 * and intelligent irrigation controls using Home Assistant's frontend framework.
 */

class AIDecisionDashboard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this.hass = null;
    this._config = null;
    this._updateInterval = null;
    this._decisionHistory = [];
    this._modelMetrics = {};
    this._realTimeData = {};
  }

  setConfig(config) {
    this._config = {
      title: 'AI Crop Steering Dashboard',
      refresh_interval: 30,
      zones: [1, 2, 3, 4],
      show_model_performance: true,
      show_decision_confidence: true,
      show_learning_metrics: true,
      ...config
    };
    this._render();
  }

  set hass(hass) {
    if (!hass) return;
    
    this._hass = hass;
    this._updateData();
    
    // Set up real-time updates
    if (this._updateInterval) {
      clearInterval(this._updateInterval);
    }
    this._updateInterval = setInterval(() => {
      this._updateData();
    }, this._config.refresh_interval * 1000);
  }

  _updateData() {
    if (!this._hass) return;

    // Gather AI decision data from Home Assistant entities
    this._gatherDecisionHistory();
    this._gatherModelMetrics();
    this._gatherRealTimeData();
    this._render();
  }

  _gatherDecisionHistory() {
    // Extract recent AI decisions from sensor data
    const decisions = [];
    const zones = this._config.zones;
    
    zones.forEach(zoneId => {
      const lastDecision = this._hass.states[`sensor.crop_steering_zone_${zoneId}_last_ai_decision`];
      const decisionConfidence = this._hass.states[`sensor.crop_steering_zone_${zoneId}_ai_confidence`];
      const decisionSource = this._hass.states[`sensor.crop_steering_zone_${zoneId}_decision_source`];
      
      if (lastDecision && decisionConfidence) {
        decisions.push({
          zoneId,
          timestamp: new Date(lastDecision.last_updated),
          decision: lastDecision.state,
          confidence: parseFloat(decisionConfidence.state),
          source: decisionSource?.state || 'unknown',
          reasoning: lastDecision.attributes?.reasoning || ''
        });
      }
    });
    
    this._decisionHistory = decisions.sort((a, b) => b.timestamp - a.timestamp).slice(0, 20);
  }

  _gatherModelMetrics() {
    // Gather ML model performance metrics
    this._modelMetrics = {
      accuracy_7d: this._getEntityState('sensor.crop_steering_ml_accuracy_7d', 0),
      accuracy_30d: this._getEntityState('sensor.crop_steering_ml_accuracy_30d', 0),
      decision_count_today: this._getEntityState('sensor.crop_steering_ai_decisions_today', 0),
      rule_fallback_rate: this._getEntityState('sensor.crop_steering_rule_fallback_rate', 0),
      learning_velocity: this._getEntityState('sensor.crop_steering_learning_velocity', 0),
      pattern_library_size: this._getEntityState('sensor.crop_steering_pattern_count', 0),
      avg_confidence: this._getEntityState('sensor.crop_steering_avg_confidence', 0),
      cost_today: this._getEntityState('sensor.crop_steering_ai_cost_today', 0)
    };
  }

  _gatherRealTimeData() {
    // Gather real-time system data for each zone
    this._realTimeData = {};
    
    this._config.zones.forEach(zoneId => {
      this._realTimeData[zoneId] = {
        vwc: this._getEntityState(`sensor.crop_steering_zone_${zoneId}_vwc_average`, 0),
        ec: this._getEntityState(`sensor.crop_steering_zone_${zoneId}_ec_average`, 0),
        phase: this._getEntityState(`sensor.crop_steering_zone_${zoneId}_current_phase`, 'Unknown'),
        next_action: this._getEntityState(`sensor.crop_steering_zone_${zoneId}_next_action`, 'None'),
        stress_level: this._getEntityState(`sensor.crop_steering_zone_${zoneId}_stress_level`, 0),
        uptake_rate: this._getEntityState(`sensor.crop_steering_zone_${zoneId}_uptake_rate`, 0)
      };
    });
  }

  _getEntityState(entityId, defaultValue) {
    const entity = this._hass.states[entityId];
    if (!entity) return defaultValue;
    
    const value = parseFloat(entity.state);
    return isNaN(value) ? entity.state : value;
  }

  _render() {
    if (!this._config) return;

    this.shadowRoot.innerHTML = `
      <style>
        ${this._getStyles()}
      </style>
      <div class="ai-dashboard">
        <div class="dashboard-header">
          <h2 class="dashboard-title">
            <ha-icon icon="mdi:brain"></ha-icon>
            ${this._config.title}
          </h2>
          <div class="dashboard-status">
            <div class="status-indicator ${this._getSystemStatus()}">
              <span class="status-dot"></span>
              <span class="status-text">${this._getSystemStatusText()}</span>
            </div>
          </div>
        </div>

        <div class="dashboard-grid">
          ${this._renderModelPerformanceCard()}
          ${this._renderDecisionConfidenceCard()}
          ${this._renderZoneOverviewCard()}
          ${this._renderRecentDecisionsCard()}
          ${this._renderLearningMetricsCard()}
          ${this._renderCostTrackingCard()}
        </div>

        <div class="decision-controls">
          ${this._renderAIControls()}
        </div>
      </div>
    `;

    this._attachEventListeners();
  }

  _renderModelPerformanceCard() {
    if (!this._config.show_model_performance) return '';

    const accuracy7d = (this._modelMetrics.accuracy_7d * 100).toFixed(1);
    const accuracy30d = (this._modelMetrics.accuracy_30d * 100).toFixed(1);
    const trendIcon = this._modelMetrics.accuracy_7d >= this._modelMetrics.accuracy_30d ? 'trending-up' : 'trending-down';
    const trendClass = this._modelMetrics.accuracy_7d >= this._modelMetrics.accuracy_30d ? 'positive' : 'negative';

    return `
      <div class="dashboard-card model-performance">
        <div class="card-header">
          <ha-icon icon="mdi:chart-line"></ha-icon>
          <span>Model Performance</span>
        </div>
        <div class="card-content">
          <div class="metric-grid">
            <div class="metric">
              <span class="metric-value">${accuracy7d}%</span>
              <span class="metric-label">7-Day Accuracy</span>
            </div>
            <div class="metric">
              <span class="metric-value">${accuracy30d}%</span>
              <span class="metric-label">30-Day Accuracy</span>
            </div>
            <div class="metric">
              <span class="metric-value ${trendClass}">
                <ha-icon icon="mdi:${trendIcon}"></ha-icon>
                ${(Math.abs(this._modelMetrics.accuracy_7d - this._modelMetrics.accuracy_30d) * 100).toFixed(1)}%
              </span>
              <span class="metric-label">Trend</span>
            </div>
          </div>
          
          <div class="performance-details">
            <div class="detail-item">
              <span>Decisions Today:</span>
              <span>${this._modelMetrics.decision_count_today}</span>
            </div>
            <div class="detail-item">
              <span>Rule Fallback Rate:</span>
              <span>${(this._modelMetrics.rule_fallback_rate * 100).toFixed(1)}%</span>
            </div>
            <div class="detail-item">
              <span>Pattern Library:</span>
              <span>${this._modelMetrics.pattern_library_size} patterns</span>
            </div>
          </div>
        </div>
      </div>
    `;
  }

  _renderDecisionConfidenceCard() {
    if (!this._config.show_decision_confidence) return '';

    const avgConfidence = (this._modelMetrics.avg_confidence * 100).toFixed(1);
    const confidenceLevel = this._getConfidenceLevel(this._modelMetrics.avg_confidence);

    return `
      <div class="dashboard-card decision-confidence">
        <div class="card-header">
          <ha-icon icon="mdi:brain"></ha-icon>
          <span>Decision Confidence</span>
        </div>
        <div class="card-content">
          <div class="confidence-gauge">
            <div class="gauge-container">
              <svg class="gauge-svg" viewBox="0 0 200 120">
                <path class="gauge-background" d="M 20 100 A 80 80 0 0 1 180 100"></path>
                <path class="gauge-fill ${confidenceLevel}" d="M 20 100 A 80 80 0 0 1 180 100" 
                      stroke-dasharray="${this._calculateGaugeFill(this._modelMetrics.avg_confidence)} 251.3"
                      stroke-dashoffset="0"></path>
              </svg>
              <div class="gauge-value">${avgConfidence}%</div>
              <div class="gauge-label">Avg Confidence</div>
            </div>
          </div>
          
          <div class="confidence-distribution">
            ${this._renderConfidenceDistribution()}
          </div>
        </div>
      </div>
    `;
  }

  _renderZoneOverviewCard() {
    return `
      <div class="dashboard-card zone-overview">
        <div class="card-header">
          <ha-icon icon="mdi:view-grid"></ha-icon>
          <span>Zone Status</span>
        </div>
        <div class="card-content">
          <div class="zone-grid">
            ${this._config.zones.map(zoneId => this._renderZoneStatus(zoneId)).join('')}
          </div>
        </div>
      </div>
    `;
  }

  _renderZoneStatus(zoneId) {
    const data = this._realTimeData[zoneId] || {};
    const statusClass = this._getZoneStatusClass(data);
    const vwcPercentage = ((data.vwc / 70) * 100).toFixed(0); // Assuming 70% is target

    return `
      <div class="zone-status ${statusClass}">
        <div class="zone-header">
          <span class="zone-title">Zone ${zoneId}</span>
          <span class="zone-phase">${data.phase}</span>
        </div>
        
        <div class="zone-metrics">
          <div class="zone-metric">
            <div class="metric-bar">
              <div class="metric-fill" style="width: ${vwcPercentage}%"></div>
            </div>
            <span class="metric-text">VWC: ${data.vwc.toFixed(1)}%</span>
          </div>
          
          <div class="zone-metric">
            <span class="metric-text">EC: ${data.ec.toFixed(2)}</span>
          </div>
          
          <div class="zone-metric">
            <span class="metric-text">Stress: ${data.stress_level}/10</span>
          </div>
        </div>
        
        <div class="zone-next-action">
          <ha-icon icon="mdi:clock-outline"></ha-icon>
          <span>${data.next_action}</span>
        </div>
      </div>
    `;
  }

  _renderRecentDecisionsCard() {
    return `
      <div class="dashboard-card recent-decisions">
        <div class="card-header">
          <ha-icon icon="mdi:history"></ha-icon>
          <span>Recent AI Decisions</span>
        </div>
        <div class="card-content">
          <div class="decisions-list">
            ${this._decisionHistory.slice(0, 8).map(decision => this._renderDecisionItem(decision)).join('')}
          </div>
        </div>
      </div>
    `;
  }

  _renderDecisionItem(decision) {
    const timeAgo = this._getTimeAgo(decision.timestamp);
    const confidenceClass = this._getConfidenceClass(decision.confidence);
    const sourceIcon = this._getSourceIcon(decision.source);

    return `
      <div class="decision-item">
        <div class="decision-header">
          <div class="decision-info">
            <ha-icon icon="${sourceIcon}"></ha-icon>
            <span class="zone-label">Zone ${decision.zoneId}</span>
            <span class="decision-action ${decision.decision}">${decision.decision}</span>
          </div>
          <div class="decision-meta">
            <span class="confidence-badge ${confidenceClass}">${(decision.confidence * 100).toFixed(0)}%</span>
            <span class="time-ago">${timeAgo}</span>
          </div>
        </div>
        <div class="decision-reasoning">${decision.reasoning.substring(0, 100)}...</div>
      </div>
    `;
  }

  _renderLearningMetricsCard() {
    if (!this._config.show_learning_metrics) return '';

    return `
      <div class="dashboard-card learning-metrics">
        <div class="card-header">
          <ha-icon icon="mdi:school"></ha-icon>
          <span>Learning Progress</span>
        </div>
        <div class="card-content">
          <div class="learning-stats">
            <div class="learning-stat">
              <ha-icon icon="mdi:speedometer"></ha-icon>
              <div class="stat-content">
                <span class="stat-value">${this._modelMetrics.learning_velocity.toFixed(2)}</span>
                <span class="stat-label">Learning Velocity</span>
              </div>
            </div>
            
            <div class="learning-stat">
              <ha-icon icon="mdi:library"></ha-icon>
              <div class="stat-content">
                <span class="stat-value">${this._modelMetrics.pattern_library_size}</span>
                <span class="stat-label">Learned Patterns</span>
              </div>
            </div>
            
            <div class="learning-progress-bar">
              <div class="progress-label">Knowledge Accumulation</div>
              <div class="progress-track">
                <div class="progress-fill" style="width: ${Math.min(100, this._modelMetrics.pattern_library_size / 50 * 100)}%"></div>
              </div>
              <div class="progress-text">${this._modelMetrics.pattern_library_size}/50 patterns</div>
            </div>
          </div>
        </div>
      </div>
    `;
  }

  _renderCostTrackingCard() {
    return `
      <div class="dashboard-card cost-tracking">
        <div class="card-header">
          <ha-icon icon="mdi:currency-usd"></ha-icon>
          <span>AI Cost Tracking</span>
        </div>
        <div class="card-content">
          <div class="cost-metrics">
            <div class="cost-metric">
              <span class="cost-value">$${this._modelMetrics.cost_today.toFixed(2)}</span>
              <span class="cost-label">Today</span>
            </div>
            
            <div class="cost-efficiency">
              <span class="efficiency-text">Cost per Decision:</span>
              <span class="efficiency-value">
                $${this._modelMetrics.decision_count_today > 0 
                  ? (this._modelMetrics.cost_today / this._modelMetrics.decision_count_today).toFixed(3)
                  : '0.000'}
              </span>
            </div>
          </div>
        </div>
      </div>
    `;
  }

  _renderAIControls() {
    return `
      <div class="ai-controls">
        <div class="control-group">
          <h3>AI System Controls</h3>
          <div class="control-buttons">
            <button class="control-btn primary" onclick="this._toggleAIMode()">
              <ha-icon icon="mdi:robot"></ha-icon>
              Toggle AI Mode
            </button>
            <button class="control-btn secondary" onclick="this._retrainModel()">
              <ha-icon icon="mdi:refresh"></ha-icon>
              Retrain Model
            </button>
            <button class="control-btn secondary" onclick="this._exportLearningData()">
              <ha-icon icon="mdi:download"></ha-icon>
              Export Learning Data
            </button>
          </div>
        </div>
        
        <div class="feedback-section">
          <h4>Provide Feedback</h4>
          <div class="feedback-controls">
            <select class="feedback-zone">
              <option value="">Select Zone...</option>
              ${this._config.zones.map(z => `<option value="${z}">Zone ${z}</option>`).join('')}
            </select>
            <select class="feedback-rating">
              <option value="">Rate Decision...</option>
              <option value="excellent">Excellent</option>
              <option value="good">Good</option>
              <option value="acceptable">Acceptable</option>
              <option value="poor">Poor</option>
              <option value="failure">Failure</option>
            </select>
            <button class="control-btn primary" onclick="this._submitFeedback()">
              Submit Feedback
            </button>
          </div>
        </div>
      </div>
    `;
  }

  _getStyles() {
    return `
      .ai-dashboard {
        padding: 24px;
        background: var(--ha-card-background);
        border-radius: var(--ha-card-border-radius);
        font-family: var(--paper-font-body1_-_font-family);
      }

      .dashboard-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 24px;
        padding-bottom: 16px;
        border-bottom: 1px solid var(--divider-color);
      }

      .dashboard-title {
        display: flex;
        align-items: center;
        gap: 8px;
        margin: 0;
        color: var(--primary-text-color);
        font-size: 24px;
        font-weight: 500;
      }

      .dashboard-status {
        display: flex;
        align-items: center;
      }

      .status-indicator {
        display: flex;
        align-items: center;
        gap: 6px;
        padding: 4px 12px;
        border-radius: 16px;
        font-size: 12px;
        font-weight: 500;
      }

      .status-indicator.healthy {
        background: rgba(76, 175, 80, 0.1);
        color: #4CAF50;
      }

      .status-indicator.warning {
        background: rgba(255, 152, 0, 0.1);
        color: #FF9800;
      }

      .status-indicator.error {
        background: rgba(244, 67, 54, 0.1);
        color: #F44336;
      }

      .status-dot {
        width: 8px;
        height: 8px;
        border-radius: 50%;
        background: currentColor;
      }

      .dashboard-grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
        gap: 24px;
        margin-bottom: 24px;
      }

      .dashboard-card {
        background: var(--ha-card-background);
        border: 1px solid var(--divider-color);
        border-radius: var(--ha-card-border-radius);
        padding: 20px;
        box-shadow: var(--ha-card-box-shadow);
      }

      .card-header {
        display: flex;
        align-items: center;
        gap: 8px;
        margin-bottom: 16px;
        font-weight: 500;
        color: var(--primary-text-color);
      }

      .metric-grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(100px, 1fr));
        gap: 16px;
        margin-bottom: 16px;
      }

      .metric {
        text-align: center;
      }

      .metric-value {
        display: block;
        font-size: 24px;
        font-weight: 600;
        color: var(--primary-text-color);
        margin-bottom: 4px;
      }

      .metric-value.positive {
        color: #4CAF50;
      }

      .metric-value.negative {
        color: #F44336;
      }

      .metric-label {
        font-size: 12px;
        color: var(--secondary-text-color);
        text-transform: uppercase;
        letter-spacing: 0.5px;
      }

      .confidence-gauge {
        display: flex;
        justify-content: center;
        margin-bottom: 20px;
      }

      .gauge-container {
        position: relative;
        text-align: center;
      }

      .gauge-svg {
        width: 160px;
        height: 100px;
      }

      .gauge-background {
        fill: none;
        stroke: var(--divider-color);
        stroke-width: 8;
      }

      .gauge-fill {
        fill: none;
        stroke-width: 8;
        stroke-linecap: round;
        transition: stroke-dasharray 0.5s ease;
      }

      .gauge-fill.high {
        stroke: #4CAF50;
      }

      .gauge-fill.medium {
        stroke: #FF9800;
      }

      .gauge-fill.low {
        stroke: #F44336;
      }

      .gauge-value {
        position: absolute;
        top: 40px;
        left: 50%;
        transform: translateX(-50%);
        font-size: 24px;
        font-weight: 600;
        color: var(--primary-text-color);
      }

      .gauge-label {
        position: absolute;
        top: 65px;
        left: 50%;
        transform: translateX(-50%);
        font-size: 12px;
        color: var(--secondary-text-color);
      }

      .zone-grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
        gap: 16px;
      }

      .zone-status {
        padding: 16px;
        border-radius: 8px;
        border: 1px solid var(--divider-color);
        background: var(--secondary-background-color);
      }

      .zone-status.healthy {
        border-color: #4CAF50;
        background: rgba(76, 175, 80, 0.05);
      }

      .zone-status.warning {
        border-color: #FF9800;
        background: rgba(255, 152, 0, 0.05);
      }

      .zone-status.critical {
        border-color: #F44336;
        background: rgba(244, 67, 54, 0.05);
      }

      .zone-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 12px;
      }

      .zone-title {
        font-weight: 600;
        color: var(--primary-text-color);
      }

      .zone-phase {
        font-size: 12px;
        padding: 2px 8px;
        background: var(--primary-color);
        color: white;
        border-radius: 12px;
      }

      .zone-metrics {
        margin-bottom: 12px;
      }

      .zone-metric {
        display: flex;
        align-items: center;
        justify-content: space-between;
        margin-bottom: 6px;
      }

      .metric-bar {
        width: 60px;
        height: 4px;
        background: var(--divider-color);
        border-radius: 2px;
        overflow: hidden;
      }

      .metric-fill {
        height: 100%;
        background: var(--primary-color);
        transition: width 0.3s ease;
      }

      .metric-text {
        font-size: 12px;
        color: var(--secondary-text-color);
      }

      .zone-next-action {
        display: flex;
        align-items: center;
        gap: 4px;
        font-size: 12px;
        color: var(--secondary-text-color);
      }

      .decisions-list {
        max-height: 400px;
        overflow-y: auto;
      }

      .decision-item {
        padding: 12px;
        border-bottom: 1px solid var(--divider-color);
        transition: background-color 0.2s ease;
      }

      .decision-item:hover {
        background: var(--secondary-background-color);
      }

      .decision-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 6px;
      }

      .decision-info {
        display: flex;
        align-items: center;
        gap: 8px;
      }

      .zone-label {
        font-size: 12px;
        color: var(--secondary-text-color);
      }

      .decision-action {
        padding: 2px 8px;
        border-radius: 12px;
        font-size: 11px;
        font-weight: 500;
        text-transform: uppercase;
      }

      .decision-action.irrigate {
        background: rgba(33, 150, 243, 0.1);
        color: #2196F3;
      }

      .decision-action.wait {
        background: rgba(158, 158, 158, 0.1);
        color: #9E9E9E;
      }

      .decision-action.emergency {
        background: rgba(244, 67, 54, 0.1);
        color: #F44336;
      }

      .confidence-badge {
        padding: 2px 6px;
        border-radius: 8px;
        font-size: 11px;
        font-weight: 500;
      }

      .confidence-badge.high {
        background: rgba(76, 175, 80, 0.1);
        color: #4CAF50;
      }

      .confidence-badge.medium {
        background: rgba(255, 152, 0, 0.1);
        color: #FF9800;
      }

      .confidence-badge.low {
        background: rgba(244, 67, 54, 0.1);
        color: #F44336;
      }

      .decision-reasoning {
        font-size: 12px;
        color: var(--secondary-text-color);
        line-height: 1.4;
      }

      .ai-controls {
        background: var(--secondary-background-color);
        border-radius: var(--ha-card-border-radius);
        padding: 20px;
      }

      .control-group h3 {
        margin: 0 0 16px 0;
        color: var(--primary-text-color);
      }

      .control-buttons {
        display: flex;
        gap: 12px;
        flex-wrap: wrap;
      }

      .control-btn {
        display: flex;
        align-items: center;
        gap: 6px;
        padding: 8px 16px;
        border: none;
        border-radius: 8px;
        cursor: pointer;
        font-size: 14px;
        transition: all 0.2s ease;
      }

      .control-btn.primary {
        background: var(--primary-color);
        color: white;
      }

      .control-btn.secondary {
        background: var(--divider-color);
        color: var(--primary-text-color);
      }

      .control-btn:hover {
        transform: translateY(-1px);
        box-shadow: 0 2px 8px rgba(0,0,0,0.1);
      }

      .feedback-section {
        margin-top: 20px;
        padding-top: 20px;
        border-top: 1px solid var(--divider-color);
      }

      .feedback-controls {
        display: flex;
        gap: 12px;
        align-items: center;
        flex-wrap: wrap;
      }

      .feedback-zone, .feedback-rating {
        padding: 6px 12px;
        border: 1px solid var(--divider-color);
        border-radius: 6px;
        background: var(--ha-card-background);
        color: var(--primary-text-color);
      }

      @media (max-width: 768px) {
        .ai-dashboard {
          padding: 16px;
        }

        .dashboard-grid {
          grid-template-columns: 1fr;
        }

        .control-buttons {
          flex-direction: column;
        }

        .feedback-controls {
          flex-direction: column;
          align-items: stretch;
        }
      }
    `;
  }

  _getSystemStatus() {
    const avgAccuracy = this._modelMetrics.accuracy_7d;
    const ruleFallbackRate = this._modelMetrics.rule_fallback_rate;
    
    if (avgAccuracy >= 0.8 && ruleFallbackRate <= 0.2) {
      return 'healthy';
    } else if (avgAccuracy >= 0.6 && ruleFallbackRate <= 0.4) {
      return 'warning';
    } else {
      return 'error';
    }
  }

  _getSystemStatusText() {
    const status = this._getSystemStatus();
    return status === 'healthy' ? 'AI Optimal' : 
           status === 'warning' ? 'AI Learning' : 'AI Degraded';
  }

  _getConfidenceLevel(confidence) {
    return confidence >= 0.8 ? 'high' : confidence >= 0.6 ? 'medium' : 'low';
  }

  _getConfidenceClass(confidence) {
    return confidence >= 0.8 ? 'high' : confidence >= 0.6 ? 'medium' : 'low';
  }

  _calculateGaugeFill(confidence) {
    return (confidence * 251.3).toFixed(1);
  }

  _getZoneStatusClass(data) {
    if (data.stress_level >= 7) return 'critical';
    if (data.stress_level >= 4) return 'warning';
    return 'healthy';
  }

  _getSourceIcon(source) {
    switch (source) {
      case 'llm_engine': return 'mdi:brain';
      case 'rule_based': return 'mdi:cog';
      case 'hybrid': return 'mdi:brain-cog';
      case 'human_override': return 'mdi:account';
      case 'safety_override': return 'mdi:shield-alert';
      default: return 'mdi:help';
    }
  }

  _getTimeAgo(timestamp) {
    const now = new Date();
    const diff = now - timestamp;
    const minutes = Math.floor(diff / 60000);
    const hours = Math.floor(minutes / 60);
    
    if (minutes < 1) return 'Just now';
    if (minutes < 60) return `${minutes}m ago`;
    if (hours < 24) return `${hours}h ago`;
    return timestamp.toLocaleDateString();
  }

  _attachEventListeners() {
    // Add event listeners for interactive controls
    const dashboard = this.shadowRoot.querySelector('.ai-dashboard');
    
    // Zone click events for detailed view
    dashboard.addEventListener('click', (e) => {
      if (e.target.closest('.zone-status')) {
        const zoneStatus = e.target.closest('.zone-status');
        this._showZoneDetails(zoneStatus);
      }
    });
  }

  _showZoneDetails(zoneElement) {
    // Implementation for showing detailed zone information
    // This would integrate with Home Assistant's dialog system
    console.log('Show zone details:', zoneElement);
  }

  disconnectedCallback() {
    if (this._updateInterval) {
      clearInterval(this._updateInterval);
    }
  }

  getCardSize() {
    return 12; // Height in grid rows
  }

  static get properties() {
    return {
      hass: {},
      config: {}
    };
  }
}

customElements.define('ai-decision-dashboard', AIDecisionDashboard);

// Register the card with Home Assistant
window.customCards = window.customCards || [];
window.customCards.push({
  type: 'ai-decision-dashboard',
  name: 'AI Decision Dashboard',
  description: 'Monitor AI decision making and learning progress for crop steering system',
  preview: true
});

console.info(
  '%c AI-DECISION-DASHBOARD %c v1.0.0 ',
  'color: orange; font-weight: bold; background: black',
  'color: white; font-weight: bold; background: dimgray'
);