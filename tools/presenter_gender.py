"""Presenter-gender contract shared by pre-Seedance rendering and prompt QC."""

VALID_GENDERS = {"male", "female"}
PRESENTER_TERMS = {
    "male": ("男主", "男主播", "男主持", "男声", "male host", "male presenter"),
    "female": ("女主", "女主播", "女主持", "女声", "female host", "female presenter"),
}


def presenter_gender_pair(value):
    value = value if isinstance(value, dict) else {}
    return str(value.get("source", "")).strip().lower(), str(value.get("target", "")).strip().lower()


def validate_presenter_gender_pair(value):
    source, target = presenter_gender_pair(value)
    if source not in VALID_GENDERS or target not in VALID_GENDERS:
        raise ValueError("presenter_gender source and target must be male or female")
    if source != target:
        raise ValueError("source and target presenter gender must match")
    return target


def presenter_gender_text_issues(text, target_gender):
    if target_gender not in VALID_GENDERS:
        return ["missing valid target presenter gender"]
    expected_terms = PRESENTER_TERMS[target_gender]
    opposite_gender = "female" if target_gender == "male" else "male"
    opposite_hits = sorted({term for term in PRESENTER_TERMS[opposite_gender] if term in text})
    issues = []
    if not any(term in text for term in expected_terms):
        issues.append(f"missing {target_gender} presenter term")
    if opposite_hits:
        issues.append("opposite presenter gender terms: " + ", ".join(opposite_hits))
    return issues
