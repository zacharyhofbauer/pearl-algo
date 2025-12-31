/**
 * PearlAlgo Terminal - Decision Room Mini App
 * 
 * Bloomberg-inspired trading terminal inside Telegram
 */

// ---------------------------------------------------------------------------
// Initialization
// ---------------------------------------------------------------------------

// Telegram WebApp instance
const tg = window.Telegram?.WebApp;

// State
let currentSignalId = null;
let chart = null;
let candlestickSeries = null;
let volumeSeries = null;
let signalsCache = [];

// Initialize on DOM ready
document.addEventListener('DOMContentLoaded', () => {
    initTelegram();
    initTabs();
    initSignalSelector();
    loadStatus();
    loadSignals().then(() => {
        // Check for signal_id in URL params (from Decision Room button)
        const urlParams = new URLSearchParams(window.location.search);
        const signalId = urlParams.get('signal');
        if (signalId) {
            // Auto-select the signal and load Decision Room
            setTimeout(() => {
                selectSignal(signalId);
            }, 500);  // Small delay to ensure signals are loaded
        }
    });
    
    // Refresh data periodically
    setInterval(loadStatus, 30000);  // Every 30 seconds
});

// ---------------------------------------------------------------------------
// Telegram Integration
// ---------------------------------------------------------------------------

function initTelegram() {
    if (tg) {
        // Tell Telegram we're ready
        tg.ready();
        
        // Expand to full height
        tg.expand();
        
        // Enable closing confirmation if needed
        // tg.enableClosingConfirmation();
        
        // Set header color to match theme
        tg.setHeaderColor(tg.themeParams.bg_color || '#0e1013');
        
        // Handle back button
        tg.BackButton.onClick(() => {
            if (currentSignalId) {
                currentSignalId = null;
                document.getElementById('signal-select').value = '';
                clearDecisionRoom();
            } else {
                tg.close();
            }
        });
        
        console.log('Telegram WebApp initialized:', tg.initData ? 'with initData' : 'no initData');
    } else {
        console.warn('Not running in Telegram WebApp');
    }
}

function getInitData() {
    return tg?.initData || '';
}

// ---------------------------------------------------------------------------
// API Calls
// ---------------------------------------------------------------------------

async function apiCall(endpoint, options = {}) {
    const headers = {
        'Content-Type': 'application/json',
        'X-Telegram-Init-Data': getInitData(),
    };
    
    try {
        const response = await fetch(endpoint, {
            ...options,
            headers: { ...headers, ...options.headers },
        });
        
        if (!response.ok) {
            const error = await response.json().catch(() => ({ detail: response.statusText }));
            throw new Error(error.detail || 'API error');
        }
        
        return await response.json();
    } catch (error) {
        console.error(`API call to ${endpoint} failed:`, error);
        throw error;
    }
}

// ---------------------------------------------------------------------------
// Status
// ---------------------------------------------------------------------------

async function loadStatus() {
    try {
        const status = await apiCall('/api/status');
        updateHeader(status);
        updateStatusBar(status);
    } catch (error) {
        console.error('Failed to load status:', error);
        document.getElementById('price').textContent = 'Error';
    }
}

