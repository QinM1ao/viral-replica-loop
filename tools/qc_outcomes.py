#!/usr/bin/env python3
import re


RESULT_PASS = "PASS"
RESULT_FAIL = "FAIL"
RESULT_STOP = "STOP"

OUTCOME_PASS = "PASS"
OUTCOME_HARD_FAILURE = "HARD_FAILURE"
OUTCOME_VISUAL_WARNING = "VISUAL_WARNING"
OUTCOME_EVIDENCE_STOP = "EVIDENCE_STOP"
OUTCOME_PROVIDER_FAILURE = "PROVIDER_FAILURE"
OUTCOME_COST_GATE = "COST_GATE"
OUTCOME_HUMAN_REVIEW = "HUMAN_REVIEW"

OUTCOMES = {
    OUTCOME_PASS,
    OUTCOME_HARD_FAILURE,
    OUTCOME_VISUAL_WARNING,
    OUTCOME_EVIDENCE_STOP,
    OUTCOME_PROVIDER_FAILURE,
    OUTCOME_COST_GATE,
    OUTCOME_HUMAN_REVIEW,
}

OUTCOME_ALIASES = {
    "PASS": OUTCOME_PASS,
    "OK": OUTCOME_PASS,
    "HARD_FAILURE": OUTCOME_HARD_FAILURE,
    "HARD FAILURE": OUTCOME_HARD_FAILURE,
    "FAIL": OUTCOME_HARD_FAILURE,
    "FAILURE": OUTCOME_HARD_FAILURE,
    "VISUAL_WARNING": OUTCOME_VISUAL_WARNING,
    "VISUAL WARNING": OUTCOME_VISUAL_WARNING,
    "WARNING": OUTCOME_VISUAL_WARNING,
    "EVIDENCE_STOP": OUTCOME_EVIDENCE_STOP,
    "EVIDENCE STOP": OUTCOME_EVIDENCE_STOP,
    "STOP_EVIDENCE": OUTCOME_EVIDENCE_STOP,
    "PROVIDER_FAILURE": OUTCOME_PROVIDER_FAILURE,
    "PROVIDER FAILURE": OUTCOME_PROVIDER_FAILURE,
    "PROVIDER": OUTCOME_PROVIDER_FAILURE,
    "COST_GATE": OUTCOME_COST_GATE,
    "COST GATE": OUTCOME_COST_GATE,
    "COST": OUTCOME_COST_GATE,
    "HUMAN_REVIEW": OUTCOME_HUMAN_REVIEW,
    "HUMAN REVIEW": OUTCOME_HUMAN_REVIEW,
    "REVIEW": OUTCOME_HUMAN_REVIEW,
}

