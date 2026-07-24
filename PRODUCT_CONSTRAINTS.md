# Product Constraints

Fill this file for each client product before running image or video generation.

Product-specific rules must be loaded through `output/<job-id>/product_profile.json`.
The generic product contract always applies. Category, brand, and SKU rules only
apply when the job product profile explicitly loads them. A brand name alone must
not imply category material, action, after-wash, or model-identity rules.

## Template

```text
## <Product Name>

Applies when `jobs.csv product_name` is `<Product Name>`.

- Product form:
- Required packaging/label details:
- Required texture/material:
- Required usage action:
- Allowed supporting props:
- Banned invented props:
- Banned old-source contamination:
- Product reference priority:
- Seedance reference rule:
```

## Example: Skincare Clay Mask

- Product jar, label, lid, open paste, and usage action must follow the client product assets.
- Do not invent boxes, bags, instruction cards, or gift packaging unless they exist in the product assets.
- Face application must use the product's real usage action, such as finger pickup and finger application for jar clay mask products.
- If the old source video uses gray mud, tube applicators, arm swatches, or watery paste, those details are contamination and must not become product texture references.
- Open paste and on-face paste must keep the approved product color and thickness.
- Cross-part skin tone must remain consistent. After-use improvement should look cleaner and more refined, not like a different person or light source.
- Product front and open-texture references should be split when they serve different roles.
- Codex ImageGen runs should prove actual image references were attached/loaded; source storyboards should transfer action/layout only, not old product/tools/materials.

## 孔凤春发酵水

Applies when `jobs.csv product_name` is `孔凤春发酵水` or contains `发酵水`.

Hard product rules:

- Product form: pale translucent/yellowish essence toner bottle, light cap, green `孔凤春` label text.
- Required label details: designated hero close-ups must preserve the major `孔凤春` brand and product-name identity plus the real label's overall design. The English line, `52%马齿苋发酵精华`, `屏障修护`, `敏肌适用`, and other microtext are generation targets, but distant, oblique, multi-bottle, and storyboard-scale versions do not need character-for-character reproduction; matching color, line layout, and brand impression is sufficient. Microtext variation alone is a visual warning, not a hard failure. A wrong product/brand, wrong label design, old-source label, blank or smoothed label, or clearly wrong/missing major hero-label anchor remains a hard fail.
- Required usage action: pour or dispense watery toner into palm/back of hand, pat/press onto face, or wet toner application.
- Banned invented props: unknown packaging box, gift box, paper box, instruction box, random blank bottle, spray nozzle not present in provided assets.
- Banned old-source contamination: `谷雨` bottle, amber/brown source bottle, solid collagen spray/mist hardware, `人参皂苷CK`, `胶原肽`, old source host face, burned-in subtitles.
- Product reference priority: closed/front bottle ref first; no-cap/open-mouth bottle ref second; other angles only support geometry.
- Seedance reference rule: source storyboard transfers only shot order/framing/action rhythm; product refs control bottle/label/liquid; identity ref controls only the female target host.
- Character role rule for `相亲相到小学同学`: the female lead/product host is replaced by the approved female model; the opening male date counterpart remains a male supporting role and may be replaced by any generic/de-identified male, but must not become the approved female model.
## 孔凤春清洁泥膜

Applies only when `output/<job-id>/product_profile.json` loads
`category:clay_mask` or `sku:kongfengchun_clean_mud_mask`.

Read first:

- `client-profiles/kongfengchun/README.md`
- `client-profiles/kongfengchun/product-profile.md`
- `client-profiles/kongfengchun/passed-standards.md`
- `client-profiles/kongfengchun/failed-cases.md`
- `client-profiles/kongfengchun/loop-overrides.md`

Hard product rules:

- Product form: white square-round jar, white cap, green leaf/flower mark.
- Required references: split product front and open white-mud references when possible.
- Required texture: milky white, thick clay mask, visible paste body and small lifted peaks.
- Required usage action: finger pickup from jar and fingertip face application.
- Banned invented props: unknown packaging box, gift box, paper box, instruction box, random white jar.
- Banned old-source contamination: yellow mud, beige mud, tan/skin-toned mud, gray mud, watery mud, tube applicator, stick applicator, brush head, arm swatch, old source host face.
- Codex ImageGen contract rule: source tube/stick/brush/arm-swatch beats must be translated to finger pickup from the open jar and fingertip application before generation; `codex_imagegen_contract_qc.py` must pass before image-stage PASS.
- Person rule: one male model only unless the user explicitly asks otherwise.
- Cross-part rule: Part1 and Part2 skin tone, exposure, wardrobe, and mud texture must be compared before video generation.
- After-wash rule: improved skin reference must be generated as a dedicated face close-up from the approved identity and may be used only after the wash is completed.
- Seedance rule: spoken product name must be wrapped in Chinese quotation marks and land on the product close-up shot.
