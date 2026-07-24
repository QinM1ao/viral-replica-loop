#!/usr/bin/env python3
import argparse
import json
import re
from pathlib import Path

from qc_input_binding import attach_input_binding
from seedance_request_contract import inspect_taskcode_request
from urllib.parse import urlparse


URL_RE = re.compile(r"https?://[^\s\"'<>，。)）]+")
LOCAL_PATH_RE = re.compile(r"(^/Users/|^/var/|^/tmp/|^[A-Za-z]:\\|\\.png$|\\.jpg$|\\.jpeg$|\\.mp4$|\\.wav$|\\.mp3$)")


def is_model_field(path):
    normalized = re.sub(r"[^a-z0-9]", "", path.lower())
    return normalized.endswith((
        "model",
        "modelep",
        "modelendpoint",
        "modelendpointid",
        "modelid",
        "ep",
    ))


def walk(value, path="$"):
    if isinstance(value, dict):
        for key, child in value.items():
            yield from walk(child, f"{path}.{key}")
    elif isinstance(value, list):
        for idx, child in enumerate(value):
            yield from walk(child, f"{path}[{idx}]")
    else:
        yield path, value


def load_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"__load_error__": str(exc)}


def read_model_route_config(path):
    if not path:
        return {}
    data = load_json(Path(path))
    if "__load_error__" in data:
        raise SystemExit(f"Could not read model route config {path}: {data['__load_error__']}")
    return data


def collect_values(data):
    urls = []
    asset_refs = []
    local_paths = []
    task_codes = []
    model_refs = []
    prompt_like = []
    endpoint_like = []

    def record_string(path, text):
        for url in URL_RE.findall(text):
            urls.append((path, url))
        if "asset://" in text:
            asset_refs.append((path, text))
        if LOCAL_PATH_RE.search(text):
            local_paths.append((path, text))
        if path.lower().endswith(("taskcode", "task_code")):
            task_codes.append((path, text))
        if any(k in path.lower() for k in ("prompt", "script", "text")) and len(text) > 20:
            prompt_like.append((path, text))
        if is_model_field(path):
            model_refs.append((path, text))
        if any(k in path.lower() for k in ("url", "path", "endpoint", "api")):
            endpoint_like.append((path, text))

    visited_json_strings = set()

    def collect_from(value, base_path="$"):
        for path, child in walk(value):
            full_path = path if base_path == "$" else f"{base_path}{path[1:]}"
            if isinstance(child, (int, float)) and full_path.lower().endswith(("taskcode", "task_code")):
                task_codes.append((full_path, str(child)))
            if not isinstance(child, str):
                continue

            text = child.strip()
            if not text:
                continue
            record_string(full_path, text)

            if text[0] not in "{[" or text in visited_json_strings:
                continue
            visited_json_strings.add(text)
            try:
                parsed = json.loads(text)
            except Exception:
                continue
            collect_from(parsed, f"{full_path}<json>")

    collect_from(data)

    return {
        "urls": urls,
        "asset_refs": asset_refs,
        "local_paths": local_paths,
        "task_codes": task_codes,
        "model_refs": model_refs,
        "prompt_like": prompt_like,
        "endpoint_like": endpoint_like,
    }

