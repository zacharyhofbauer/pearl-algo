'use client'

import { useState, useMemo } from 'react'
import { DataPanel } from './DataPanelsContainer'
import type { AnalyticsData, RecentExit } from '@/stores'

interface AnalyticsPanelProps {
  analytics: AnalyticsData
  recentExits?: RecentExit[]
}

type TabType = 'sessions' | 'hours' | 'duration' | 'calendar'

interface DayPnL {
  date: string
  dayOfWeek: number
  weekOfMonth: number
  pnl: number
  trades: number
  isToday: boolean
  isFuture: boolean
}

export default function AnalyticsPanel({ analytics, recentExits = [] }: AnalyticsPanelProps) {
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

  // Build calendar data from recent exits
  const calendarData = useMemo(() => {
    const today = new Date()
    today.setHours(0, 0, 0, 0)

    // Get last 28 days (4 weeks)
    const days: DayPnL[] = []
    const pnlByDate: Record<string, { pnl: number; trades: number }> = {}

    // Aggregate P&L by date from recent exits
    recentExits.forEach(exit => {
      if (!exit.exit_time) return
      const date = new Date(exit.exit_time)
      const dateKey = date.toISOString().split('T')[0]
      if (!pnlByDate[dateKey]) {
        pnlByDate[dateKey] = { pnl: 0, trades: 0 }
      }
      pnlByDate[dateKey].pnl += exit.pnl
      pnlByDate[dateKey].trades += 1
    })

    // Generate last 28 days
    for (let i = 27; i >= 0; i--) {
      const date = new Date(today)
      date.setDate(date.getDate() - i)
      const dateKey = date.toISOString().split('T')[0]
      const dayOfWeek = date.getDay() // 0 = Sunday
      const weekOfMonth = Math.floor((27 - i) / 7)

      days.push({
        date: dateKey,
        dayOfWeek,
        weekOfMonth,
        pnl: pnlByDate[dateKey]?.pnl || 0,
        trades: pnlByDate[dateKey]?.trades || 0,
        isToday: i === 0,
        isFuture: false,
      })
    }

    return days
  }, [recentExits])

  // Find max absolute P&L for heatmap scaling
  const maxCalendarPnL = useMemo(() => {
    return Math.max(
      ...calendarData.map(d => Math.abs(d.pnl)),
      1
    )
  }, [calendarData])

  // Get heatmap color based on P&L
  const getHeatmapColor = (pnl: number, trades: number) => {
    if (trades === 0) return 'var(--bg-primary)'

    const intensity = Math.min(Math.abs(pnl) / maxCalendarPnL, 1)
    const alpha = 0.2 + intensity * 0.8

    if (pnl > 0) {
      return `rgba(0, 230, 118, ${alpha})`
    } else if (pnl < 0) {
      return `rgba(255, 82, 82, ${alpha})`
    }
    return 'var(--bg-secondary)'
  }

  const formatDateLabel = (dateStr: string) => {
    const date = new Date(dateStr)
    return date.getDate().toString()
  }

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

  const renderCalendarTab = () => {
    const dayLabels = ['S', 'M', 'T', 'W', 'T', 'F', 'S']

    // Calculate total P&L for the period
    const totalPnL = calendarData.reduce((sum, d) => sum + d.pnl, 0)
    const totalTrades = calendarData.reduce((sum, d) => sum + d.trades, 0)
    const profitDays = calendarData.filter(d => d.pnl > 0).length
    const lossDays = calendarData.filter(d => d.pnl < 0).length

    return (
      <div className="analytics-calendar">
        {/* Summary stats */}
        <div className="calendar-summary">
          <div className="calendar-stat">
            <span className="calendar-stat-label">28d P&L</span>
            <span className={`calendar-stat-value ${totalPnL >= 0 ? 'positive' : 'negative'}`}>
              {formatPnL(totalPnL)}
            </span>
          </div>
          <div className="calendar-stat">
            <span className="calendar-stat-label">Days</span>
            <span className="calendar-stat-value">
              <span className="positive">{profitDays}W</span>
              <span className="divider">/</span>
              <span className="negative">{lossDays}L</span>
            </span>
          </div>
          <div className="calendar-stat">
            <span className="calendar-stat-label">Trades</span>
            <span className="calendar-stat-value">{totalTrades}</span>
          </div>
        </div>

        {/* Day labels */}
        <div className="calendar-day-labels">
          {dayLabels.map((label, idx) => (
            <span key={idx} className="calendar-day-label">{label}</span>
          ))}
        </div>

        {/* Heatmap grid */}
        <div className="calendar-heatmap">
          {calendarData.map((day, idx) => (
            <div
              key={day.date}
              className={`calendar-cell ${day.isToday ? 'today' : ''} ${day.trades === 0 ? 'empty' : ''}`}
              style={{ backgroundColor: getHeatmapColor(day.pnl, day.trades) }}
              title={`${day.date}: ${day.trades > 0 ? formatPnL(day.pnl) : 'No trades'} (${day.trades} trades)`}
            >
              <span className="calendar-cell-date">{formatDateLabel(day.date)}</span>
              {day.trades > 0 && (
                <span className={`calendar-cell-pnl ${day.pnl >= 0 ? 'positive' : 'negative'}`}>
                  {day.pnl >= 0 ? '+' : ''}{Math.round(day.pnl)}
                </span>
              )}
            </div>
          ))}
        </div>

        {/* Legend */}
        <div className="calendar-legend">
          <span className="calendar-legend-label">Loss</span>
          <div className="calendar-legend-gradient">
            <div className="calendar-legend-stop loss" />
            <div className="calendar-legend-stop neutral" />
            <div className="calendar-legend-stop profit" />
          </div>
          <span className="calendar-legend-label">Profit</span>
        </div>
      </div>
    )
  }

  const getTabLabel = (tab: TabType): string => {
    switch (tab) {
      case 'sessions': return 'Sessions'
      case 'hours': return 'Hours'
      case 'duration': return 'Duration'
      case 'calendar': return 'Calendar'
    }
  }

  return (
    <DataPanel title="Analytics">
      {/* Tab Navigation */}
      <div className="analytics-tabs">
        {(['sessions', 'hours', 'duration', 'calendar'] as TabType[]).map((tab) => (
          <button
            key={tab}
            className={`analytics-tab ${activeTab === tab ? 'active' : ''}`}
            onClick={() => setActiveTab(tab)}
          >
            {getTabLabel(tab)}
          </button>
        ))}
      </div>

      {/* Tab Content */}
      <div className="analytics-content">
        {activeTab === 'sessions' && renderSessionsTab()}
        {activeTab === 'hours' && renderHoursTab()}
        {activeTab === 'duration' && renderDurationTab()}
        {activeTab === 'calendar' && renderCalendarTab()}
      </div>
    </DataPanel>
  )
}
