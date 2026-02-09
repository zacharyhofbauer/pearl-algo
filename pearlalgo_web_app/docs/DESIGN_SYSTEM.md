# Pearl Algo Design System

A comprehensive design system for the Pearl Algo Web App, providing consistent styling, reusable components, and design tokens.

## Design Tokens

Design tokens are CSS custom properties defined in `app/globals.css` that provide a single source of truth for design values.

### Typography Scale

```css
--font-size-xs: 10px;   /* Labels, badges, small text */
--font-size-sm: 11px;   /* Secondary text, captions */
--font-size-md: 12px;   /* Body text, default size */
--font-size-lg: 14px;   /* Stat values, emphasized text */
--font-size-xl: 18px;   /* Headers, titles */
--font-size-2xl: 24px;  /* Large numbers, balances */
```

### Spacing Scale (4px base)

```css
--space-1: 2px;   /* Tight spacing */
--space-2: 4px;   /* Compact spacing */
--space-3: 6px;   /* Small gaps */
--space-4: 8px;   /* Standard gaps */
--space-5: 12px;  /* Medium spacing */
--space-6: 16px;  /* Default padding */
--space-7: 24px;  /* Large spacing */
```

### Motion Scale

```css
--duration-fast: 150ms;     /* Hover effects, quick feedback */
--duration-normal: 200ms;   /* Standard transitions */
--duration-slow: 300ms;     /* Deliberate animations */
--duration-slower: 2000ms;  /* Pulse animations */
--ease-default: ease;       /* Default easing */
```

### Color System

#### Core Colors
```css
--bg-primary: #0a0a0f;
--bg-secondary: #12121a;
--bg-card: #1a1a24;
--bg-elevated: #22222e;
--text-primary: #f0eeeb;    /* WCAG AA: ~15:1 on bg-primary */
--text-secondary: #b0b8c8;  /* WCAG AA: ~8.5:1 on bg-primary */
--text-tertiary: #8a92a0;   /* WCAG AA: ~5:1 on bg-card */
--text-muted: #6e7380;      /* WCAG AA: ~4.5:1 on bg-primary */
--accent-cyan: #00d4ff;
--accent-green: #00e676;
--accent-red: #ff5252;
--accent-yellow: #ffc107;
--accent-purple: #ab47bc;
```

#### Semantic Colors - Financial
```css
--color-profit: var(--accent-green);
--color-loss: var(--accent-red);
```

#### Semantic Colors - Status
```css
--color-status-online: var(--accent-green);
--color-status-warning: var(--accent-yellow);
--color-status-offline: var(--accent-red);
```

#### Semantic Colors - Health
```css
--color-health-ok: var(--accent-green);
--color-health-warning: var(--accent-yellow);
--color-health-error: var(--accent-red);
```

#### Direction Colors
```css
--color-long: var(--accent-cyan);
--color-short: #ff6ec7;
```

#### RGB Variants (for rgba() usage)
```css
--accent-green-rgb: 0, 230, 118;
--accent-red-rgb: 255, 82, 82;
--accent-cyan-rgb: 0, 212, 255;
--accent-yellow-rgb: 255, 193, 7;
```

Usage: `rgba(var(--accent-green-rgb), 0.15)`

## UI Primitives

### InfoTooltip

A reusable tooltip component for providing contextual help.

```tsx
import { InfoTooltip } from '@/components/ui'

// Basic usage - shows info icon
<InfoTooltip text="This explains the metric" />

// With custom trigger
<InfoTooltip text="Help text" position="bottom">
  <span>Custom trigger</span>
</InfoTooltip>
```

**Props:**
- `text` (string, required): Tooltip content
- `position` ('top' | 'bottom' | 'left' | 'right'): Tooltip position (default: 'top')
- `children` (ReactNode): Custom trigger element

### StatDisplay

A flexible component for displaying labeled statistics with various styling options.

```tsx
import { StatDisplay } from '@/components/ui'

// Basic usage
<StatDisplay label="Trades" value="42" />

// Financial mode with positive value
<StatDisplay
  label="P&L"
  value="+$125.00"
  colorMode="financial"
  positive
/>

// Status mode
<StatDisplay
  label="System"
  value="Online"
  colorMode="status"
  status="ok"
/>

// With tooltip
<StatDisplay
  label="Expectancy"
  value="$2.50"
  tooltip="Average profit per trade"
/>

// Compact variant
<StatDisplay
  label="Win Rate"
  value="65%"
  variant="compact"
/>
```

