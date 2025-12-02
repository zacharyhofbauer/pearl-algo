# Master Test Suite - Professional Trading System

## 🎯 Quick Start (Run This First)

```bash
# 1. Quick validation (5 minutes)
./QUICK_TEST_RUN.sh

# 2. If all pass, proceed to detailed tests
# See STEP_BY_STEP_TESTS.md for full sequence
```

---

## Test Categories

### ✅ Phase 1: System Integrity (MUST PASS)
- Environment validation
- Component imports
- Unit tests
- Configuration loading

### ✅ Phase 2: Feature Validation (SHOULD PASS)
- LLM providers
- Broker connections
- Risk rules
- Workflow integration

### ✅ Phase 3: Paper Trading (VALIDATE BEFORE LIVE)
- Single cycle test
- Short run (2-3 cycles)
- Monitoring validation
- Alert system

---

## Test Execution Order

1. **Quick Test** → `./QUICK_TEST_RUN.sh`
2. **Detailed Tests** → Follow `STEP_BY_STEP_TESTS.md`
3. **Paper Trading** → Run for 24 hours minimum
4. **Production Checklist** → See `PROFESSIONAL_TEST_PLAN.md`

---

## Critical Path

```
Environment Check → Unit Tests → LLM Test → Risk Validation → Single Cycle → Paper Trading
```

If any step fails, **STOP** and fix before proceeding.

---

## Feedback Template

After running tests, provide:
1. Which tests passed/failed
2. Error messages (if any)
3. Performance observations
4. Unexpected behavior
5. Recommendations

See `STEP_BY_STEP_TESTS.md` for detailed test instructions.
