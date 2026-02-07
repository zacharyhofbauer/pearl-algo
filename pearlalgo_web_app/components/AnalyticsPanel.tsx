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
  const [calMonth, setCalMonth] = useState(() => {
    const now = new Date()
    return { year: now.getFullYear(), month: now.getMonth() }
  })

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

  // Build calendar data for the selected month
  // Uses server-side calendar_data from analytics (has ALL trades, not just recent 100)
  const calendarData = useMemo(() => {
    const now = new Date()
    const { year, month } = calMonth
    const isCurrentMonth = year === now.getFullYear() && month === now.getMonth()
    const todayDate = isCurrentMonth ? now.getDate() : -1

    // Server-side aggregated P&L by date (from analytics endpoint)
    const serverCal = (analytics as any)?.calendar_data as Array<{ date: string; pnl: number; trades: number }> | undefined
    const pnlByDate: Record<string, { pnl: number; trades: number }> = {}

    if (serverCal && serverCal.length > 0) {
      serverCal.forEach(d => {
        pnlByDate[d.date] = { pnl: d.pnl, trades: d.trades }
      })
    } else {
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
    }

    // Generate every day of the selected month
    const daysInMonth = new Date(year, month + 1, 0).getDate()
    const days: DayPnL[] = []
    for (let d = 1; d <= daysInMonth; d++) {
      const date = new Date(year, month, d)
      const dateKey = `${year}-${String(month + 1).padStart(2, '0')}-${String(d).padStart(2, '0')}`
      const dayOfWeek = date.getDay()
      const isFuture = isCurrentMonth ? d > todayDate : (year > now.getFullYear() || (year === now.getFullYear() && month > now.getMonth()))

      days.push({
        date: dateKey,
        dayOfWeek,
        weekOfMonth: 0,
        pnl: pnlByDate[dateKey]?.pnl || 0,
        trades: pnlByDate[dateKey]?.trades || 0,
        isToday: d === todayDate,
        isFuture,
      })
    }

    return days
  }, [analytics, recentExits, calMonth])

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

    // Month label from calMonth state
    const monthDate = new Date(calMonth.year, calMonth.month, 1)
    const monthLabel = monthDate.toLocaleString('default', { month: 'long', year: 'numeric' })
    const now = new Date()
    const isCurrentMonth = calMonth.year === now.getFullYear() && calMonth.month === now.getMonth()

    // Use equity-based total when available (MFFU current month), else sum from calendar days
    const serverTotalPnL = (analytics as any)?.calendar_total_pnl as number | undefined
    const sumPnL = calendarData.reduce((sum, d) => sum + d.pnl, 0)
    const useEquityTotal = serverTotalPnL != null && isCurrentMonth
    const totalPnL = useEquityTotal ? serverTotalPnL : sumPnL
    const totalTrades = calendarData.reduce((sum, d) => sum + d.trades, 0)
    const profitDays = calendarData.filter(d => d.pnl > 0).length
    const lossDays = calendarData.filter(d => d.pnl < 0).length

    // Scale factor to adjust per-day PnL to match equity total (accounts for fees)
    const pnlScale = (useEquityTotal && sumPnL !== 0) ? serverTotalPnL / sumPnL : 1

    // Build proper month grid (pad start to align with day-of-week)
    const firstDay = calendarData.length > 0 ? calendarData[0] : null
    const startPadding = firstDay ? firstDay.dayOfWeek : 0

    const goToPrevMonth = (e: React.MouseEvent) => {
      e.stopPropagation()
      setCalMonth(prev => {
        const d = new Date(prev.year, prev.month - 1, 1)
        return { year: d.getFullYear(), month: d.getMonth() }
      })
    }
    const goToNextMonth = (e: React.MouseEvent) => {
      e.stopPropagation()
      if (isCurrentMonth) return // can't go to future
      setCalMonth(prev => {
        const d = new Date(prev.year, prev.month + 1, 1)
        return { year: d.getFullYear(), month: d.getMonth() }
      })
    }

    return (
      <div className="axiom-calendar">
        {/* Month header with nav arrows + summary */}
        <div className="axiom-cal-header">
          <div className="axiom-cal-nav">
            <button className="axiom-cal-nav-btn" onClick={goToPrevMonth} aria-label="Previous month">&lt;</button>
            <span className="axiom-cal-month">{monthLabel}</span>
            <button className="axiom-cal-nav-btn" onClick={goToNextMonth} disabled={isCurrentMonth} aria-label="Next month">&gt;</button>
          </div>
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
            const adjustedPnl = day.pnl * pnlScale
            const isProfit = adjustedPnl > 0
            const isLoss = adjustedPnl < 0
            const intensity = hasTrades ? Math.min(Math.abs(adjustedPnl) / (maxCalendarPnL * Math.abs(pnlScale) || 1), 1) : 0
            const alpha = hasTrades ? 0.15 + intensity * 0.55 : 0

            let bgColor = 'transparent'
            if (isProfit) bgColor = `rgba(0, 230, 118, ${alpha})`
            else if (isLoss) bgColor = `rgba(255, 82, 82, ${alpha})`

            return (
              <div
                key={day.date}
                className={`axiom-cal-cell ${day.isToday ? 'axiom-cal-today' : ''} ${day.isFuture ? 'axiom-cal-future' : ''} ${!hasTrades && !day.isFuture ? 'axiom-cal-no-trades' : ''}`}
                style={{ backgroundColor: day.isFuture ? 'transparent' : bgColor }}
                title={day.isFuture ? '' : `${day.date}: ${hasTrades ? `${formatPnL(adjustedPnl)} (${day.trades} trades)` : 'No trades'}`}
              >
                <span className="axiom-cal-date">{dayNum}</span>
                {day.isFuture ? null : hasTrades ? (
                  <span className={`axiom-cal-amount ${isProfit ? 'positive' : 'negative'}`}>
                    {isProfit ? '+' : '-'}${Math.abs(Math.round(adjustedPnl))}
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
