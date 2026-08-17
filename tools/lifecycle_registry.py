#!/usr/bin/env python3
"""Single lifecycle interface for runner rules and user-visible progress."""

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Dict, Optional, Tuple


INTERNAL_PROGRESS_STAGES = {
    "confirmation_gate",
    "retry_limit_gate",
    "self_audit_review",
    "unknown",
}


@dataclass(frozen=True)
class Progress:
    index: int
    label: str
    summary: str
    canonical: frozenset
    statuses: frozenset
    next_stages: frozenset
    status_prefixes: frozenset = frozenset()

    def as_dict(self) -> dict:
        return {
            "index": self.index,
            "label": self.label,
            "summary": self.summary,
            "canonical": self.canonical,
            "statuses": self.statuses,
            "next_stages": self.next_stages,
            "status_prefixes": self.status_prefixes,
        }


_LEGACY_PROGRESS_STAGES = (
    Progress(
        index=1,
        label="看懂原片",
        summary="拆清楚原视频剧情、口播、镜头节奏和污染风险。",
        canonical=frozenset(
            {"asset_gate", "source_blueprint", "story_analysis", "storyboard"}
        ),
        statuses=frozenset({"pending", "story_analyzed"}),
        next_stages=frozenset(
            {"source_blueprint", "story_analysis", "storyboard"}
        ),
    ),
    Progress(
        index=2,
        label="改好分镜",
        summary=(
            "一次性改完所有 Part 分镜，替换人物和产品，并去掉旧字幕/旧画面污染。"
        ),
        canonical=frozenset(
            {
                "image_sample",
                "image_sample_review",
                "image_batch_qc",
                "afterwash_reference_review",
            }
        ),
        statuses=frozenset(
            {
                "storyboard_passed",
                "sample_image_waiting_review",
                "image_sample_approved",
                "afterwash_ref_waiting_review",
                "afterwash_ref_passed",
            }
        ),
        next_stages=frozenset(
            {
                "image_sample",
                "image_sample_review",
                "image_batch_qc",
                "sample_image_waiting_review",
                "afterwash_reference_review",
            }
        ),
    ),
    Progress(
        index=3,
        label="写视频脚本",
        summary="写口播、缝点、Seedance 提示词和请求素材，并完成音频边界检查。",
        canonical=frozenset(
            {
                "voiceover",
                "seam",
                "seedance_prompt",
                "audio_boundary_qc",
                "request_qc",
                "pre_seedance_pack",
            }
        ),
        statuses=frozenset(
            {
                "image_qc_passed",
                "part2_storyboard_loop_passed",
                "voiceover_done",
                "seam_done",
                "seedance_prompt_done",
                "audio_boundary_qc_done",
            }
        ),
        next_stages=frozenset(
            {
                "voiceover",
                "seam",
                "seedance_prompt",
                "audio_boundary_qc",
                "request_qc",
                "pre_seedance_pack",
            }
        ),
    ),
    Progress(
        index=4,
        label="生成视频",
        summary="确认付费范围，提交或等待 Seedance，并下载各 Part 视频。",
        canonical=frozenset(
            {"cost_gate", "generation_approval", "generation"}
        ),
        statuses=frozenset(
            {"seedance_inputs_prepared", "generation_approved"}
        ),
        status_prefixes=frozenset(
            {"seedance_inputs_prepared", "seedance_generating"}
        ),
        next_stages=frozenset({"generation_approval", "generation"}),
    ),
    Progress(
        index=5,
        label="质检交付",
        summary="按明确剪辑计划收尾成片，跑技术 QC，交付最终视频或明确失败原因。",
        canonical=frozenset(
            {
                "finishing",
                "subtitle_removal",
                "final_qc",
                "caption_finishing",
                "terminal",
            }
        ),
        statuses=frozenset(
            {
                "finishing",
                "subtitle_removal",
                "final_qc",
                "caption_finishing",
                "done",
                "blocked",
            }
        ),
        status_prefixes=frozenset(
            {
                "finishing",
                "subtitle_removal",
                "final_qc",
                "caption_finishing",
            }
        ),
        next_stages=frozenset(
            {
                "finishing",
                "subtitle_removal",
                "final_qc",
                "caption_finishing",
                "done",
                "blocked",
            }
        ),
    ),
)


