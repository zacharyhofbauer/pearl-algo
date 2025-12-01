from __future__ import annotations

import logging
from pathlib import Path
from rich.logging import RichHandler


def setup_logging(level: str = "INFO", log_file: str | Path | None = None) -> None:
    handlers = [RichHandler(rich_tracebacks=True)]
    
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_path)
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
        )
        handlers.append(file_handler)
    
    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=handlers,
    )