VISUAL_WARNING_FORBIDDEN_PATTERNS = [
    r"\bwrong\s+person\b",
    r"\bwrong\s+product\b",
    r"\bwrong\s+(?:product\s+)?brand\b",
    r"\bblank\s+(?:product\s+)?label\b",
    r"\bblank\s+(?:product\s+)?bottle\b",
    r"\blabel\s+(?:is\s+)?blank\b",
    r"\bsmooth(?:ed)?\s+(?:product\s+)?label\b",
    r"\bold[-\s]+source\s+label\b",
    r"\bold\s+source(?:'s)?\s+label\b",
    r"\b(?:wrong|incorrect)\s+label\s+design\b",
    r"\bmajor\s+(?:brand|product[-\s]+name)(?:\s+anchor)?\s+(?:is\s+)?(?:absent|missing|wrong)\b",
    r"\b(?:missing|wrong)\s+major\s+(?:brand|product[-\s]+name)(?:\s+anchor)?\b",
    r"\b(?:wrong|incorrect)\s+(?:bottle|package)\s+(?:shape|form)\b",
    r"\b(?:invented|unexpected|wrong)\s+(?:spray|mist)(?:\s+\w+){0,2}\s+(?:nozzle|hardware)\b",
    r"\bwrong\s+wardrobe\b",
    r"\bsource\s+contamination\b",
    r"\bchanged?\s+shot\s+order\b",
    r"\bshot\s+order\s+changed?\b",
    r"(?<!no\s)\bvisible\s+squeez",
    r"\bsqueezed?\s+(?:subject|person|model|body)\b",
    r"\bmissing\s+(?:output|saved output|candidate)\b",
    r"\bunsaved\s+(?:output|candidate|image)\b",
    r"\bthin\s+mud\b",
    r"\bwatery\s+mud\b",
    r"\bgray\s+mud\b",
    r"\byellow\s+mud\b",
    r"\bbeige\s+mud\b",
    r"\btan\s+mud\b",
    r"错人",
    r"错产品",
    r"错品牌",
    r"空白标签",
    r"空白瓶",
    r"抹平标签",
    r"旧产品标签",
    r"旧标签",
    r"标签设计.*(?:错|不符)",
    r"(?:主要品牌|产品名).*(?:缺失|错误|不对)",
    r"瓶型.*(?:错误|不对|不符)",
    r"(?:错误|多余|凭空|不应有).*(?:喷头|喷雾硬件)",
    r"出现.*不应有.*喷头",
    r"错服装",
    r"源污染",
    r"源视频污染",
    r"镜头顺序.*变",
    r"变.*镜头顺序",
    r"明显.*压",
    r"压扁",
    r"挤压",
    r"缺少.*输出",
    r"未保存",
    r"没保存",
    r"薄泥",
    r"水感",
    r"灰泥",
    r"黄泥",
    r"发黄",
    r"偏黄",
]

LABEL_WARNING_CONTEXT_PATTERNS = [
    r"\bproduct[_\s-]+label[_\s-]+microtext[_\s-]+only\b",
    r"\bmicro[_\s-]*text\b",
    r"\bcharacter[_\s-]+for[_\s-]+character\b",
    r"\b(?:tiny|small)\s+(?:label\s+)?text\b",
    r"标签.*(?:小字|微小字|细字|逐字)",
    r"(?:小字|微小字|细字|逐字).*(?:标签|文字)",
]

LABEL_WARNING_ALLOWED_FINDING_CODES = {
    "product_label_microtext_only",
}

EVIDENCE_STOP_PATTERNS = [
    r"missing\s+imagegen\s+input\s+proof",
    r"missing\s+(?:image\s+)?input\s+proof",
    r"missing\s+manifest\s+binding",
    r"active\s+hash\s+mismatch",
    r"missing\s+saved\s+candidate",
    r"missing\s+qc\s+artifact",
    r"missing\s+evidence",
    r"inconsistent\s+evidence",
    r"hash\s+mismatch",
    r"manifest\s+binding",
    r"codex_imagegen_contract",
    r"visual_asset_manifest",
    r"没有.*证据",
    r"缺少.*证据",
    r"缺少.*manifest",
    r"缺少.*候选",
    r"缺少.*QC",
    r"哈希.*不一致",
]

PROVIDER_FAILURE_PATTERNS = [
    r"\bprovider\b",
    r"\bapi\b",
    r"\btimeout\b",
    r"\b524\b",
    r"\b5\d\d\b",
    r"\bgateway\b",
    r"接口",
    r"网关",
    r"超时",
]

COST_GATE_PATTERNS = [
    r"\bcost\b",
    r"\bpaid\b",
    r"\bapproval\b",
    r"\bgeneration approval\b",
    r"付费",
    r"成本",
    r"审批",
    r"批准",
]


def normalize_outcome(value):
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    normalized = re.sub(r"[-/]+", " ", text).upper()
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return OUTCOME_ALIASES.get(normalized) or OUTCOME_ALIASES.get(normalized.replace(" ", "_"))