**Props:**
- `label` (string, required): Stat label
- `value` (ReactNode, required): Stat value
- `variant` ('default' | 'compact' | 'inline'): Display variant
- `colorMode` ('default' | 'financial' | 'status'): Color mode
- `positive` (boolean): Apply positive styling
- `negative` (boolean): Apply negative styling
- `status` ('ok' | 'warning' | 'error' | 'inactive'): Status for status mode
- `tooltip` (string): Tooltip text
- `subtext` (ReactNode): Additional text below value
- `fullWidth` (boolean): Span full width in grid
- `className` (string): Additional CSS classes

## DataPanel Component

The DataPanel component now supports padding and variant props.

```tsx
import { DataPanel } from '@/components/DataPanelsContainer'

// Basic usage
<DataPanel title="Performance">
  {content}
</DataPanel>

// With padding variant
<DataPanel title="Config" padding="compact">
  {content}
</DataPanel>

// Optional icon (image only)
<DataPanel title="Pearl AI" iconSrc="/pearl-emoji.png">
  {content}
</DataPanel>

// With visual variant
<DataPanel title="Challenge" variant="feature">
  {content}
</DataPanel>
```

**Padding Variants:**
- `none`: No padding
- `compact`: `var(--space-4)` (8px)
- `default`: `var(--space-6)` (16px)
- `spacious`: `var(--space-7)` (24px)

**Visual Variants:**
- `default`: Standard panel styling
- `feature`: Cyan-highlighted border and header
- `status`: Green-tinted border for status panels
- `config`: Yellow-tinted border for configuration

## Grid Utilities

CSS utility classes for grid layouts.

```tsx
<div className="grid grid-cols-2 gap-md">
  <StatDisplay label="A" value="1" />
  <StatDisplay label="B" value="2" />
</div>

<div className="grid grid-cols-3 gap-sm">
  <div>Item 1</div>
  <div>Item 2</div>
  <div className="col-span-full">Full width</div>
</div>
```

**Grid Classes:**
- `.grid` - Enable grid display
- `.grid-cols-2` - 2-column grid
- `.grid-cols-3` - 3-column grid
- `.grid-cols-4` - 4-column grid

**Gap Classes:**
- `.gap-xs` - `var(--space-2)` (4px)
- `.gap-sm` - `var(--space-3)` (6px)
- `.gap-md` - `var(--space-5)` (12px)
- `.gap-lg` - `var(--space-6)` (16px)

**Span Classes:**
- `.col-span-2` - Span 2 columns
- `.col-span-3` - Span 3 columns
- `.col-span-full` - Span all columns

## Migration Guide

### Replacing Inline InfoTooltip

Before:
```tsx
function InfoTooltip({ text }: { text: string }) {
  return (
    <span className="tooltip-wrapper">
      <span className="info-icon">?</span>
      <span className="tooltip-content">{text}</span>
    </span>
  )
}
```

After:
```tsx
import { InfoTooltip } from '@/components/ui'

<InfoTooltip text="Help text" />
```

### Replacing Stat Divs

Before:
```tsx
<div className="stat-item">
  <span className="stat-item-label">P&L</span>
  <span className={`stat-item-value ${pnl >= 0 ? 'positive' : 'negative'}`}>
    {formatPnL(pnl)}
  </span>
</div>
```

After:
```tsx
<StatDisplay
  label="P&L"
  value={formatPnL(pnl)}
  colorMode="financial"
  positive={pnl >= 0}
  negative={pnl < 0}
/>
```

### Using Design Tokens in CSS

Before:
```css
.my-class {
  font-size: 12px;
  gap: 8px;
  transition: all 0.15s ease;
  background: rgba(0, 230, 118, 0.15);
}
```

After:
```css
.my-class {
  font-size: var(--font-size-md);
  gap: var(--space-4);
  transition: all var(--duration-fast) var(--ease-default);
  background: rgba(var(--accent-green-rgb), 0.15);
}
```

## Testing

Tests for UI primitives are located in `__tests__/components/ui/`.

Run tests:
```bash
npm run test
```

## File Structure

```
components/
  ui/
    index.ts           # Export all UI primitives
    InfoTooltip.tsx    # Tooltip component
    StatDisplay.tsx    # Stat display component
  DataPanelsContainer.tsx  # Panel wrapper with variants

app/
  globals.css          # Design tokens and global styles

docs/
  DESIGN_SYSTEM.md     # This file

__tests__/
  components/
    ui/
      InfoTooltip.test.tsx
      StatDisplay.test.tsx
```
