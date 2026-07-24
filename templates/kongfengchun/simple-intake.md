# 孔凤春新任务输入模板

以后在 Codex 里直接说这段就行：

```text
我要跑孔凤春专用 Loop。

视频目录：
产品名：孔凤春清洁泥膜
产品图路径：
人物/主播图路径：
声音参考：直接用原爆款视频提取
目标时长：30秒
备注：基本全复刻，场景和节奏按原视频，只换孔凤春产品和指定人物；不要灰泥、不要陌生包装、不要双男模。
```

Codex 应自动执行：

```bash
python3 scripts/new-task.py \
  --root . \
  --video-dir "<视频目录>" \
  --product-name "孔凤春清洁泥膜" \
  --product-assets "<产品图路径>" \
  --person-assets "<人物/主播图路径>" \
  --audio-assets "extract_from_original" \
  --target-duration "30s" \
  --notes "<备注>"
./run-loop.sh
```

不需要用户说 `BRIEF.md`、`jobs.csv`、`client_profile`。
