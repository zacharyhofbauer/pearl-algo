"""
PEARL Update Notification System.

Tracks code/system updates and allows PEARL to communicate them to the user.
Updates are stored in a JSON file and can be sent via Telegram.
"""
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List, Dict, Any

# Custom PEARL emoji ID
PEARL_EMOJI_ID = "5177134388684523561"


def _get_updates_file() -> Path:
    """Get path to updates tracking file."""
    project_root = Path(__file__).parent.parent.parent.parent
    return project_root / "data" / "pearl_updates.json"


def _load_updates() -> Dict[str, Any]:
    """Load updates from file."""
    updates_file = _get_updates_file()
    if updates_file.exists():
        try:
            return json.loads(updates_file.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"updates": [], "last_notified_at": None}


def _save_updates(data: Dict[str, Any]) -> None:
    """Save updates to file."""
    updates_file = _get_updates_file()
    updates_file.parent.mkdir(parents=True, exist_ok=True)
    updates_file.write_text(json.dumps(data, indent=2), encoding="utf-8")


def add_update(
    title: str,
    description: str,
    category: str = "feature",  # feature, fix, improvement, config
    notify_user: bool = True,
) -> None:
    """
    Add a new update to the tracking system.
    
    Args:
        title: Short title of the update
        description: Detailed description
        category: Type of update (feature, fix, improvement, config)
        notify_user: Whether to notify user on next check-in
    """
    data = _load_updates()
    
    update = {
        "id": datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S"),
        "title": title,
        "description": description,
        "category": category,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "notified": not notify_user,  # If notify_user=False, mark as already notified
    }
    
    data["updates"].append(update)
    
    # Keep only last 50 updates
    data["updates"] = data["updates"][-50:]
    
    _save_updates(data)


def get_pending_updates() -> List[Dict[str, Any]]:
    """Get updates that haven't been notified to user yet."""
    data = _load_updates()
    return [u for u in data["updates"] if not u.get("notified", False)]


def mark_updates_notified(update_ids: Optional[List[str]] = None) -> None:
    """Mark updates as notified."""
    data = _load_updates()
    
    for update in data["updates"]:
        if update_ids is None or update["id"] in update_ids:
            update["notified"] = True
    
    data["last_notified_at"] = datetime.now(timezone.utc).isoformat()
    _save_updates(data)


def format_updates_message(updates: List[Dict[str, Any]]) -> str:
    """
    Format updates for Telegram message (MarkdownV2 with custom emoji).
    
    Returns MarkdownV2 formatted message ready to send.
    """
    if not updates:
        return ""
    
    # Escape function for MarkdownV2
    def esc(text: str) -> str:
        escape_chars = r'_*[]()~`>#+-=|{}.!'
        result = ""
        for char in text:
            if char in escape_chars:
                result += f"\\{char}"
            else:
                result += char
        return result
    
    # Category icons
    icons = {
        "feature": "✨",
        "fix": "🔧",
        "improvement": "📈",
        "config": "⚙️",
    }
    
    lines = [
        f"![🐚](tg://emoji?id={PEARL_EMOJI_ID}) *PEARL*",
        "System Update",
        "",
    ]
    
    for update in updates[:5]:  # Show max 5 updates
        icon = icons.get(update.get("category", "feature"), "📝")
        title = esc(update.get("title", "Update"))
        desc = esc(update.get("description", ""))
        lines.append(f"{icon} *{title}*")
        if desc:
            lines.append(f"   {desc}")
        lines.append("")
    
    if len(updates) > 5:
        lines.append(f"\\.\\.\\. and {len(updates) - 5} more updates")
    
    return "\n".join(lines)


async def send_updates_notification(bot_token: str, chat_id: str) -> bool:
    """
    Send pending updates notification to Telegram.
    
    Returns True if updates were sent, False if no pending updates.
    """
    updates = get_pending_updates()
    if not updates:
        return False
    
    message = format_updates_message(updates)
    if not message:
        return False
    
    try:
        from telegram import Bot
        bot = Bot(token=bot_token)
        await bot.send_message(
            chat_id=chat_id,
            text=message,
            parse_mode="MarkdownV2"
        )
        
        # Mark as notified
        mark_updates_notified([u["id"] for u in updates])
        return True
    except Exception as e:
        print(f"Failed to send updates notification: {e}")
        return False


# Convenience function for adding common update types
def add_feature(title: str, description: str = "") -> None:
    """Add a new feature update."""
    add_update(title, description, category="feature")


def add_fix(title: str, description: str = "") -> None:
    """Add a bug fix update."""
    add_update(title, description, category="fix")


def add_improvement(title: str, description: str = "") -> None:
    """Add an improvement update."""
    add_update(title, description, category="improvement")
