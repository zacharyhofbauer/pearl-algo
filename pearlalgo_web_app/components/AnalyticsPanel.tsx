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
    const dayLabels = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']

    // Calculate total P&L for the period
    const totalPnL = calendarData.reduce((sum, d) => sum + d.pnl, 0)
    const totalTrades = calendarData.reduce((sum, d) => sum + d.trades, 0)
    const profitDays = calendarData.filter(d => d.pnl > 0).length
    const lossDays = calendarData.filter(d => d.pnl < 0).length

    // Build proper month grid (pad start to align with day-of-week)
    const firstDay = calendarData.length > 0 ? calendarData[0] : null
    const startPadding = firstDay ? firstDay.dayOfWeek : 0

    // Get month/year label
    const now = new Date()
    const monthLabel = now.toLocaleString('default', { month: 'long', year: 'numeric' })

    return (
      <div className="axiom-calendar">
        {/* Month header + summary */}
        <div className="axiom-cal-header">
          <span className="axiom-cal-month">{monthLabel}</span>
          <div className="axiom-cal-stats">
            <span className={`axiom-cal-pnl ${totalPnL >= 0 ? 'positive' : 'negative'}`}>
              {totalPnL >= 0 ? '+' : ''}${Math.abs(totalPnL).toFixed(0)}
            </span>
            <span className="axiom-cal-record">
              <span className="positive">{profitDays}W</span>
              <span style={{ opacity: 0.4 }}>/</span>
              <span className="negative">{lossDays}L</span>
            </span>
          </div>
        </div>

        {/* Day-of-week headers */}
        <div className="axiom-cal-grid axiom-cal-day-headers">
          {dayLabels.map((label, idx) => (
            <div key={idx} className="axiom-cal-day-header">{label}</div>
          ))}
        </div>

        {/* Calendar grid */}
        <div className="axiom-cal-grid">
          {/* Empty cells for padding */}
          {Array.from({ length: startPadding }).map((_, i) => (
            <div key={`pad-${i}`} className="axiom-cal-cell axiom-cal-cell-empty" />
          ))}

          {/* Day cells */}
          {calendarData.map((day) => {
            const dayNum = parseInt(day.date.split('-')[2], 10)
            const hasTrades = day.trades > 0
            const isProfit = day.pnl > 0
            const isLoss = day.pnl < 0
            const intensity = hasTrades ? Math.min(Math.abs(day.pnl) / maxCalendarPnL, 1) : 0
            const alpha = hasTrades ? 0.15 + intensity * 0.55 : 0

            let bgColor = 'transparent'
            if (isProfit) bgColor = `rgba(0, 230, 118, ${alpha})`
            else if (isLoss) bgColor = `rgba(255, 82, 82, ${alpha})`

            return (
              <div
                key={day.date}
                className={`axiom-cal-cell ${day.isToday ? 'axiom-cal-today' : ''} ${!hasTrades ? 'axiom-cal-no-trades' : ''}`}
                style={{ backgroundColor: bgColor }}
                title={`${day.date}: ${hasTrades ? `${formatPnL(day.pnl)} (${day.trades} trades)` : 'No trades'}`}
              >
                <span className="axiom-cal-date">{dayNum}</span>
                {hasTrades ? (
                  <span className={`axiom-cal-amount ${isProfit ? 'positive' : 'negative'}`}>
                    {isProfit ? '+' : '-'}${Math.abs(Math.round(day.pnl))}
                  </span>
                ) : (
                  <span className="axiom-cal-amount axiom-cal-dash">-</span>
                )}
              </div>
            )
          })}
        </div>

        {/* Weekly totals */}
        <div className="axiom-cal-footer">
          <span className="axiom-cal-footer-label">{totalTrades} trades</span>
          <span className={`axiom-cal-footer-total ${totalPnL >= 0 ? 'positive' : 'negative'}`}>
            {totalPnL >= 0 ? '+' : ''}${totalPnL.toFixed(2)}
          </span>
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