function updateHeader(status) {
    // Symbol
    document.getElementById('symbol').textContent = status.symbol || 'MNQ';
    
    // Price
    const priceEl = document.getElementById('price');
    if (status.price) {
        priceEl.textContent = `$${status.price.toLocaleString('en-US', { minimumFractionDigits: 2 })}`;
    } else {
        priceEl.textContent = '--';
    }
    
    // Price change
    const changeEl = document.getElementById('price-change');
    if (status.price_change) {
        changeEl.textContent = status.price_change;
        changeEl.className = 'price-change ' + (status.price_change.startsWith('+') ? 'up' : 'down');
    } else {
        changeEl.textContent = '';
    }
    
    // Data quality badge
    const dataBadge = document.getElementById('data-badge');
    const dq = status.data_quality;
    if (dq.level === 'level1') {
        dataBadge.textContent = 'LIVE';
        dataBadge.className = 'data-badge live';
    } else if (dq.level === 'historical' || dq.level === 'historical_fallback') {
        dataBadge.textContent = dq.is_stale ? `HIST ${dq.age_minutes?.toFixed(0)}m` : 'HIST';
        dataBadge.className = 'data-badge historical';
    } else {
        dataBadge.textContent = dq.level?.toUpperCase() || 'UNKNOWN';
        dataBadge.className = 'data-badge error';
    }
    
    // Gate badge
    const gateBadge = document.getElementById('gate-badge');
    if (status.gates.session_open) {
        gateBadge.textContent = 'SESSION';
        gateBadge.className = 'gate-badge open';
    } else if (status.gates.futures_open) {
        gateBadge.textContent = 'FUTURES';
        gateBadge.className = 'gate-badge open';
    } else {
        gateBadge.textContent = 'CLOSED';
        gateBadge.className = 'gate-badge closed';
    }
}

function updateStatusBar(status) {
    // Agent status
    const agentStatus = document.getElementById('agent-status');
    const agent = status.agent;
    if (agent.running && !agent.paused) {
        agentStatus.innerHTML = `<span class="text-bull">●</span> Agent ${agent.activity_pulse}`;
    } else if (agent.paused) {
        agentStatus.innerHTML = `<span class="text-bear">●</span> Agent paused`;
    } else {
        agentStatus.innerHTML = `<span class="text-muted">●</span> Agent stopped`;
    }
    
    // Last update
    const lastUpdate = document.getElementById('last-update');
    lastUpdate.textContent = new Date().toLocaleTimeString();
}

// ---------------------------------------------------------------------------
// Tabs
// ---------------------------------------------------------------------------

function initTabs() {
    const tabs = document.querySelectorAll('.tab');
    tabs.forEach(tab => {
        tab.addEventListener('click', () => {
            const view = tab.dataset.view;
            switchView(view);
        });
    });
}

function switchView(viewName) {
    // Update tabs
    document.querySelectorAll('.tab').forEach(tab => {
        tab.classList.toggle('active', tab.dataset.view === viewName);
    });
    
    // Update views
    document.querySelectorAll('.view').forEach(view => {
        view.classList.toggle('active', view.id === `view-${viewName}`);
    });
    
    // Load data for view
    if (viewName === 'signals') {
        loadSignals();
    } else if (viewName === 'performance') {
        loadPerformance();
    }
}

// ---------------------------------------------------------------------------
// Signals
// ---------------------------------------------------------------------------

function initSignalSelector() {
    const select = document.getElementById('signal-select');
    select.addEventListener('change', (e) => {
        const signalId = e.target.value;
        if (signalId) {
            loadDecisionRoom(signalId);
        } else {
            clearDecisionRoom();
        }
    });
}

async function loadSignals() {
    try {
        const data = await apiCall('/api/signals?limit=20');
        signalsCache = data.signals;
        
        // Update selector
        updateSignalSelector(data.signals);
        
        // Update signals list view
        updateSignalsList(data.signals);
    } catch (error) {
        console.error('Failed to load signals:', error);
    }
}

function updateSignalSelector(signals) {
    const select = document.getElementById('signal-select');
    const currentValue = select.value;
    
    // Keep first option
    select.innerHTML = '<option value="">Select a signal...</option>';
    
    signals.forEach(sig => {
        const option = document.createElement('option');
        option.value = sig.signal_id;
        const dir = sig.direction === 'LONG' ? '🟢' : '🔴';
        const time = new Date(sig.timestamp).toLocaleString();
        option.textContent = `${dir} ${sig.signal_type} @ $${sig.entry_price.toFixed(2)} - ${time}`;
        select.appendChild(option);
    });
    
    // Restore selection
    if (currentValue) {
        select.value = currentValue;
    }
}