def _legacy_progress_config():
    return [
        {
            "index": stage.index,
            "label": stage.label,
            "summary": stage.summary,
            "canonical": sorted(stage.canonical),
            "statuses": sorted(stage.statuses),
            "next_stages": sorted(stage.next_stages),
            "status_prefixes": sorted(stage.status_prefixes),
        }
        for stage in _LEGACY_PROGRESS_STAGES
    ]


class LifecycleRegistry:
    """Validated lifecycle rules behind one small interface."""

    def __init__(
        self,
        config: Dict[str, Any],
        path: Path,
        *,
        legacy_partial: bool = False,
    ):
        self.config = config
        self.path = path
        self.legacy_partial = legacy_partial
        self._validate()
        self.progress_stages = tuple(
            self._progress_from_config(item)
            for item in self.config["progress"]
        )

    @classmethod
    def load(cls, root: Path) -> "LifecycleRegistry":
        root = Path(root).resolve()
        candidates = (
            root / "rules" / "STAGE_RULES.json",
            root / "stages" / "STAGE_RULES.json",
        )
        path = next(
            (candidate for candidate in candidates if candidate.is_file()),
            candidates[0],
        )
        try:
            config = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise ValueError(f"lifecycle rules file is unavailable: {path}") from exc
        except json.JSONDecodeError as exc:
            raise ValueError(f"lifecycle rules file is invalid JSON: {path}") from exc
        return cls.from_config(config, path=path)

    @classmethod
    def from_config(
        cls,
        config: Dict[str, Any],
        path: Optional[Path] = None,
    ) -> "LifecycleRegistry":
        if not isinstance(config, dict):
            raise ValueError("lifecycle registry must be an object")
        legacy_partial = bool(config.get("_legacy_partial")) or any(
            key not in config
            for key in ("version", "initial", "progress")
        )
        normalized = dict(config)
        if legacy_partial:
            normalized["_legacy_partial"] = True
        normalized.setdefault("version", 1)
        normalized.setdefault(
            "initial",
            {
                "status": "pending",
                "next_stage": "source_blueprint",
            },
        )
        normalized.setdefault("progress", _legacy_progress_config())
        if legacy_partial and isinstance(normalized.get("rules"), list):
            normalized["rules"] = [
                {
                    **rule,
                    "id": str(rule.get("id") or f"legacy-rule-{index}"),
                }
                if isinstance(rule, dict)
                else rule
                for index, rule in enumerate(normalized["rules"], start=1)
            ]
        return cls(
            normalized,
            path or Path("<memory>"),
            legacy_partial=legacy_partial,
        )

    @staticmethod
    def _progress_from_config(item: dict) -> Progress:
        return Progress(
            index=item["index"],
            label=item["label"],
            summary=item["summary"],
            canonical=frozenset(item["canonical"]),
            statuses=frozenset(item["statuses"]),
            next_stages=frozenset(item["next_stages"]),
            status_prefixes=frozenset(item["status_prefixes"]),
        )

    @staticmethod
    def rule_matches(rule: dict, status: str) -> bool:
        match = rule.get("match") or {}
        match_type = match.get("type", "exact")
        target = str(match.get("status") or "")
        if match_type == "exact":
            return status == target
        if match_type == "prefix":
            return status.startswith(target)
        if match_type == "contains":
            return target in status
        raise ValueError(
            f"unknown match type `{match_type}` in rule "
            f"`{rule.get('id', '')}`"
        )

    def resolve(self, status: str) -> Optional[dict]:
        value = str(status or "").strip()
        for rule in self.config["rules"]:
            if self.rule_matches(rule, value):
                return rule
        return None

    def initial(self) -> Tuple[str, str]:
        initial = self.config["initial"]
        return initial["status"], initial["next_stage"]

    def is_terminal(self, status: str) -> bool:
        return str(status or "").strip() in set(
            self.config["terminal_statuses"]
        )

    def execution_stage(self, status: str) -> Optional[str]:
        if self.is_terminal(status):
            return None
        rule = self.resolve(status)
        if rule is None:
            return None
        return str(rule["canonical_stage"])

    def terminal_statuses(self) -> Tuple[str, ...]:
        return tuple(self.config["terminal_statuses"])

    def paid_stage_markers(self) -> Tuple[str, ...]:
        return tuple(self.config.get("paid_stage_markers") or ())

    def progress(
        self,
        canonical: str = "",
        status: str = "",
        next_stage: str = "",
    ) -> Progress:
        canonical = str(canonical or "").strip()
        status = str(status or "").strip()
        next_stage = str(next_stage or "").strip()
        if canonical in INTERNAL_PROGRESS_STAGES:
            canonical = ""
        for progress in self.progress_stages:
            if (
                canonical in progress.canonical
                or status in progress.statuses
                or any(
                    status.startswith(prefix)
                    for prefix in progress.status_prefixes
                )
                or next_stage in progress.next_stages
            ):
                return progress
        return self.progress_stages[0]

    def _validate(self) -> None:
        if not isinstance(self.config.get("version"), int):
            raise ValueError(f"{self.path} lifecycle version must be an integer")
        rules = self.config.get("rules")
        if not isinstance(rules, list):
            raise ValueError(f"{self.path} must contain a `rules` list")
        terminal = self.config.get("terminal_statuses")
        if not isinstance(terminal, list) or not all(
            isinstance(value, str) and value.strip() for value in terminal
        ):
            raise ValueError(
                f"{self.path} terminal_statuses must be a string list"
            )
        initial = self.config.get("initial")
        if not isinstance(initial, dict):
            raise ValueError(f"{self.path} must contain an `initial` object")
        if not all(
            isinstance(initial.get(key), str) and initial[key].strip()
            for key in ("status", "next_stage")
        ):
            raise ValueError(
                f"{self.path} initial status and next_stage are required"
            )
        progress = self.config.get("progress")
        if not isinstance(progress, list) or len(progress) != 5:
            raise ValueError(
                f"{self.path} progress must contain exactly five stages"
            )
        if [item.get("index") for item in progress if isinstance(item, dict)] != [
            1,
            2,
            3,
            4,
            5,
        ]:
            raise ValueError(
                f"{self.path} progress indexes must be ordered 1 through 5"
            )
        for item in progress:
            if not isinstance(item, dict):
                raise ValueError(
                    f"{self.path} progress stages must be objects"
                )
            index = item["index"]
            if not all(
                isinstance(item.get(key), str) and item[key].strip()
                for key in ("label", "summary")
            ):
                raise ValueError(
                    f"{self.path} progress stage {index} needs label and summary"
                )
            for key in (
                "canonical",
                "statuses",
                "next_stages",
                "status_prefixes",
            ):
                values = item.get(key)
                if not isinstance(values, list) or not all(
                    isinstance(value, str) and value.strip()
                    for value in values
                ):
                    raise ValueError(
                        f"{self.path} progress stage {index} `{key}` "
                        "must be a string list"
                    )

        seen_ids = set()
        for rule in rules:
            if not isinstance(rule, dict):
                raise ValueError(f"{self.path} lifecycle rules must be objects")
            rule_id = str(rule.get("id") or "").strip()
            if not rule_id:
                raise ValueError(f"{self.path} lifecycle rule id is required")
            if rule_id in seen_ids:
                raise ValueError(f"{self.path} duplicate rule id `{rule_id}`")
            seen_ids.add(rule_id)
            match = rule.get("match")
            if not isinstance(match, dict):
                raise ValueError(f"{self.path} rule `{rule_id}` has no match")
            match_type = match.get("type", "exact")
            if match_type not in {"exact", "prefix", "contains"}:
                raise ValueError(
                    f"{self.path} rule `{rule_id}` has unknown match type "
                    f"`{match_type}`"
                )
            if not str(match.get("status") or "").strip():
                raise ValueError(
                    f"{self.path} rule `{rule_id}` has no match status"
                )
            if not str(rule.get("canonical_stage") or "").strip():
                raise ValueError(
                    f"{self.path} rule `{rule_id}` has no canonical_stage"
                )

        initial_rule = self.resolve(initial["status"])
        if initial_rule is None and not self.legacy_partial:
            raise ValueError(
                f"{self.path} initial status has no matching lifecycle rule"
            )
        if (
            not self.legacy_partial
            and initial_rule is not None
            and initial_rule.get("canonical_stage") != initial["next_stage"]
        ):
            raise ValueError(
                f"{self.path} initial next_stage disagrees with its rule"
            )
