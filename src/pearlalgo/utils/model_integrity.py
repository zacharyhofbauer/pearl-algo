"""
Model Integrity Verification

Provides SHA256 hash verification for ML model files to detect tampering
or corruption. Each model file gets a companion .sha256 file containing
its hash.

Usage:
    from pearlalgo.utils.model_integrity import save_model_with_hash, load_model_with_verification

    # When saving a model
    joblib.dump(model, path)
    save_model_hash(path)

    # When loading a model
    if verify_model_hash(path):
        model = joblib.load(path)
    else:
        raise ValueError("Model integrity check failed")
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Optional, Tuple

from pearlalgo.utils.logger import logger


def compute_file_hash(path: Path) -> str:
    """
    Compute SHA256 hash of a file.

    Args:
        path: Path to the file

    Returns:
        Hexadecimal hash string
    """
    sha256 = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


def get_hash_path(model_path: Path) -> Path:
    """Get the path to the hash sidecar file for a model."""
    return model_path.with_suffix(model_path.suffix + ".sha256")


def save_model_hash(model_path: Path) -> bool:
    """
    Compute and save the hash of a model file.

    Creates a companion .sha256 file next to the model.

    Args:
        model_path: Path to the model file

    Returns:
        True if successful
    """
    model_path = Path(model_path)
    if not model_path.exists():
        logger.warning(f"Cannot compute hash: model file not found: {model_path}")
        return False

    try:
        file_hash = compute_file_hash(model_path)
        hash_path = get_hash_path(model_path)
        hash_path.write_text(file_hash)
        logger.debug(f"Saved model hash: {hash_path}")
        return True
    except Exception as e:
        logger.warning(f"Failed to save model hash: {e}")
        return False


def verify_model_hash(model_path: Path, strict: bool = False) -> Tuple[bool, Optional[str]]:
    """
    Verify the integrity of a model file against its stored hash.

    Args:
        model_path: Path to the model file
        strict: If True, fail when no hash file exists. If False, pass with warning.

    Returns:
        Tuple of (is_valid, reason)
        - is_valid: True if hash matches or no hash file exists (non-strict mode)
        - reason: Description of verification result
    """
    model_path = Path(model_path)
    hash_path = get_hash_path(model_path)

    if not model_path.exists():
        return False, f"Model file not found: {model_path}"

    if not hash_path.exists():
        if strict:
            return False, f"Hash file not found: {hash_path}"
        else:
            logger.debug(f"No hash file for {model_path.name}, skipping verification")
            return True, "no_hash_file"

    try:
        expected_hash = hash_path.read_text().strip()
        actual_hash = compute_file_hash(model_path)

        if actual_hash == expected_hash:
            logger.debug(f"Model integrity verified: {model_path.name}")
            return True, "hash_verified"
        else:
            logger.error(
                f"Model integrity check FAILED for {model_path.name}: "
                f"expected {expected_hash[:16]}..., got {actual_hash[:16]}..."
            )
            return False, "hash_mismatch"

    except Exception as e:
        logger.warning(f"Hash verification error for {model_path}: {e}")
        return False, f"verification_error: {e}"


def delete_model_hash(model_path: Path) -> None:
    """Delete the hash file for a model (e.g., when model is deleted)."""
    hash_path = get_hash_path(Path(model_path))
    if hash_path.exists():
        hash_path.unlink()
        logger.debug(f"Deleted model hash: {hash_path}")