function updateSignalsList(signals) {
    const container = document.getElementById('signals-list');
    
    if (signals.length === 0) {
        container.innerHTML = '<div class="loading">No signals found</div>';
        return;
    }
    
    container.innerHTML = signals.map(sig => {
        const dirClass = sig.direction.toLowerCase();
        const pnlClass = sig.pnl > 0 ? 'profit' : sig.pnl < 0 ? 'loss' : '';
        const pnlText = sig.pnl !== null ? (sig.pnl >= 0 ? '+' : '') + `$${sig.pnl.toFixed(2)}` : '--';
        const time = formatTimeAgo(new Date(sig.timestamp));
        
        return `
            <div class="signal-card" onclick="selectSignal('${sig.signal_id}')">
                <div class="signal-card-header">
                    <span class="signal-direction ${dirClass}">${sig.direction}</span>
                    <span class="signal-type">${sig.signal_type}</span>
                </div>
                <div class="signal-card-body">
                    <span class="signal-price">$${sig.entry_price.toFixed(2)}</span>
                    <span class="signal-pnl ${pnlClass}">${pnlText}</span>
                </div>
                <div class="signal-time">${time} • ${sig.status}</div>
            </div>
        `;
    }).join('');
}

function selectSignal(signalId) {
    document.getElementById('signal-select').value = signalId;
    switchView('decision-room');
    loadDecisionRoom(signalId);
}

// ---------------------------------------------------------------------------
// Decision Room
// ---------------------------------------------------------------------------

async function loadDecisionRoom(signalId) {
    currentSignalId = signalId;
    
    // Show back button in Telegram
    if (tg) {
        tg.BackButton.show();
    }
    
    try {
        const data = await apiCall(`/api/decision-room/${signalId}`);
        renderDecisionRoom(data);
        
        // Load chart data
        const ohlcv = await apiCall(`/api/ohlcv?lookback_hours=12&signal_id=${signalId}`);
        renderChart(ohlcv);
    } catch (error) {
        console.error('Failed to load decision room:', error);
        document.getElementById('setup-content').textContent = 'Failed to load signal';
    }
}

function clearDecisionRoom() {
    currentSignalId = null;
    
    // Hide back button
    if (tg) {
        tg.BackButton.hide();
    }
    
    document.getElementById('setup-content').textContent = 'Select a signal to view details';
    document.getElementById('evidence-content').textContent = '--';
    document.getElementById('risks-content').textContent = '--';
    document.getElementById('ats-content').textContent = '--';
    document.getElementById('ml-content').textContent = '--';
    document.getElementById('notes-list').innerHTML = '';
    
    if (chart) {
        chart.remove();
        chart = null;
    }
}

