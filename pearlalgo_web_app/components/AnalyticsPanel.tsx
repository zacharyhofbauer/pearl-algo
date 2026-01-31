'use client'

import { useState } from 'react'
import { DataPanel } from './DataPanelsContainer'
import type { AnalyticsData } from '@/stores'

interface AnalyticsPanelProps {
  analytics: AnalyticsData
}

type TabType = 'sessions' | 'hours' | 'duration'

export default function AnalyticsPanel({ analytics }: AnalyticsPanelProps) {
  const [activeTab, setActiveTab] = useState<TabType>('sessions')

  const formatPnL = (pnl: number) => {
    const sign = pnl >= 0 ? '+' : ''
    return `${sign}$${pnl.toFixed(2)}`
  }

  // Find max absolute P&L for bar scaling
  const maxSessionPnL = Math.max(
    ...analytics.session_performance.map(s => Math.abs(s.pnl)),
    1 // Prevent division by zero
  )

  const maxDurationPnL = Math.max(
    ...analytics.hold_duration.map(d => Math.abs(d.pnl)),
    1
  )

  const renderSessionsTab = () => (
    <div className="analytics-sessions">
      {analytics.session_performance.map((session) => {
        const barWidth = Math.abs(session.pnl) / maxSessionPnL * 100
        const isPositive = session.pnl >= 0
        const totalTrades = session.wins + session.losses

        return (
          <div key={session.id} className="session-bar-item">
            <div className="session-bar-header">
              <span className="session-bar-name">{session.name}</span>
              <span className={`session-bar-pnl ${isPositive ? 'positive' : 'negative'}`}>
                {formatPnL(session.pnl)}
              </span>
            </div>
            <div className="session-bar-track">
              <div
                className={`session-bar-fill ${isPositive ? 'positive' : 'negative'}`}
                style={{ width: `${barWidth}%` }}
              />
            </div>
            <div className="session-bar-stats">
              <span className="session-bar-trades">
                {totalTrades} trades
              </span>
              <span className="session-bar-winrate">
                {session.win_rate.toFixed(0)}% WR
              </span>
            </div>
          </div>
        )
      })}
    </div>
  )

  const renderHoursTab = () => (
    <div className="analytics-hours">
      {/* Best Hours */}
      <div className="hours-section">
        <div className="hours-section-header positive">Best Hours</div>
        {analytics.best_hours.length > 0 ? (
          <div className="hours-list">
            {analytics.best_hours.map((hour, idx) => (
              <div key={`best-${hour.hour}`} className="hour-item">
                <span className="hour-rank">#{idx + 1}</span>
                <span className="hour-time">{hour.hour_label}</span>
                <span className="hour-pnl positive">{formatPnL(hour.pnl)}</span>
                <span className="hour-stats">
                  {hour.trades} trades, {hour.win_rate.toFixed(0)}% WR
                </span>
              </div>
            ))}
          </div>
        ) : (
          <div className="hours-empty">Need 5+ trades per hour</div>
        )}
      </div>

      {/* Worst Hours */}
      <div className="hours-section">
        <div className="hours-section-header negative">Worst Hours</div>
        {analytics.worst_hours.length > 0 ? (
          <div className="hours-list">
            {analytics.worst_hours.map((hour, idx) => (
              <div key={`worst-${hour.hour}`} className="hour-item">
                <span className="hour-rank">#{idx + 1}</span>
                <span className="hour-time">{hour.hour_label}</span>
                <span className="hour-pnl negative">{formatPnL(hour.pnl)}</span>
                <span className="hour-stats">
                  {hour.trades} trades, {hour.win_rate.toFixed(0)}% WR
                </span>
              </div>
            ))}
          </div>
        ) : (
          <div className="hours-empty">Need 5+ trades per hour</div>
        )}
      </div>
    </div>
  )

  const renderDurationTab = () => (
    <div className="analytics-duration">
      {analytics.hold_duration.map((dur) => {
        const barWidth = Math.abs(dur.pnl) / maxDurationPnL * 100
        const isPositive = dur.pnl >= 0
        const totalTrades = dur.wins + dur.losses

        return (
          <div key={dur.id} className="duration-bar-item">
            <div className="duration-bar-header">
              <span className="duration-bar-name">{dur.name}</span>
              <span className={`duration-bar-pnl ${isPositive ? 'positive' : 'negative'}`}>
                {formatPnL(dur.pnl)}
              </span>
            </div>
            <div className="duration-bar-track">
              <div
                className={`duration-bar-fill ${isPositive ? 'positive' : 'negative'}`}
                style={{ width: `${barWidth}%` }}
              />
            </div>
            <div className="duration-bar-stats">
              <span className="duration-bar-trades">
                {totalTrades} trades ({dur.wins}W / {dur.losses}L)
              </span>
              <span className="duration-bar-winrate">
                {dur.win_rate.toFixed(0)}% WR
              </span>
            </div>
          </div>
        )
      })}
    </div>
  )

  return (
    <DataPanel title="Analytics" icon="📈">
      {/* Tab Navigation */}
      <div className="analytics-tabs">
        {(['sessions', 'hours', 'duration'] as TabType[]).map((tab) => (
          <button
            key={tab}
            className={`analytics-tab ${activeTab === tab ? 'active' : ''}`}
            onClick={() => setActiveTab(tab)}
          >
            {tab === 'sessions' ? 'Sessions' : tab === 'hours' ? 'Hours' : 'Duration'}
          </button>
        ))}
      </div>

      {/* Tab Content */}
      <div className="analytics-content">
        {activeTab === 'sessions' && renderSessionsTab()}
        {activeTab === 'hours' && renderHoursTab()}
        {activeTab === 'duration' && renderDurationTab()}
      </div>
    </DataPanel>
  )
}
