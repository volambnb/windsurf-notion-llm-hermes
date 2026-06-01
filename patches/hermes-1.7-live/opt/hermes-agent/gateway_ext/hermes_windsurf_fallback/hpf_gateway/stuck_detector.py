from __future__ import annotations

import hashlib
import re
from difflib import SequenceMatcher

from .types import ErrorClass, TaskState


def classify_error(status_code: int | None, message: str) -> ErrorClass:
    normalized = message.lower()
    if status_code in {402, 429} or any(token in normalized for token in ("quota", "rate limit", "trial limit", "credit exhausted")):
        return "known_quota"
    if status_code in {503, 504} or "timeout" in normalized or "overloaded" in normalized:
        return "known_transient"
    if status_code in {401, 403, 404} or "model_not_found" in normalized or "unauthorized" in normalized:
        return "known_fatal"
    return "unknown"


def error_fingerprint(stderr: str) -> str:
    normalized = stderr.lower()
    normalized = re.sub(r"\b\d{4}-\d{2}-\d{2}[^\s]*", "", normalized)
    normalized = re.sub(r"\bline\s+\d+\b", "line", normalized)
    normalized = re.sub(r"[a-z]:\\[^\s]+", "<path>", normalized)
    normalized = re.sub(r"/[^\s:]+", "<path>", normalized)
    normalized = re.sub(r"\b\d+\b", "<num>", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:12]


def code_diff_similarity(diff_a: str, diff_b: str) -> float:
    if not diff_a and not diff_b:
        return 0.0
    return SequenceMatcher(None, diff_a, diff_b).ratio()


class StuckDetector:
    def compute_score(self, task_state: TaskState) -> float:
        attempts_score = min(task_state.attempts / 3, 1.0)
        fingerprint_score = 1.0 if task_state.fingerprint_current == task_state.fingerprint_previous and task_state.fingerprint_current else 0.0
        diff_score = code_diff_similarity(task_state.diff_current, task_state.diff_previous)
        progress_delta = task_state.progress_current - task_state.progress_previous
        progress_score = 1.0 if progress_delta <= 0 else max(0.0, 1 - progress_delta * 5)
        elapsed_score = min(task_state.elapsed_minutes / 5, 1.0)
        return (
            0.15 * attempts_score
            + 0.30 * fingerprint_score
            + 0.25 * diff_score
            + 0.20 * progress_score
            + 0.10 * elapsed_score
        )