function renderDecisionRoom(data) {
    // Setup Summary
    const sig = data.signal;
    const setupHtml = `
        <div class="info-row">
            <span class="info-label">Direction</span>
            <span class="info-value ${sig.direction === 'LONG' ? 'bull' : 'bear'}">${sig.direction}</span>
        </div>
        <div class="info-row">
            <span class="info-label">Type</span>
            <span class="info-value">${sig.signal_type}</span>
        </div>
        <div class="info-row">
            <span class="info-label">Entry</span>
            <span class="info-value mono">$${sig.entry_price.toFixed(2)}</span>
        </div>
        <div class="info-row">
            <span class="info-label">Stop Loss</span>
            <span class="info-value mono text-bear">$${sig.stop_loss.toFixed(2)}</span>
        </div>
        <div class="info-row">
            <span class="info-label">Take Profit</span>
            <span class="info-value mono text-bull">$${sig.take_profit.toFixed(2)}</span>
        </div>
        <div class="info-row">
            <span class="info-label">R:R</span>
            <span class="info-value">${sig.risk_reward.toFixed(1)}:1</span>
        </div>
        <div class="info-row">
            <span class="info-label">Status</span>
            <span class="info-value">${sig.status}</span>
        </div>
        ${sig.pnl !== null ? `
        <div class="info-row">
            <span class="info-label">P&L</span>
            <span class="info-value ${sig.pnl >= 0 ? 'bull' : 'bear'}">${sig.pnl >= 0 ? '+' : ''}$${sig.pnl.toFixed(2)}</span>
        </div>
        ` : ''}
    `;
    document.getElementById('setup-content').innerHTML = setupHtml;
    
    // Evidence
    const ev = data.evidence;
    const evidenceHtml = `
        ${ev.mtf_alignment ? `<div class="info-row"><span class="info-label">MTF Alignment</span><span class="info-value">${ev.mtf_alignment}</span></div>` : ''}
        ${ev.regime ? `<div class="info-row"><span class="info-label">Regime</span><span class="info-value">${ev.regime}</span></div>` : ''}
        ${ev.vwap_location ? `<div class="info-row"><span class="info-label">VWAP Position</span><span class="info-value">${ev.vwap_location}</span></div>` : ''}
        ${ev.pressure ? `<div class="info-row"><span class="info-label">Pressure</span><span class="info-value">${ev.pressure}</span></div>` : ''}
        ${Object.keys(ev.additional || {}).length === 0 && !ev.mtf_alignment && !ev.regime && !ev.vwap_location && !ev.pressure ? '<span class="text-muted">No evidence data available</span>' : ''}
    `;
    document.getElementById('evidence-content').innerHTML = evidenceHtml;
    
    // Risks
    const risks = data.risks;
    let risksHtml = '';
    if (risks.invalidation) {
        risksHtml += `<div class="warning-item">⚠️ ${risks.invalidation}</div>`;
    }
    if (risks.warnings && risks.warnings.length > 0) {
        risks.warnings.forEach(w => {
            risksHtml += `<div class="warning-item">⚠️ ${w}</div>`;
        });
    }
    if (!risksHtml) {
        risksHtml = '<span class="text-muted">No specific risks identified</span>';
    }
    document.getElementById('risks-content').innerHTML = risksHtml;
    
    // ATS Constraints
    const ats = data.ats;
    const atsHtml = `
        <div class="info-row">
            <span class="info-label">Armed</span>
            <span class="info-value ${ats.armed ? 'bull' : 'bear'}">${ats.armed ? 'YES' : 'NO'}</span>
        </div>
        <div class="info-row">
            <span class="info-label">Session Allowed</span>
            <span class="info-value ${ats.session_allowed ? 'bull' : 'warning'}">${ats.session_allowed ? 'YES' : 'NO'}</span>
        </div>
        ${ats.max_daily_loss ? `
        <div class="info-row">
            <span class="info-label">Max Daily Loss</span>
            <span class="info-value">$${ats.max_daily_loss.toFixed(0)}</span>
        </div>
        ` : ''}
        ${ats.current_daily_pnl !== null ? `
        <div class="info-row">
            <span class="info-label">Daily P&L</span>
            <span class="info-value ${ats.current_daily_pnl >= 0 ? 'bull' : 'bear'}">$${ats.current_daily_pnl.toFixed(2)}</span>
        </div>
        ` : ''}
    `;
    document.getElementById('ats-content').innerHTML = atsHtml;
    
    // ML View
    const ml = data.ml;
    const confClass = ml.confidence_tier === 'High' ? 'high' : ml.confidence_tier === 'Moderate' ? 'moderate' : 'low';
    const mlHtml = `
        <div class="info-row">
            <span class="info-label">Confidence</span>
            <span class="info-value">${(ml.confidence * 100).toFixed(0)}% (${ml.confidence_tier})</span>
        </div>
        <div class="confidence-bar">
            <div class="confidence-fill ${confClass}" style="width: ${ml.confidence * 100}%"></div>
        </div>
        ${ml.diagnostics ? `<p style="margin-top: 8px; color: var(--text-secondary); font-size: 12px;">${ml.diagnostics}</p>` : ''}
    `;
    document.getElementById('ml-content').innerHTML = mlHtml;
    
    // Notes
    renderNotes(data.notes);
}

