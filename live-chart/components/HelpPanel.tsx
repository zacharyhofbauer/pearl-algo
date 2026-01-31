'use client'

import { useState } from 'react'

export default function HelpPanel() {
  const [isExpanded, setIsExpanded] = useState(false)

  return (
    <div className="help-panel">
      <button
        className="help-panel-toggle"
        onClick={() => setIsExpanded(!isExpanded)}
      >
        <span className="help-icon">?</span>
        <span>Quick Reference</span>
        <span className="help-expand-icon">{isExpanded ? '▲' : '▼'}</span>
      </button>

      {isExpanded && (
        <div className="help-panel-content">
          <div className="help-section">
            <h4>Main Commands</h4>
            <div className="help-commands">
              <code>./pearl.sh start</code>
              <span>Start all services</span>
              <code>./pearl.sh stop</code>
              <span>Stop all services</span>
              <code>./pearl.sh restart</code>
              <span>Restart everything</span>
              <code>./pearl.sh status</code>
              <span>Full status dashboard</span>
              <code>./pearl.sh quick</code>
              <span>One-liner status</span>
            </div>
          </div>

          <div className="help-section">
            <h4>Individual Services</h4>
            <div className="help-commands">
              <code>./pearl.sh gateway start|stop|status</code>
              <span>IB Gateway</span>
              <code>./pearl.sh agent start|stop|status</code>
              <span>Trading Agent</span>
              <code>./pearl.sh telegram start|stop|status</code>
              <span>Telegram Bot</span>
              <code>./pearl.sh chart start|stop|restart</code>
              <span>Live Chart (this site)</span>
              <code>./pearl.sh tunnel status|logs</code>
              <span>Cloudflare Tunnel</span>
            </div>
          </div>

          <div className="help-section">
            <h4>Troubleshooting</h4>
            <div className="help-commands">
              <code>./pearl.sh quick</code>
              <span>Check all services</span>
              <code>./pearl.sh chart restart</code>
              <span>pearlalgo.io not loading</span>
              <code>./pearl.sh tunnel status</code>
              <span>Check tunnel + public access</span>
              <code>journalctl -u cloudflared-pearlalgo -f</code>
              <span>Tunnel logs</span>
            </div>
          </div>

          <div className="help-section">
            <h4>After Reboot</h4>
            <div className="help-commands single">
              <code>cd ~/pearlalgo-dev-ai-agents && ./pearl.sh start</code>
            </div>
            <p className="help-note">Tunnel auto-starts. Chart/Agent need manual start.</p>
          </div>

          <div className="help-section">
            <h4>Options</h4>
            <div className="help-commands">
              <code>--market ES</code>
              <span>Different market</span>
              <code>--no-telegram</code>
              <span>Skip Telegram</span>
              <code>--no-chart</code>
              <span>Skip Chart</span>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
