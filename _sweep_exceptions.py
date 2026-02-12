#!/usr/bin/env python3
"""
Exception handler sweep script.
Processes bare `except Exception:` handlers and adds structured logging.

Rules:
- Change `except Exception:` to `except Exception as e:`
- Replace bare `pass` with appropriate logger call
- For handlers that set defaults, add logger call before the fallback
- Skip `# pragma: no cover` import guards
- Skip specific import guard lines (hardcoded)
- Don't add log if body already has a logger.* call
"""

import re

BASE = "/home/pearl/PearlAlgoProject/"

# Files and their configurations
FILES = [
    {
        "path": "src/pearlalgo/market_agent/state_manager.py",
        "log_line": 'logger.warning(f"State operation failed: {e}")',
        "skip_lines": {42},  # import guard: SQLITE_AVAILABLE = False
    },
    {
        "path": "src/pearlalgo/market_agent/scheduled_tasks.py",
        "log_line": 'logger.debug(f"Non-critical: {e}")',
        "skip_lines": set(),
    },
    {
        "path": "src/pearlalgo/market_agent/operator_handler.py",
        "log_line": 'logger.debug(f"Non-critical: {e}")',
        "skip_lines": set(),
    },
    {
        "path": "src/pearlalgo/market_agent/telegram_command_handler.py",
        "log_line": 'logger.debug(f"Non-critical: {e}")',
        "skip_lines": {117},  # import guard: HTTPXRequest = None (within telegram import block)
    },
    {
        "path": "src/pearlalgo/market_agent/telegram_notifier.py",
        "log_line": 'logger.debug(f"Non-critical: {e}")',
        "skip_lines": set(),
    },
]


def process_file(filepath, log_line, skip_lines):
    """
    Process a single file to update bare exception handlers.

    Returns the number of handlers modified.
    """
    with open(filepath, "r") as f:
        lines = f.readlines()

    result = []
    modified = 0
    i = 0

    while i < len(lines):
        line = lines[i]
        line_num = i + 1  # 1-based line numbers

        # Match bare `except Exception:` (not `except Exception as e:`)
        m = re.match(r"^(\s*)except Exception:\s*(#.*)?$", line.rstrip("\n"))

        if m:
            indent_str = m.group(1)
            comment = (m.group(2) or "").strip()

            # Skip if # pragma: no cover
            if "# pragma: no cover" in comment:
                result.append(line)
                i += 1
                continue

            # Skip specific hardcoded import-guard lines
            if line_num in skip_lines:
                result.append(line)
                i += 1
                continue

            # --- Transform the except line ---
            if comment:
                new_except = f"{indent_str}except Exception as e:  {comment}\n"
            else:
                new_except = f"{indent_str}except Exception as e:\n"
            result.append(new_except)
            modified += 1
            i += 1

            # Collect any blank lines between except and body
            blank_lines = []
            while i < len(lines) and lines[i].strip() == "":
                blank_lines.append(lines[i])
                i += 1

            if i >= len(lines):
                result.extend(blank_lines)
                continue

            # Determine body indent from first non-blank body line
            first_body = lines[i]
            body_indent = first_body[: len(first_body) - len(first_body.lstrip())]
            first_stripped = first_body.strip()

            # Scan ahead to check if the body already has a logger.* call
            # (look past comments to the first actual code line)
            body_has_logger = False
            j = i
            while j < len(lines):
                check_line = lines[j]
                check_stripped = check_line.strip()
                if check_stripped == "":
                    j += 1
                    continue
                check_indent_len = len(check_line) - len(check_line.lstrip())
                # If we've dedented past the body, stop
                if check_indent_len < len(body_indent):
                    break
                # Skip comments
                if check_stripped.startswith("#"):
                    j += 1
                    continue
                # First real code line in the body
                if "logger." in check_stripped:
                    body_has_logger = True
                break

            if first_stripped == "pass":
                # Replace `pass` with logger call
                result.extend(blank_lines)
                result.append(f"{body_indent}{log_line}\n")
                i += 1  # consume the `pass` line
            elif body_has_logger:
                # Body already has logging — just adding `as e:` is enough
                result.extend(blank_lines)
                # Don't insert extra log; body lines handled by main loop
            else:
                # Insert logger call before existing body
                result.extend(blank_lines)
                result.append(f"{body_indent}{log_line}\n")
                # Don't advance i — body line still needs to be emitted by main loop
        else:
            result.append(line)
            i += 1

    with open(filepath, "w") as f:
        f.writelines(result)

    return modified


# --- Main ---
grand_total = 0
for cfg in FILES:
    filepath = BASE + cfg["path"]
    count = process_file(filepath, cfg["log_line"], cfg["skip_lines"])
    grand_total += count
    print(f"  {cfg['path']}: {count} handlers modified")

print(f"\n  TOTAL: {grand_total} handlers modified")
