export default function ArchiveLoading() {
  return (
    <main className="archive-page" role="status" aria-label="Loading archive">
      <div className="archive-hero">
        <div className="archive-hero-top">
          <div className="archive-skeleton" style={{ width: 200, height: 32 }} />
          <div className="archive-skeleton" style={{ width: 80, height: 20 }} />
        </div>
        <div className="archive-skeleton" style={{ width: 180, height: 48 }} />
        <div className="archive-skeleton" style={{ width: 260, height: 16 }} />
      </div>
      <div className="archive-stats-grid">
        {Array.from({ length: 8 }).map((_, i) => (
          <div key={i} className="archive-stat-card">
            <div className="archive-skeleton" style={{ width: 60, height: 10 }} />
            <div className="archive-skeleton" style={{ width: 80, height: 20 }} />
          </div>
        ))}
      </div>
      <div className="archive-skeleton-chart" />
    </main>
  )
}