def is_http_url(value):
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def check_request(path, data, args):
    checks = []
    if "__load_error__" in data:
        return {
            "path": str(path),
            "overall": "STOP",
            "checks": [{
                "name": "json_parse",
                "status": "STOP",
                "detail": data["__load_error__"],
            }],
            "metrics": {},
        }

    values = collect_values(data)
    task_codes = [code for _, code in values["task_codes"]]
    urls = values["urls"]
    bad_urls = [(p, u) for p, u in urls if not is_http_url(u)]

    checks.append({
        "name": "json_parse",
        "status": "PASS",
        "detail": "request body is valid JSON",
    })

    contract = inspect_taskcode_request(data)
    checks.extend(contract["checks"])
    contract_metrics = contract["metrics"]

    if args.allowed_task_codes:
        allowed = set(args.allowed_task_codes)
        ok = bool(task_codes) and all(code in allowed for code in task_codes)
        checks.append({
            "name": "task_code",
            "status": "PASS" if ok else "FAIL",
            "detail": f"found={task_codes}, allowed={sorted(allowed)}",
        })
    else:
        checks.append({
            "name": "task_code_present",
            "status": "PASS" if task_codes else "FAIL",
            "detail": f"found={task_codes}",
        })

    if args.expected_endpoint:
        body_text = json.dumps(data, ensure_ascii=False)
        ok = args.expected_endpoint in body_text
        checks.append({
            "name": "endpoint",
            "status": "PASS" if ok else "FAIL",
            "detail": f"expected substring `{args.expected_endpoint}`",
        })

    if args.expected_model_ep:
        model_values = [text for _, text in values["model_refs"]]
        ok = args.expected_model_ep in model_values
        checks.append({
            "name": "model_ep",
            "status": "PASS" if ok else "FAIL",
            "detail": f"found={values['model_refs'][:5]}, expected=`{args.expected_model_ep}`",
        })

    if args.require_public_urls:
        ok = bool(urls) and not bad_urls and not values["local_paths"]
        checks.append({
            "name": "public_urls",
            "status": "PASS" if ok else "FAIL",
            "detail": f"http_urls={len(urls)}, bad_urls={bad_urls}, local_paths={values['local_paths'][:5]}",
        })

    if args.forbid_asset_refs:
        checks.append({
            "name": "no_asset_refs",
            "status": "PASS" if not values["asset_refs"] else "FAIL",
            "detail": f"asset_refs={values['asset_refs'][:5]}",
        })
    else:
        checks.append({
            "name": "asset_refs_allowed",
            "status": "PASS",
            "detail": f"asset_refs={values['asset_refs'][:5]}",
        })

    checks.append({
        "name": "prompt_text_present",
        "status": "PASS" if values["prompt_like"] else "FAIL",
        "detail": f"prompt_like_fields={[p for p, _ in values['prompt_like'][:5]]}",
    })

    body_text = json.dumps(data, ensure_ascii=False)
    declared_prompt_files = [
        text
        for path, text in values["prompt_like"]
        if path.lower().endswith("prompt_file")
    ]
    for prompt_file in args.prompt_files:
        prompt_file_text = str(prompt_file)
        if declared_prompt_files and prompt_file_text not in declared_prompt_files:
            continue
        prompt_text = Path(prompt_file).read_text(encoding="utf-8").strip()
        prompt_values = [text.strip() for _, text in values["prompt_like"]]
        ok = bool(prompt_text) and (
            prompt_text in prompt_values
            or any(prompt_text in value for value in prompt_values)
            or prompt_text in body_text
        )
        checks.append({
            "name": f"prompt_matches:{Path(prompt_file).name}",
            "status": "PASS" if ok else "FAIL",
            "detail": "prompt file text is embedded in request body" if ok else "prompt file text not found exactly",
        })

    status_order = {"PASS": 0, "FAIL": 1, "STOP": 2}
    overall = max((c["status"] for c in checks), key=lambda s: status_order[s])
    return {
        "path": str(path),
        "overall": overall,
        "checks": checks,
        "metrics": {
            "url_count": len(urls),
            "task_codes": task_codes,
            "asset_ref_count": len(values["asset_refs"]),
            "local_path_count": len(values["local_paths"]),
            "model_refs": values["model_refs"],
            "provider_duration": contract_metrics["duration"],
            "image_count": contract_metrics["image_count"],
            "image_refs": contract_metrics["image_refs"],
            "audio_count": contract_metrics["audio_count"],
            "audio_refs": contract_metrics["audio_refs"],
        },
    }


def write_md(path, report):
    lines = [
        "# Request Body QC",
        "",
        f"- Overall: **{report['overall']}**",
        "",
        "## Requests",
        "",
    ]
    for item in report["requests"]:
        lines.append(f"### `{item['path']}`")
        lines.append("")
        lines.append(f"- Overall: **{item['overall']}**")
        for check in item["checks"]:
            lines.append(f"- {check['status']}: `{check['name']}` - {check['detail']}")
        lines.append("")
    lines.extend([
        "## Metrics",
        "",
        "```json",
        json.dumps(report["metrics"], ensure_ascii=False, indent=2),
        "```",
        "",
    ])
    Path(path).write_text("\n".join(lines), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="QC Seedance request body JSON files.")
    parser.add_argument("--requests", nargs="+", type=Path, required=True)
    parser.add_argument("--prompt-files", nargs="*", type=Path, default=[])
    parser.add_argument("--out-json", type=Path, required=True)
    parser.add_argument("--out-md", type=Path, required=True)
    parser.add_argument("--expected-endpoint", default="")
    parser.add_argument("--expected-model-ep", default="")
    parser.add_argument("--model-route-config", type=Path, default=None)
    parser.add_argument("--allowed-task-codes", nargs="*", default=[])
    parser.add_argument("--require-public-urls", action="store_true")
    asset_group = parser.add_mutually_exclusive_group()
    asset_group.add_argument("--forbid-asset-refs", dest="forbid_asset_refs", action="store_true")
    asset_group.add_argument("--allow-asset-refs", dest="forbid_asset_refs", action="store_false")
    parser.set_defaults(forbid_asset_refs=True)
    args = parser.parse_args()
    model_config = read_model_route_config(args.model_route_config)
    if model_config and not args.expected_model_ep:
        args.expected_model_ep = model_config.get("model", "")

    request_reports = []
    for request_path in args.requests:
        request_reports.append(check_request(request_path, load_json(request_path), args))

    status_order = {"PASS": 0, "FAIL": 1, "STOP": 2}
    overall = max((r["overall"] for r in request_reports), key=lambda s: status_order[s])
    report = {
        "overall": overall,
        "requests": request_reports,
        "metrics": {
            "request_count": len(request_reports),
            "prompt_file_count": len(args.prompt_files),
        },
    }
    attach_input_binding(
        report,
        Path.cwd(),
        [*args.requests, *args.prompt_files, args.model_route_config],
    )

    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_md.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_md(args.out_md, report)
    print(overall)


if __name__ == "__main__":
    main()
