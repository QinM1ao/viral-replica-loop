# Checker Review QC

- Overall: **PASS**
- Review result: `PASS`
- Outcome type: `PASS`
- Blocker category: `none`
- Structure status: `PASS`

## Checks

- PASS: `required_fields` - missing=[]
- PASS: `result_value` - result='PASS'
- PASS: `outcome_type_value` - outcome=PASS
- PASS: `gate_file_exists` - gates/pre_seedance_pack_gate.md
- PASS: `pass_has_reason` - job-008 is ready to stop at Pre-Seedance handoff before video generation.

## Fields

```json
{
  "Gate": "gates/pre_seedance_pack_gate.md",
  "Job": "job-008",
  "Stage": "pre_seedance_pack",
  "Input artifacts": "output/job-008/voiceover/voiceover.md; output/job-008/voiceover/shot_line_map.md; output/job-008/seam/seam_design.md; output/job-008/seedance/seedance_素材角色表.md; output/job-008/seedance/seedance_part1_prompt.txt; output/job-008/seedance/seedance_part2_prompt.txt; output/job-008/audio-boundary/audio_boundary_qc.md; output/job-008/seedance/requests/part1_request_prepared.json; output/job-008/seedance/requests/part2_request_prepared.json; output/job-008/seedance_web_final; output/job-008/checks/pre_seedance_pack_seedance_prompt_contract_qc.json; output/job-008/seedance/requests/request_qc.json; output/job-008/seedance/requests/final_upload_audio_duration_qc.json; output/job-008/checks/pre_seedance_pack_visual_asset_manifest_qc.json",
  "Checks": "PASS - voiceover, shot-line map, seam notes, material role table, two Seedance 2.0 prompts, two prepared request JSON files, two <=15s reference audio files, and web-side handoff directory are complete; prompt contract QC PASS; request body QC PASS; final upload audio duration QC PASS; visual asset manifest QC with final upload directory PASS; paid Seedance generation was not submitted.",
  "Result": "PASS",
  "Reason": "job-008 is ready to stop at Pre-Seedance handoff before video generation.",
  "Failed item": "N/A",
  "Failure type": "N/A",
  "Retry variable": "N/A",
  "Locked variables": "passed story analysis; approved images; product profile; visual manifest; image batch QC reports; active web-side handoff directory output/job-008/seedance_web_final",
  "Next status": "seedance_inputs_prepared",
  "Needs user confirmation": "no",
  "Outcome type": "PASS",
  "Why not fail": "Required Pre-Seedance files and QC reports exist for both Parts, prompts cover every shot-line map target-time row inside Shot 1/2/3 groups, request bodies use the configured SD 2.0 mini model EP, and the final handoff directory contains only active upload assets."
}
```
