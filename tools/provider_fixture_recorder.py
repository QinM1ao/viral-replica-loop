#!/usr/bin/env python3
"""Fail-closed, zero-submission replay for sealed Product Fixture responses."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class RecorderStop(RuntimeError):
    """A hard stop at the provider boundary."""

    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


def canonical_json_bytes(payload: Any) -> bytes:
    return (
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def file_sha256(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def parse_utc(value: str, field: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise RecorderStop("invalid_request", f"{field} must be UTC with a Z suffix")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise RecorderStop("invalid_request", f"{field} is not a timestamp") from exc
    return parsed.astimezone(timezone.utc)


class ZeroSubmissionRecorder:
    """Read one sealed recording. It intentionally has no write or transport API."""

    def __init__(self, recording_path: Path, *, now: str | None = None):
        self.recording_path = Path(recording_path).resolve()
        self.fixture_root = self.recording_path.parent.parent
        self.now = (
            parse_utc(now, "now")
            if now is not None
            else datetime.now(timezone.utc)
        )
        self.matched_replay_count = 0
        self.unmatched_request_count = 0
        self.fallback_count = 0
        try:
            self.recording = json.loads(
                self.recording_path.read_text(encoding="utf-8")
            )
        except (OSError, ValueError, TypeError) as exc:
            raise RecorderStop("recording_invalid", "recording is unreadable") from exc
        self._validate_recording()

    def _fixture_path(self, relative: object) -> Path:
        if not isinstance(relative, str) or not relative:
            raise RecorderStop("recording_invalid", "recording path is missing")
        candidate = (self.fixture_root / relative).resolve()
        try:
            candidate.relative_to(self.fixture_root)
        except ValueError as exc:
            raise RecorderStop(
                "recording_invalid", "recording path escapes fixture root"
            ) from exc
        if not candidate.is_file():
            raise RecorderStop("recording_invalid", f"missing sealed file: {relative}")
        return candidate

    def _validate_recording(self) -> None:
        recording = self.recording
        if (
            recording.get("kind") != "zero_submission_provider_recording"
            or recording.get("sealed") is not True
        ):
            raise RecorderStop("recording_invalid", "recording is not sealed")
        for capability in (
            "write_capability",
            "network_capability",
            "submit_capability",
            "golden_refresh_capability",
        ):
            if recording.get(capability) is not False:
                raise RecorderStop(
                    "recording_invalid", f"{capability} must be false"
                )

        request_path = self._fixture_path(recording.get("request_path"))
        response_path = self._fixture_path(recording.get("response_path"))
        if file_sha256(request_path) != recording.get("request_file_sha256"):
            raise RecorderStop("recording_invalid", "frozen request bytes changed")
        if file_sha256(response_path) != recording.get("response_file_sha256"):
            raise RecorderStop("recording_invalid", "sealed response bytes changed")

        try:
            request = json.loads(request_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError) as exc:
            raise RecorderStop(
                "recording_invalid", "frozen request is unreadable"
            ) from exc
        if not isinstance(request, dict):
            raise RecorderStop(
                "recording_invalid", "frozen request summary must be an object"
            )
        if sha256_bytes(canonical_json_bytes(request)) != recording.get(
            "request_summary_sha256"
        ):
            raise RecorderStop(
                "recording_invalid",
                "request summary does not match canonical frozen request",
            )

        try:
            response = json.loads(response_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError) as exc:
            raise RecorderStop(
                "recording_invalid", "sealed response is unreadable"
            ) from exc
        if sha256_bytes(canonical_json_bytes(response)) != recording.get(
            "response_summary_sha256"
        ):
            raise RecorderStop("recording_invalid", "sealed response summary changed")

        seal_payload = {
            "kind": recording["kind"],
            "request_summary_sha256": recording.get("request_summary_sha256"),
            "response_summary_sha256": recording.get("response_summary_sha256"),
            "valid_until": recording.get("valid_until"),
        }
        if sha256_bytes(canonical_json_bytes(seal_payload)) != recording.get(
            "seal_sha256"
        ):
            raise RecorderStop("recording_invalid", "recording seal changed")
        self.response = response

    def replay(self, request_summary: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(request_summary, dict):
            raise RecorderStop("invalid_request", "request summary must be an object")

        controls = request_summary.get("recorder_controls")
        if not isinstance(controls, dict):
            raise RecorderStop("invalid_request", "recorder controls are required")
        if controls.get("network_access") is not False:
            raise RecorderStop("network_forbidden", "network access is never allowed")
        endpoint = request_summary.get("provider", {}).get("endpoint")
        if not isinstance(endpoint, str) or not endpoint.startswith("recorder://"):
            raise RecorderStop(
                "network_forbidden", "only the recorder URI scheme is accepted"
            )
        if controls.get("real_submit") is not False:
            raise RecorderStop(
                "real_submit_forbidden", "real provider submission is never allowed"
            )
        if controls.get("refresh_golden") is not False:
            raise RecorderStop(
                "golden_refresh_forbidden",
                "golden evidence cannot be refreshed by replay",
            )
        if controls.get("mode") != "offline_replay":
            raise RecorderStop("invalid_request", "mode must be offline_replay")

        expires_at = parse_utc(request_summary.get("expires_at"), "expires_at")
        valid_until = parse_utc(self.recording.get("valid_until"), "valid_until")
        if self.now > expires_at or self.now > valid_until:
            raise RecorderStop("request_expired", "bound replay request is expired")

        approval = request_summary.get("approval")
        if not isinstance(approval, dict):
            raise RecorderStop("invalid_request", "approval binding is required")
        if (
            approval.get("provider_submission_allowed") is not False
            or approval.get("media_generation_allowed") is not False
            or approval.get("paid_task_limit") != 0
            or approval.get("cost_limit_usd") != 0
            or approval.get("retry_authority") != 0
        ):
            raise RecorderStop(
                "real_submit_forbidden", "approval must remain zero-spend"
            )

        request_digest = sha256_bytes(canonical_json_bytes(request_summary))
        if request_digest != self.recording.get("request_summary_sha256"):
            self.unmatched_request_count += 1
            raise RecorderStop(
                "unmatched_request",
                "request does not exactly match frozen input, model, parameters, "
                "approval, and reference order",
            )

        receipt = self.response.get("receipt", {})
        if (
            receipt.get("real_submit") is not False
            or receipt.get("task_created") is not False
            or receipt.get("paid_task_count") != 0
            or receipt.get("media_generation_task_count") != 0
            or receipt.get("external_effects") != []
        ):
            raise RecorderStop(
                "recording_invalid", "sealed response claims an external effect"
            )
        self.matched_replay_count += 1
        return copy.deepcopy(self.response)

    def metrics(self) -> dict[str, int]:
        return {
            "matched_replay_count": self.matched_replay_count,
            "unmatched_request_count": self.unmatched_request_count,
            "fallback_count": self.fallback_count,
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recording", required=True)
    parser.add_argument("--request", required=True)
    parser.add_argument("--now")
    parser.add_argument("--network", action="store_true")
    parser.add_argument("--real-submit", action="store_true")
    parser.add_argument("--refresh-golden", action="store_true")
    args = parser.parse_args()

    request = json.loads(Path(args.request).read_text(encoding="utf-8"))
    controls = request.setdefault("recorder_controls", {})
    controls["network_access"] = bool(args.network) or controls.get(
        "network_access", False
    )
    controls["real_submit"] = bool(args.real_submit) or controls.get(
        "real_submit", False
    )
    controls["refresh_golden"] = bool(args.refresh_golden) or controls.get(
        "refresh_golden", False
    )
    try:
        response = ZeroSubmissionRecorder(
            Path(args.recording), now=args.now
        ).replay(request)
    except RecorderStop as exc:
        print(f"STOP {exc.code}: {exc.detail}")
        return 3
    print(json.dumps(response, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
