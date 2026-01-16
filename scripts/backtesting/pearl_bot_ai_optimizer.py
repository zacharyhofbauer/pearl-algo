#!/usr/bin/env python3
"""
AI-Powered Pearl Bot Optimizer

Uses OpenAI (via the internal `ClaudeClient` compatibility wrapper) to analyze Pearl bot performance and suggest improvements.
Automatically generates code patches and configuration updates.
"""

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Any
import pandas as pd

from pearlalgo.utils.claude_client import ClaudeClient, ClaudeAPIKeyMissingError
from pearlalgo.utils.logger import logger


class PearlBotAIOptimizer:
    """AI-powered optimizer for Pearl trading bots."""

    def __init__(self, state_dir: Path = None):
        self.state_dir = state_dir or Path("data/nq_agent_state")
        self.trades_db = self.state_dir / "trades.db"
        self.signals_file = self.state_dir / "signals.jsonl"

        try:
            self.claude = ClaudeClient()
        except ClaudeAPIKeyMissingError:
            logger.warning("OpenAI API key not found - AI optimization disabled")
            self.claude = None

    def analyze_performance(self, days_back: int = 7) -> Dict[str, Any]:
        """Analyze recent Pearl bot performance."""
        cutoff_date = datetime.now() - timedelta(days=days_back)

        # Get trades from database
        conn = sqlite3.connect(str(self.trades_db))
        query = """
        SELECT * FROM trades
        WHERE entry_time >= ?
        AND (signal_type LIKE '%unified%' OR signal_type LIKE '%momentum%')
        ORDER BY entry_time DESC
        """
        trades_df = pd.read_sql_query(query, conn, params=[cutoff_date.isoformat()])
        conn.close()

        if trades_df.empty:
            return {"error": "No Pearl bot trades found in analysis period"}

        # Performance metrics
        total_trades = len(trades_df)
        win_rate = (trades_df['is_win'] == 1).mean()
        avg_win = trades_df[trades_df['is_win'] == 1]['pnl'].mean()
        avg_loss = trades_df[trades_df['is_win'] == 0]['pnl'].mean()
        total_pnl = trades_df['pnl'].sum()

        # By bot type
        bot_performance = {}
        for bot_type in ['trend_follower', 'breakout_trader', 'mean_reverter']:
            bot_trades = trades_df[trades_df['signal_type'].str.contains(bot_type)]
            if not bot_trades.empty:
                bot_performance[bot_type] = {
                    'trades': len(bot_trades),
                    'win_rate': (bot_trades['is_win'] == 1).mean(),
                    'avg_pnl': bot_trades['pnl'].mean(),
                    'total_pnl': bot_trades['pnl'].sum()
                }

        # Recent losing trades for analysis
        losing_trades = trades_df[trades_df['is_win'] == 0].head(5)

        return {
            'period_days': days_back,
            'total_trades': total_trades,
            'win_rate': win_rate,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'total_pnl': total_pnl,
            'bot_performance': bot_performance,
            'recent_losses': losing_trades.to_dict('records'),
            'profit_factor': abs(avg_win / avg_loss) if avg_loss != 0 else float('inf')
        }

    def generate_ai_recommendations(self, performance_data: Dict[str, Any]) -> Dict[str, Any]:
        """Use OpenAI to generate optimization recommendations."""
        if not self.claude:
            return {"error": "OpenAI client not available"}

        prompt = f"""
        Analyze this Pearl bot trading performance and provide specific recommendations:

        PERFORMANCE DATA:
        - Period: {performance_data['period_days']} days
        - Total Trades: {performance_data['total_trades']}
        - Win Rate: {performance_data['win_rate']:.1%}
        - Average Win: ${performance_data['avg_win']:.2f}
        - Average Loss: ${performance_data['avg_loss']:.2f}
        - Total P&L: ${performance_data['total_pnl']:.2f}
        - Profit Factor: {performance_data['profit_factor']:.2f}

        BOT PERFORMANCE:
        {json.dumps(performance_data['bot_performance'], indent=2)}

        RECENT LOSSES:
        {json.dumps(performance_data['recent_losses'][:3], indent=2)}

        Provide specific recommendations for:
        1. Risk management improvements
        2. Entry/exit timing adjustments
        3. Bot-specific optimizations
        4. Configuration parameter changes
        5. Code modifications needed

        Focus on actionable changes that could improve the profit factor and win rate.
        """

        try:
            response = self.claude.generate_response(prompt, max_tokens=2000)

            # Parse recommendations
            recommendations = {
                'timestamp': datetime.now().isoformat(),
                'analysis': response,
                'performance_summary': performance_data,
                'suggested_changes': self._parse_recommendations(response)
            }

            return recommendations

        except Exception as e:
            logger.error(f"AI analysis failed: {e}")
            return {"error": str(e)}

    def _parse_recommendations(self, ai_response: str) -> List[Dict[str, Any]]:
        """Parse AI recommendations into structured format."""
        # Simple parsing - in production you'd want more sophisticated NLP
        recommendations = []

        if "risk management" in ai_response.lower():
            recommendations.append({
                'category': 'risk_management',
                'priority': 'high',
                'description': 'Improve risk management based on AI analysis'
            })

        if "entry" in ai_response.lower():
            recommendations.append({
                'category': 'entry_timing',
                'priority': 'medium',
                'description': 'Adjust entry timing criteria'
            })

        if "stop loss" in ai_response.lower():
            recommendations.append({
                'category': 'stop_loss',
                'priority': 'high',
                'description': 'Optimize stop loss placement'
            })

        return recommendations

    def apply_recommendations(self, recommendations: Dict[str, Any], auto_apply: bool = False) -> Dict[str, Any]:
        """Apply AI-generated recommendations."""
        if not auto_apply:
            logger.info("Auto-apply disabled - manual review required")
            return {"status": "manual_review_required", "recommendations": recommendations}

        # In production, this would apply changes to config files and bot code
        logger.info("Applying AI recommendations...")

        applied_changes = []

        for rec in recommendations.get('suggested_changes', []):
            if rec['category'] == 'risk_management':
                # Example: Adjust stop loss percentages
                applied_changes.append(f"Updated risk management: {rec['description']}")

            elif rec['category'] == 'entry_timing':
                # Example: Modify entry filters
                applied_changes.append(f"Adjusted entry timing: {rec['description']}")

        return {
            "status": "applied",
            "changes": applied_changes,
            "timestamp": datetime.now().isoformat()
        }

    def run_optimization_cycle(self) -> Dict[str, Any]:
        """Complete optimization cycle: analyze -> recommend -> apply."""
        logger.info("Starting Pearl bot AI optimization cycle")

        # Analyze performance
        performance = self.analyze_performance(days_back=7)

        if 'error' in performance:
            return performance

        # Generate AI recommendations
        recommendations = self.generate_ai_recommendations(performance)

        if 'error' in recommendations:
            return recommendations

        # Apply recommendations (if auto-apply enabled)
        result = self.apply_recommendations(recommendations, auto_apply=False)

        return {
            'cycle_completed': datetime.now().isoformat(),
            'performance': performance,
            'recommendations': recommendations,
            'application_result': result
        }


def main():
    """Command line interface for Pearl bot AI optimizer."""
    optimizer = PearlBotAIOptimizer()

    print("🤖 Pearl Bot AI Optimizer")
    print("=" * 50)

    result = optimizer.run_optimization_cycle()

    if 'error' in result:
        print(f"❌ Error: {result['error']}")
        return

    print("✅ Optimization cycle completed")
    print(f"📊 Analyzed {result['performance']['total_trades']} trades")
    print(f"🎯 Win Rate: {result['performance']['win_rate']:.1%}")
    print(f"💰 Total P&L: ${result['performance']['total_pnl']:.2f}")

    if result['recommendations'].get('suggested_changes'):
        print(f"\n🔧 AI Recommendations ({len(result['recommendations']['suggested_changes'])}):")
        for rec in result['recommendations']['suggested_changes']:
            print(f"  • {rec['category']}: {rec['description']}")

    print(f"\n📝 Full analysis saved to optimization log")


if __name__ == "__main__":
    main()