function renderNotes(notes) {
    const container = document.getElementById('notes-list');
    
    if (!notes || notes.length === 0) {
        container.innerHTML = '<p class="text-muted">No notes yet</p>';
        return;
    }
    
    container.innerHTML = notes.map(note => {
        // Parse timestamp from note format: [ISO_DATE] note text
        const match = note.match(/^\[(.*?)\]\s*(.*)/);
        const time = match ? new Date(match[1]).toLocaleString() : '';
        const text = match ? match[2] : note;
        
        return `
            <div class="note-item">
                <div class="note-time">${time}</div>
                <div>${text}</div>
            </div>
        `;
    }).join('');
}

async function saveNote() {
    if (!currentSignalId) return;
    
    const textarea = document.getElementById('note-text');
    const note = textarea.value.trim();
    
    if (!note) return;
    
    try {
        await apiCall('/api/notes', {
            method: 'POST',
            body: JSON.stringify({
                signal_id: currentSignalId,
                note: note,
            }),
        });
        
        // Clear input
        textarea.value = '';
        
        // Reload decision room to show new note
        loadDecisionRoom(currentSignalId);
        
        // Haptic feedback
        if (tg) {
            tg.HapticFeedback.notificationOccurred('success');
        }
    } catch (error) {
        console.error('Failed to save note:', error);
        if (tg) {
            tg.HapticFeedback.notificationOccurred('error');
        }
    }
}

// ---------------------------------------------------------------------------
// Chart
// ---------------------------------------------------------------------------

function renderChart(data) {
    const container = document.getElementById('chart');
    
    // Remove existing chart
    if (chart) {
        chart.remove();
        chart = null;
    }
    
    if (!data.bars || data.bars.length === 0) {
        container.innerHTML = '<div class="loading">No chart data available</div>';
        return;
    }
    
    // Create chart
    chart = LightweightCharts.createChart(container, {
        width: container.clientWidth,
        height: 200,
        layout: {
            background: { type: 'solid', color: 'transparent' },
            textColor: '#787b86',
        },
        grid: {
            vertLines: { color: '#1e2127' },
            horzLines: { color: '#1e2127' },
        },
        crosshair: {
            mode: LightweightCharts.CrosshairMode.Magnet,
        },
        rightPriceScale: {
            borderColor: '#2a2e36',
        },
        timeScale: {
            borderColor: '#2a2e36',
            timeVisible: true,
            secondsVisible: false,
        },
    });
    
    // Candlestick series
    candlestickSeries = chart.addCandlestickSeries({
        upColor: '#26a69a',
        downColor: '#ef5350',
        borderDownColor: '#ef5350',
        borderUpColor: '#26a69a',
        wickDownColor: '#ef5350',
        wickUpColor: '#26a69a',
    });
    
    // Convert data
    const candleData = data.bars.map(bar => ({
        time: new Date(bar.timestamp).getTime() / 1000,
        open: bar.open,
        high: bar.high,
        low: bar.low,
        close: bar.close,
    }));
    
    candlestickSeries.setData(candleData);
    
    // Add price lines for entry/stop/TP
    if (data.entry_price) {
        candlestickSeries.createPriceLine({
            price: data.entry_price,
            color: '#2962ff',
            lineWidth: 2,
            lineStyle: LightweightCharts.LineStyle.Solid,
            axisLabelVisible: true,
            title: 'Entry',
        });
    }
    
    if (data.stop_loss) {
        candlestickSeries.createPriceLine({
            price: data.stop_loss,
            color: '#ef5350',
            lineWidth: 1,
            lineStyle: LightweightCharts.LineStyle.Dashed,
            axisLabelVisible: true,
            title: 'Stop',
        });
    }
    
    if (data.take_profit) {
        candlestickSeries.createPriceLine({
            price: data.take_profit,
            color: '#26a69a',
            lineWidth: 1,
            lineStyle: LightweightCharts.LineStyle.Dashed,
            axisLabelVisible: true,
            title: 'TP',
        });
    }
    
    if (data.exit_price) {
        candlestickSeries.createPriceLine({
            price: data.exit_price,
            color: '#9c27b0',
            lineWidth: 2,
            lineStyle: LightweightCharts.LineStyle.Solid,
            axisLabelVisible: true,
            title: 'Exit',
        });
    }
    
    // Volume series
    volumeSeries = chart.addHistogramSeries({
        color: '#26a69a',
        priceFormat: { type: 'volume' },
        priceScaleId: '',
        scaleMargins: { top: 0.85, bottom: 0 },
    });
    
    const volumeData = data.bars.map((bar, i) => ({
        time: new Date(bar.timestamp).getTime() / 1000,
        value: bar.volume,
        color: i > 0 && data.bars[i].close >= data.bars[i].open ? '#26a69a80' : '#ef535080',
    }));
    
    volumeSeries.setData(volumeData);
    
    // Fit content
    chart.timeScale().fitContent();
    
    // Handle resize
    const resizeObserver = new ResizeObserver(() => {
        if (chart) {
            chart.applyOptions({ width: container.clientWidth });
        }
    });
    resizeObserver.observe(container);
}

