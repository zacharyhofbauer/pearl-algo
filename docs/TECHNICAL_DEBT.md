# Technical Debt Register

This document tracks accepted technical debt in the codebase. These are deliberate decisions to use suboptimal patterns for practical reasons.

## Frontend (TypeScript/React)

### Accepted `any` Types

The following `any` types are intentionally used due to typing limitations:

| File | Line | Pattern | Reason |
|------|------|---------|--------|
| `CandlestickChart.tsx` | 393 | `param: any` | lightweight-charts callback type not exported by library |
| `CandlestickChart.tsx` | 543, 568 | `displayMarkers: any[]` | Dynamic marker aggregation with heterogeneous shapes |
| `EquityCurvePanel.tsx` | 15 | `chartRef: any` | Dynamic `require()` import for SSR compatibility |

**Rationale:** Previous attempts to properly type these caused runtime issues. The untyped code is isolated to chart rendering and does not affect business logic or data flow.

**Mitigation:** These patterns are monitored during chart library upgrades. If lightweight-charts exports these types in future versions, they should be adopted.

---

## Review Schedule

This document should be reviewed quarterly or when upgrading major dependencies (especially `lightweight-charts`).

Last reviewed: 2026-02-02
