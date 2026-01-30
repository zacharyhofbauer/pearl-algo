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
        <span className="help-icon">❓</span>
        <span>Quick Reference</span>
        <span className="help-expand-icon">{isExpanded ? '▲' : '▼'}</span>
      </button>

      {isExpanded && (
        <div className="help-panel-content">
          <div className="help-section">
            <h4>🚀 Main Commands</h4>
            <div className="help-commands">
              <code>./pearl.sh start</code>
              <span>Start all services</span>
              <code>./pearl.sh stop</code>
              <span>Stop all services</span>
              <code>./pearl.sh restart</code>
              <span>Restart everything</span>
              <code>./pearl.sh status</code>
              <span>Show status</span>
              <code>./pearl.sh quick</code>
              <span>Quick status check</span>
            </div>
          </div>

          <div className="help-section">
            <h4>🔧 Individual Services</h4>
            <div className="help-commands">
              <code>./pearl.sh gateway start|stop</code>
              <span>IB Gateway</span>
              <code>./pearl.sh agent start|stop</code>
              <span>Trading Agent</span>
              <code>./pearl.sh telegram start|stop</code>
              <span>Telegram Bot</span>
              <code>./pearl.sh chart start|stop</code>
              <span>Live Chart API</span>
            </div>
          </div>

          <div className="help-section">
            <h4>⚙️ Options</h4>
            <div className="help-commands">
              <code>./pearl.sh start --market ES</code>
              <span>Different market</span>
              <code>./pearl.sh start --no-telegram</code>
              <span>Skip Telegram</span>
              <code>./pearl.sh start --no-chart</code>
              <span>Skip Chart API</span>
              <code>./pearl.sh start --foreground</code>
              <span>Run in foreground</span>
            </div>
          </div>

          <div className="help-section">
            <h4>💻 Terminal Setup</h4>
            <div className="help-commands single">
              <code>cd ~/pearlalgo-dev-ai-agents && source .venv/bin/activate</code>
            </div>
          </div>

          <div className="help-section">
            <h4>🤖 AI Assistants</h4>
            <div className="help-commands">
              <code>agent</code>
              <span>Cursor Agent (CLI)</span>
              <code>claude</code>
              <span>Claude AI (CLI)</span>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
