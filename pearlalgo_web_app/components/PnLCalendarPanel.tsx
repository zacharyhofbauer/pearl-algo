'use client'

import { useState, useMemo } from 'react'
import { DataPanel } from './DataPanelsContainer'
import type { RecentExit } from '@/stores'

interface PnLCalendarPanelProps {
  recentExits: RecentExit[]
}

interface DayData {
  date: string
  pnl: number
  trades: number
  wins: number
  losses: number
}

export default function PnLCalendarPanel({ recentExits }: PnLCalendarPanelProps) {
  const [selectedMonth, setSelectedMonth] = useState(() => {
    const now = new Date()
    return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`
  })

  // Aggregate trades by day
  const dailyPnL = useMemo(() => {
    const byDay: Record<string, DayData> = {}

    recentExits.forEach((trade) => {
      if (!trade.exit_time) return
      const date = trade.exit_time.split('T')[0]

      if (!byDay[date]) {
        byDay[date] = { date, pnl: 0, trades: 0, wins: 0, losses: 0 }
      }

      byDay[date].pnl += trade.pnl || 0
      byDay[date].trades += 1
      if ((trade.pnl || 0) >= 0) {
        byDay[date].wins += 1
      } else {
        byDay[date].losses += 1
      }
    })

    return byDay
  }, [recentExits])

  // Generate calendar grid for selected month
  const calendarDays = useMemo(() => {
    const [year, month] = selectedMonth.split('-').map(Number)
    const firstDay = new Date(year, month - 1, 1)
    const lastDay = new Date(year, month, 0)
    const daysInMonth = lastDay.getDate()
    const startDayOfWeek = firstDay.getDay()

    const days: (DayData | null)[] = []

    // Add empty cells for days before the first of the month
    for (let i = 0; i < startDayOfWeek; i++) {
      days.push(null)
    }

    // Add days of the month
    for (let day = 1; day <= daysInMonth; day++) {
      const dateStr = `${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`
      days.push(dailyPnL[dateStr] || { date: dateStr, pnl: 0, trades: 0, wins: 0, losses: 0 })
    }

    return days
  }, [selectedMonth, dailyPnL])

  // Calculate monthly totals
  const monthlyStats = useMemo(() => {
    let totalPnL = 0
    let totalTrades = 0
    let totalWins = 0
    let profitDays = 0
    let lossDays = 0

    calendarDays.forEach((day) => {
      if (day && day.trades > 0) {
        totalPnL += day.pnl
        totalTrades += day.trades
        totalWins += day.wins
        if (day.pnl >= 0) profitDays++
        else lossDays++
      }
    })

    return { totalPnL, totalTrades, totalWins, profitDays, lossDays }
  }, [calendarDays])

  const formatPnL = (pnl: number) => {
    const sign = pnl >= 0 ? '+' : ''
    return `${sign}$${Math.abs(pnl).toFixed(0)}`
  }

  const getPnLClass = (pnl: number, trades: number) => {
    if (trades === 0) return 'calendar-day-empty'
    if (pnl > 100) return 'calendar-day-big-win'
    if (pnl > 0) return 'calendar-day-win'
    if (pnl < -100) return 'calendar-day-big-loss'
    if (pnl < 0) return 'calendar-day-loss'
    return 'calendar-day-neutral'
  }

  const changeMonth = (delta: number) => {
    const [year, month] = selectedMonth.split('-').map(Number)
    const newDate = new Date(year, month - 1 + delta, 1)
    setSelectedMonth(`${newDate.getFullYear()}-${String(newDate.getMonth() + 1).padStart(2, '0')}`)
  }

  const monthName = new Date(selectedMonth + '-01').toLocaleDateString('en-US', {
    month: 'long',
    year: 'numeric'
  })

  return (
    <DataPanel title="P&L Calendar" icon="📅" className="pnl-calendar-panel">
      <div className="pnl-calendar">
        {/* Month Navigation */}
        <div className="calendar-nav">
          <button onClick={() => changeMonth(-1)} className="calendar-nav-btn">◀</button>
          <span className="calendar-month">{monthName}</span>
          <button onClick={() => changeMonth(1)} className="calendar-nav-btn">▶</button>
        </div>

        {/* Monthly Summary */}
        <div className="calendar-summary">
          <div className={`summary-pnl ${monthlyStats.totalPnL >= 0 ? 'positive' : 'negative'}`}>
            {formatPnL(monthlyStats.totalPnL)}
          </div>
          <div className="summary-stats">
            <span className="stat-item">{monthlyStats.totalTrades} trades</span>
            <span className="stat-item win">{monthlyStats.profitDays}W</span>
            <span className="stat-item loss">{monthlyStats.lossDays}L</span>
          </div>
        </div>

        {/* Day Headers */}
        <div className="calendar-header">
          {['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'].map((day) => (
            <div key={day} className="calendar-header-day">{day}</div>
          ))}
        </div>

        {/* Calendar Grid */}
        <div className="calendar-grid">
          {calendarDays.map((day, idx) => (
            <div
              key={idx}
              className={`calendar-day ${day ? getPnLClass(day.pnl, day.trades) : 'calendar-day-outside'}`}
              title={day && day.trades > 0 ? `${day.date}: ${formatPnL(day.pnl)} (${day.trades} trades)` : ''}
            >
              {day && (
                <>
                  <span className="day-number">{parseInt(day.date.split('-')[2])}</span>
                  {day.trades > 0 && (
                    <span className="day-pnl">{formatPnL(day.pnl)}</span>
                  )}
                </>
              )}
            </div>
          ))}
        </div>

        {/* Legend */}
        <div className="calendar-legend">
          <span className="legend-item"><span className="legend-dot big-win"></span>+$100</span>
          <span className="legend-item"><span className="legend-dot win"></span>Profit</span>
          <span className="legend-item"><span className="legend-dot loss"></span>Loss</span>
          <span className="legend-item"><span className="legend-dot big-loss"></span>-$100</span>
        </div>
      </div>
    </DataPanel>
  )
}
