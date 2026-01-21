"""
Shared visual regression testing utilities for chart generation.

This module provides a single source-of-truth for image comparison, validation,
and diff artifact generation used across all chart visual regression tests.

Usage:
    from tests.fixtures.visual_regression_utils import (
        validate_png_file,
        load_image_as_array,
        compare_images,
        save_diff_artifact,
        DEFAULT_PIXEL_TOLERANCE,
        DEFAULT_MAX_DIFF_PIXELS_PCT,
        MOBILE_PIXEL_TOLERANCE,
        MOBILE_MAX_DIFF_PIXELS_PCT,
    )
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Tuple

import numpy as np

# === Default Tolerances ===
# These tolerances account for minor font rendering differences across environments.
# Measured as mean absolute difference per pixel (0-255 scale).

# Standard tolerance for desktop/telegram charts
DEFAULT_PIXEL_TOLERANCE = 2.0  # Allow ~0.8% variance per channel
DEFAULT_MAX_DIFF_PIXELS_PCT = 1.0  # Allow up to 1% of pixels to differ

# Higher tolerance for mobile charts (font scaling causes more variance)
MOBILE_PIXEL_TOLERANCE = 2.5
MOBILE_MAX_DIFF_PIXELS_PCT = 2.0

# Tight tolerance for determinism checks (same-run comparison)
DETERMINISM_PIXEL_TOLERANCE = 0.5
DETERMINISM_MAX_DIFF_PIXELS_PCT = 0.1

# PNG magic bytes (first 8 bytes of any valid PNG file)
PNG_MAGIC = b'\x89PNG\r\n\x1a\n'


def validate_png_file(path: Path) -> Tuple[bool, str]:
    """
    Validate that a file is a valid PNG image.
    
    Checks:
    - File exists
    - File is not empty
    - File has valid PNG header (magic bytes)
    - File can be loaded and verified by PIL/matplotlib
    
    Args:
        path: Path to the PNG file to validate
        
    Returns:
        (is_valid, error_message) - error_message is empty string if valid
    """
    if not path.exists():
        return False, f"File does not exist: {path}"
    
    if path.stat().st_size == 0:
        return False, f"File is empty: {path}"
    
    # Check PNG magic bytes
    try:
        with open(path, "rb") as f:
            header = f.read(8)
        if header != PNG_MAGIC:
            return False, f"Invalid PNG header: got {header!r}, expected {PNG_MAGIC!r}"
    except Exception as e:
        return False, f"Could not read file: {e}"
    
    # Try to actually load the image to verify it's not truncated/corrupt
    try:
        try:
            from PIL import Image
            img = Image.open(path)
            img.verify()  # Verify without loading full data
        except ImportError:
            import matplotlib.pyplot as plt
            plt.imread(str(path))  # Will raise if corrupt
    except Exception as e:
        return False, f"Image file is corrupt or unreadable: {e}"
    
    return True, ""


def load_image_as_array(path: Path) -> Optional[np.ndarray]:
    """
    Load an image file as a numpy array.
    
    Attempts to use PIL first, falls back to matplotlib if PIL is unavailable.
    Normalizes float images to uint8 (0-255 scale).
    
    Args:
        path: Path to the image file
        
    Returns:
        Numpy array of image data, or None if loading fails
    """
    try:
        from PIL import Image
        img = Image.open(path)
        return np.array(img)
    except ImportError:
        # Fallback to matplotlib
        import matplotlib.pyplot as plt
        img = plt.imread(str(path))
        # Convert to uint8 if normalized float
        if img.dtype == np.float32 or img.dtype == np.float64:
            img = (img * 255).astype(np.uint8)
        return img
    except Exception:
        return None


def compare_images(
    actual: np.ndarray,
    expected: np.ndarray,
    *,
    tolerance: float = DEFAULT_PIXEL_TOLERANCE,
    max_diff_pct: float = DEFAULT_MAX_DIFF_PIXELS_PCT,
) -> Tuple[bool, float, float, Optional[np.ndarray]]:
    """
    Compare two images with tolerance for rendering differences.
    
    Visual regression comparison that accounts for minor font/anti-aliasing
    differences across environments while catching semantic visual changes.
    
    Args:
        actual: Rendered image as numpy array
        expected: Baseline image as numpy array
        tolerance: Maximum mean pixel difference allowed (0-255 scale)
        max_diff_pct: Maximum percentage of pixels allowed to differ
        
    Returns:
        (passed, mean_diff, diff_pct, diff_image)
        - passed: True if within tolerance
        - mean_diff: Mean absolute difference per pixel
        - diff_pct: Percentage of pixels exceeding tolerance
        - diff_image: Visualization with differences highlighted in red
    """
    # Handle shape differences by cropping to common dimensions
    if actual.shape != expected.shape:
        h = min(actual.shape[0], expected.shape[0])
        w = min(actual.shape[1], expected.shape[1])
        actual = actual[:h, :w]
        expected = expected[:h, :w]
        
        # If still different (e.g., channel count), fail
        if actual.shape != expected.shape:
            return False, 255.0, 100.0, None

    # Compute pixel-wise absolute difference
    diff = np.abs(actual.astype(np.float32) - expected.astype(np.float32))
    
    # Mean difference across all pixels and channels
    mean_diff = float(np.mean(diff))
    
    # Percentage of pixels with any channel exceeding tolerance
    if diff.ndim == 3:
        diff_pixels = np.any(diff > tolerance, axis=-1)
    else:
        diff_pixels = diff > tolerance
    diff_pct = float(np.mean(diff_pixels) * 100)
    
    # Create diff visualization (highlight differences in red)
    diff_image = expected.copy()
    if diff.ndim == 3:
        mask = np.any(diff > tolerance, axis=-1)
        if diff_image.shape[-1] == 4:  # RGBA
            diff_image[mask] = [255, 0, 0, 255]
        else:  # RGB
            diff_image[mask] = [255, 0, 0]
    
    passed = (mean_diff <= tolerance) and (diff_pct <= max_diff_pct)
    return passed, mean_diff, diff_pct, diff_image


def save_diff_artifact(
    actual: Optional[np.ndarray],
    expected: Optional[np.ndarray],
    diff: Optional[np.ndarray],
    name: str,
    output_dir: Optional[Path] = None,
) -> Path:
    """
    Save comparison artifacts for debugging failed visual regression tests.
    
    Saves three images:
    - {name}_actual.png: The rendered image
    - {name}_expected.png: The baseline image
    - {name}_diff.png: Visualization with differences highlighted
    
    Args:
        actual: Rendered image array (or None to skip)
        expected: Baseline image array (or None to skip)
        diff: Diff visualization array (or None to skip)
        name: Base name for artifact files (e.g., "dashboard", "entry")
        output_dir: Directory to save artifacts (default: tests/artifacts)
        
    Returns:
        Path to the output directory
    """
    if output_dir is None:
        # Default to tests/artifacts relative to this file
        output_dir = Path(__file__).parent.parent / "artifacts"
    
    output_dir.mkdir(parents=True, exist_ok=True)
    
    try:
        from PIL import Image
        
        if actual is not None:
            Image.fromarray(actual).save(output_dir / f"{name}_actual.png")
        if expected is not None:
            Image.fromarray(expected).save(output_dir / f"{name}_expected.png")
        if diff is not None:
            Image.fromarray(diff).save(output_dir / f"{name}_diff.png")
    except ImportError:
        import matplotlib.pyplot as plt
        
        if actual is not None:
            plt.imsave(str(output_dir / f"{name}_actual.png"), actual)
        if expected is not None:
            plt.imsave(str(output_dir / f"{name}_expected.png"), expected)
        if diff is not None:
            plt.imsave(str(output_dir / f"{name}_diff.png"), diff)
    
    return output_dir


def format_regression_failure_message(
    mean_diff: float,
    diff_pct: float,
    tolerance: float,
    max_diff_pct: float,
    artifact_dir: Path,
    baseline_update_command: str,
) -> str:
    """
    Format a standardized failure message for visual regression test failures.
    
    Args:
        mean_diff: Actual mean pixel difference
        diff_pct: Actual percentage of differing pixels
        tolerance: Expected pixel tolerance
        max_diff_pct: Expected max diff percentage
        artifact_dir: Directory where diff artifacts were saved
        baseline_update_command: Command to regenerate baseline
        
    Returns:
        Formatted failure message string
    """
    return (
        f"Visual regression detected!\n"
        f"  Mean pixel difference: {mean_diff:.2f} (tolerance: {tolerance})\n"
        f"  Pixels differing: {diff_pct:.2f}% (tolerance: {max_diff_pct}%)\n"
        f"  Diff artifacts saved to: {artifact_dir}\n"
        f"\n"
        f"If this change is intentional, update the baseline:\n"
        f"  {baseline_update_command}"
    )