def outcome_for_result(result, outcome_value="", text="", cost_gate=False):
    explicit = normalize_outcome(outcome_value)
    if explicit:
        return explicit

    result = str(result or "").strip().upper()
    haystack = text or ""
    if result == RESULT_PASS:
        return OUTCOME_PASS
    if result == RESULT_FAIL:
        return OUTCOME_PROVIDER_FAILURE if has_any(PROVIDER_FAILURE_PATTERNS, haystack) else OUTCOME_HARD_FAILURE
    if result == RESULT_STOP:
        if cost_gate or has_any(COST_GATE_PATTERNS, haystack):
            return OUTCOME_COST_GATE
        if has_any(PROVIDER_FAILURE_PATTERNS, haystack):
            return OUTCOME_PROVIDER_FAILURE
        if has_any(EVIDENCE_STOP_PATTERNS, haystack):
            return OUTCOME_EVIDENCE_STOP
        return OUTCOME_HUMAN_REVIEW
    return None


def blocker_category(outcome):
    outcome = normalize_outcome(outcome) or outcome
    if outcome == OUTCOME_HARD_FAILURE:
        return "visual_failure"
    if outcome == OUTCOME_VISUAL_WARNING:
        return "visual_warning"
    if outcome == OUTCOME_EVIDENCE_STOP:
        return "evidence_failure"
    if outcome == OUTCOME_PROVIDER_FAILURE:
        return "provider_failure"
    if outcome == OUTCOME_COST_GATE:
        return "cost_gate"
    if outcome == OUTCOME_HUMAN_REVIEW:
        return "human_review"
    return "none"


def has_any(patterns, text):
    return any(re.search(pattern, text or "", flags=re.IGNORECASE) for pattern in patterns)


def visual_warning_forbidden_hits(text):
    hits = []
    for pattern in VISUAL_WARNING_FORBIDDEN_PATTERNS:
        if re.search(pattern, text or "", flags=re.IGNORECASE):
            hits.append(pattern)
    return hits


def validate_outcome(result, outcome, why_not_fail="", text="", finding_code=""):
    checks = []
    result = str(result or "").strip().upper()
    outcome = normalize_outcome(outcome) or outcome_for_result(result, text=text)

    if outcome not in OUTCOMES:
        checks.append(("outcome_type_value", "FAIL", f"outcome={outcome!r}"))
        return outcome, checks

    checks.append(("outcome_type_value", "PASS", f"outcome={outcome}"))

    if outcome == OUTCOME_VISUAL_WARNING:
        checks.append((
            "visual_warning_result_pass",
            "PASS" if result == RESULT_PASS else "FAIL",
            f"result={result}",
        ))
        checks.append((
            "visual_warning_has_why_not_fail",
            "PASS" if str(why_not_fail or "").strip() else "FAIL",
            why_not_fail or "",
        ))
        hits = visual_warning_forbidden_hits(text)
        checks.append((
            "visual_warning_no_hard_failure_red_flags",
            "PASS" if not hits else "FAIL",
            f"red_flags={hits}",
        ))
        if has_any(LABEL_WARNING_CONTEXT_PATTERNS, text):
            normalized_code = re.sub(
                r"[^a-z0-9]+",
                "_",
                str(finding_code or "").strip().lower(),
            ).strip("_")
            checks.append((
                "visual_warning_label_finding_code",
                (
                    "PASS"
                    if normalized_code in LABEL_WARNING_ALLOWED_FINDING_CODES
                    else "FAIL"
                ),
                f"finding_code={normalized_code or 'missing'}",
            ))
    elif outcome == OUTCOME_HARD_FAILURE:
        checks.append((
            "hard_failure_result_fail",
            "PASS" if result == RESULT_FAIL else "FAIL",
            f"result={result}",
        ))
    elif outcome == OUTCOME_EVIDENCE_STOP:
        checks.append((
            "evidence_stop_result_stop",
            "PASS" if result == RESULT_STOP else "FAIL",
            f"result={result}",
        ))
    elif outcome == OUTCOME_COST_GATE:
        checks.append((
            "cost_gate_result_stop",
            "PASS" if result == RESULT_STOP else "FAIL",
            f"result={result}",
        ))
    elif outcome == OUTCOME_PROVIDER_FAILURE:
        checks.append((
            "provider_failure_result_non_pass",
            "PASS" if result in {RESULT_FAIL, RESULT_STOP} else "FAIL",
            f"result={result}",
        ))
    return outcome, checks
