#!/bin/bash
# Quick test script for Polygon-only system

set -e

echo "🧪 Testing Polygon-Only System"
echo "================================"
echo ""

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Check if virtual environment exists
if [ ! -d ".venv" ]; then
    echo -e "${YELLOW}⚠️  Virtual environment not found. Creating...${NC}"
    python3 -m venv .venv
fi

# Activate virtual environment
source .venv/bin/activate

# Install dependencies if needed
echo -e "${GREEN}📦 Checking dependencies...${NC}"
pip install -q -e ".[dev]" || pip install -q pytest pytest-asyncio pytest-cov

# Check for API key
if [ -z "$POLYGON_API_KEY" ]; then
    echo -e "${YELLOW}⚠️  POLYGON_API_KEY not set${NC}"
    echo "   Unit tests will run (mocked), but integration tests will be skipped"
    echo ""
fi

# Run tests
echo -e "${GREEN}🧪 Running Polygon Provider Tests...${NC}"
echo ""

# Unit tests (no API key needed)
echo "1️⃣  Unit Tests (Mocked):"
pytest tests/test_polygon_provider.py::TestPolygonConfig -v --tb=short
pytest tests/test_polygon_provider.py::TestPolygonProviderUnit -v --tb=short
pytest tests/test_polygon_provider.py::TestPolygonHealthMonitor -v --tb=short
pytest tests/test_polygon_provider.py::TestPolygonProviderErrorHandling -v --tb=short

echo ""
echo "2️⃣  Margin Models Tests (moved to risk/):"
pytest tests/test_margin_models.py -v --tb=short

echo ""
if [ -n "$POLYGON_API_KEY" ]; then
    echo -e "${GREEN}3️⃣  Integration Tests (Real API):${NC}"
    pytest tests/test_polygon_provider.py::TestPolygonProviderIntegration -v -m integration --tb=short
else
    echo -e "${YELLOW}3️⃣  Integration Tests: Skipped (no API key)${NC}"
fi

echo ""
echo -e "${GREEN}✅ Test Summary${NC}"
echo "================================"
pytest tests/test_polygon_provider.py tests/test_margin_models.py --co -q

echo ""
echo -e "${GREEN}🎉 Testing complete!${NC}"
echo ""
echo "Next steps:"
echo "  - Set POLYGON_API_KEY to run integration tests"
echo "  - See TESTING_GUIDE_POLYGON.md for detailed testing instructions"
echo "  - Run: pytest --cov=src/pearlalgo/data_providers --cov-report=html for coverage"