// ---------------------------------------------------------------------------
// Performance
// ---------------------------------------------------------------------------

async function loadPerformance() {
    try {
        const data = await apiCall('/api/performance');
        renderPerformance(data);
    } catch (error) {
        console.error('Failed to load performance:', error);
        document.getElementById('performance-grid').innerHTML = '<div class="loading">Failed to load performance</div>';
    }
}

function renderPerformance(data) {
    const container = document.getElementById('performance-grid');
    
    const pnlClass = data.total_pnl >= 0 ? 'profit' : 'loss';
    const pnlSign = data.total_pnl >= 0 ? '+' : '';
    
    container.innerHTML = `
        <div class="perf-card">
            <div class="perf-label">Win Rate</div>
            <div class="perf-value">${(data.win_rate * 100).toFixed(0)}%</div>
        </div>
        <div class="perf-card">
            <div class="perf-label">Total P&L</div>
            <div class="perf-value ${pnlClass}">${pnlSign}$${data.total_pnl.toFixed(2)}</div>
        </div>
        <div class="perf-card">
            <div class="perf-label">Wins</div>
            <div class="perf-value text-bull">${data.wins}</div>
        </div>
        <div class="perf-card">
            <div class="perf-label">Losses</div>
            <div class="perf-value text-bear">${data.losses}</div>
        </div>
        <div class="perf-card">
            <div class="perf-label">Total Signals</div>
            <div class="perf-value">${data.total_signals}</div>
        </div>
        <div class="perf-card">
            <div class="perf-label">Avg P&L</div>
            <div class="perf-value ${data.avg_pnl >= 0 ? 'profit' : 'loss'}">${data.avg_pnl >= 0 ? '+' : ''}$${data.avg_pnl.toFixed(2)}</div>
        </div>
        <div class="perf-card full-width">
            <div class="perf-label">Period</div>
            <div class="perf-value" style="font-size: 14px;">${data.period}</div>
        </div>
    `;
}

// ---------------------------------------------------------------------------
// Panel Toggle
// ---------------------------------------------------------------------------

function togglePanel(panelId) {
    const panel = document.getElementById(`panel-${panelId}`);
    panel.classList.toggle('collapsed');
}

// ---------------------------------------------------------------------------
// Utilities
// ---------------------------------------------------------------------------

function formatTimeAgo(date) {
    const now = new Date();
    const diff = (now - date) / 1000;  // seconds
    
    if (diff < 60) return 'just now';
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
    return `${Math.floor(diff / 86400)}d ago`;
}

// Export for HTML onclick handlers
window.togglePanel = togglePanel;
window.selectSignal = selectSignal;
window.saveNote = saveNote;

