# 抖音短视频 BGM / 节奏音效：曲库、授权边界与独立 Skill 方向

研究日期：2026-07-21
适用范围：中国大陆、品牌/商品短视频、最终成片需要在本地自动渲染并交付 MP4。
说明：这是依据公开的一手产品页、帮助中心、许可条款和 API 文档做的工程选型，不是法律意见。每次正式商用仍应以购买/下载当日的具体曲目授权和项目投放范围为准。

## 结论

应该做成独立 Skill，而且不能只是“给视频随便配一首歌”。推荐名称暂定为 `source-faithful-soundtrack`，由最终剪辑 Skill 在字幕完成后调用。

它有三项与字幕完全不同的职责：

1. 从原视频理解声音语法：BPM、能量起伏、卡点位置、段落转换、每个节奏音效承担的作用；不能照搬原视频的秒点，也不能从原视频剥离音乐复用。
2. 从有明确商用授权的现成曲库检索并下载真实 BGM / SFX，保存许可证据；不生成音乐，也不从抖音、剪映或别人的视频抓音频。
3. 把新曲目的节拍和音效事件语义重映射到生成成片的实际动作、字幕强调和剪切点，再完成 ducking、响度和峰值 QC。

对当前项目最实用的曲库组合是：

- **中国大陆商用主库：VFine Music。** 它公开提供短视频场景、BGM 与音效、音乐查找和下载 API、15/30/60 秒片段、细粒度波形 JSON，并能生成项目授权书，最贴近我们的“Agent 检索 → 下载文件 → 本地混音 → 留证”闭环。
- **自动化能力最强的备选/国际主库：Epidemic Sound Partner API。** 它公开支持音乐与 SFX 搜索、下载、BPM、waveform、beat timing、stems、相似音频/参考音频/视频匹配、目标时长改版和官方 MCP，但生产使用需要取得相应 API/合作及商业许可。
- **低成本试听与 MVP 兜底：Pixabay（BGM/SFX）+ Freesound（SFX 为主）。** 两者都必须逐条保留许可；Pixabay 需要规避或留证处理 Content ID 曲目，Freesound 只能自动接受 CC0 或满足署名条件的 CC BY，必须排除 CC BY-NC。

抖音、巨量创意、剪映/CapCut 的官方曲库应该用来**发现抖音声音趋势或在平台内完成发布**，不应默认当成可抽出音频文件供本地 HyperFrames/FFmpeg 渲染的素材仓库。公开许可和接口没有给出这种权利。

## 最关键的区分

| 渠道 | 平台内配乐/发布 | 可下载独立音频用于本地渲染 | 商业短视频 | 自动化可行性 | 本项目定位 |
|---|---:|---:|---:|---:|---|
| 巨量创意 / 音乐商店 / 即创 | 是 | 未见公开授权与当前公开下载 API | 限巨量生态和具体素材授权 | 低 | 趋势发现、站内投放备选 |
| 剪映 / CapCut Commercial Sounds | 是 | 否，不可抽取或平台外再编辑 | 仅明确许可的平台 | 低 | 站内编辑，不作为本地资产源 |
| TikTok CML | 是 | 未见面向普通开发者的文件下载 API | TikTok 商业内容 | 低 | 国际 TikTok 发布，不等于中国抖音授权 |
| VFine Music | 是 | 是 | 是，按项目/用途授权 | 高 | 大陆 MVP 首选 |
| TME 曲易买 | 是 | 商务授权后按产品方案 | 是 | 中至高 | 国内知名曲库和企业方案备选 |
| Epidemic Sound | 是 | 是 | 是，需正确商业方案/合作 | 很高 | 自动化能力首选 |
| Soundstripe | 是 | 是 | 是，需正确商业/企业覆盖 | 很高但偏企业 | 第二 API 供应商 |
| Adobe Stock Audio | 是 | 是 | 标准许可覆盖社交和数字广告 | 中 | 单曲/Adobe 工作流备选 |
| Artlist | 是 | 是 | Pro/Business 覆盖客户项目 | 人工高、Agent 低 | 仅人工选曲 |
| Envato Elements | 是 | 是 | 一项目一许可 | 人工中、Agent 低 | 低频人工备选 |
| Pixabay | 是 | 是 | 允许，但风险由用户承担 | 中 | 免费 MVP 兜底 |
| Freesound | 是 | 是 | 取决于每条 CC 许可 | 高，但许可需严筛 | 免费 SFX 兜底 |
| YouTube Audio Library | 是 | 是 | 官方明确的是 YouTube 视频场景 | 低 | 不用于抖音交付 |

## 一、抖音、巨量创意、即创、剪映能提供什么

### 1. 巨量创意和音乐商店：有官方授权曲库，但优先理解为巨量生态内能力

巨量引擎当前“智能平台”页面把“巨量创意”描述为拥有“海量授权 BGM”，并单列“音乐商店”，称其提供广泛音乐版权资源、覆盖各类抖音热歌榜单。它适合判断当前抖音广告音乐方向和做站内素材。[巨量引擎智能平台](https://www.oceanengine.com/platform)

但巨量创意平台服务协议明确：用户可以下载平台制作的视频，但受原始权利人授权限制，使用平台制作的视频只能在巨量引擎网络平台客户端/网站范围内投放。它没有授予我们把曲库里的音乐单独抽出，再放进自己的本地渲染系统中反复加工的权利。[巨量创意平台服务协议](https://lf3-cdn-tos.draftstatic.com/obj/ies-hotsoon-draft/aic_platform/1efd0924-cdad-4ae7-9d85-373dc660c514.html)

巨量引擎在 2020 年曾公开 Marketing API 的“相似音乐推荐”，可按语言、心情、曲风、乐器等维度推荐相似音乐。但这是历史公告，当前公开产品页没有证明该接口仍按同样方式对外开放，因此只能作为能力线索，不能写进 MVP 的硬依赖。[2020 年巨量引擎 Marketing API 公告](https://www.oceanengine.com/news/production/429)

工程判断：

- 可把巨量音乐商店作为**趋势和候选名称来源**，或者为“只在巨量生态发布”的成片提供站内选曲方案。
- 不把它作为 `bgm.wav` / `sfx.wav` 的本地文件来源，除非后续拿到逐曲授权、合作接口和明确允许本地下载/再编辑的书面条款。
- 当前抖音开放平台公开的内容发布 API 是上传已经完成的 MP4，不是音乐曲库搜索和下载 API。[抖音内容发布接入方案](https://open.douyin.com/platform/resource/docs/ability/content-management/douyin-publish-solution)

### 2. 即创：可以做巨量体系内的成片，但不等于开放音频素材仓库

即创属于巨量引擎创意制作工具。它的官方协议同样将平台产物绑定到巨量引擎网络平台范围。因此它可以作为“平台内生成/投放”的路径，却不是我们的本地音频资产供应商。[巨量创意平台服务协议](https://lf3-cdn-tos.draftstatic.com/obj/ies-hotsoon-draft/aic_platform/1efd0924-cdad-4ae7-9d85-373dc660c514.html)

### 3. 剪映：AI 音效能力值得参考，但素材许可不支持抽取复用

剪映官网目前公开“AI 音效”，即智能理解视频并匹配音效；这证明“先理解画面动作，再放置音效事件”是平台认可的产品方向。[剪映官网 AI 音效](https://www.capcut.cn/)

但是公开的 CapCut Materials License 给出了非常明确的边界：

- Commercial Sounds 只明确许可在 CapCut、TikTok 和 TikTok for Business 展示/分享；平台之外需要另行取得权利。
- 平台素材和音乐不得在平台外修改，不得单独分发，也不得让第三方提取、下载或复用。
- 平台素材只允许在平台内编辑；导出后只能作为成片的一部分展示。

来源：[CapCut Materials License Agreement](https://www.capcut.com/clause/material-license-agreement?lang=en)

这份公开条款是 CapCut 的国际条款，不替代中国大陆剪映每个具体素材的当前授权标识；但它足以说明工程上不能默认把剪映/CapCut 缓存或导出文件当作我们自己的音效库。中国大陆剪映若后续提供单独商用授权，应逐素材核实并保存当日许可。

### 4. TikTok Commercial Music Library：TikTok 商业发布很好用，但不是抖音本地渲染曲库

TikTok CML 是面向企业的预清权曲库，可按地区、投放位置、主题、曲风、情绪和时长搜索，选定后可用于 TikTok 自然商业内容或广告。[TikTok CML 使用说明](https://ads.tiktok.com/help/article/how-to-use-the-commercial-music-library)

TikTok 也明确：推广品牌、产品或服务时，应使用 CML；若使用 CML 外的音乐，发布者必须确认自己已经获得并支付所有必要授权。[TikTok 商业音乐使用说明](https://support.tiktok.com/en/business-and-creator/creator-and-business-accounts/commercial-use-of-music-on-tiktok)

但是：

- 授权围绕 TikTok 内容和地区可用性，不等于中国大陆抖音授权。
- 官方公开访问方式是 TikTok App 的 Commercial Sounds 和 Creative Center；没有面向普通开发者、用于下载独立音乐文件并在本地渲染的公开 API 说明。
- TikTok 自己的官方合法性材料称 CML 音乐“licensed for use on TikTok only”。[TikTok Music Legality](https://ads.tiktok.com/business/library/TikTok_Music_Legality.pdf)

因此 CML 只适合国际 TikTok 分发分支，不是当前抖音本地成片的首选素材源。

## 二、适合直接取得文件并用于本地渲染的曲库

### A. VFine Music：大陆 MVP 首选

VFine 的公开企业服务页直接覆盖当前需求：

- 百万级曲库，包含流行音乐、纯音乐和音效；适用短视频。
- API 支持音乐查找和音乐下载。
- 提供 15 秒、30 秒、60 秒版本。
- 提供每秒 500 个采样点的波形 JSON，可辅助自动卡点和段落分析。
- 可在线搜索/试听、下载试听文件、按用途购买并激活音乐授权书。

来源：[VFine 开放能力](https://www.vfinemusic.com/access)、[VFine 商用授权流程](https://www.vfinemusic.com/brand-publicity)

VFine 公开授权书样例包含被授权主体、项目、用途、作品名/ID、版权所有者、授权代码、期限、地域和投放渠道，适合直接落进我们的版权证据包。[VFine 音乐授权书样例](https://pro-api.vfinemusic.com/web/musiclic/view?license_id=7d016528b7b9d37f001)

自动化评价：**高**。它最接近中国大陆项目真正需要的 API、下载、短版本和项目级证书。但 API 的生产接入、价格、具体投放平台和音效是否逐条同权，仍需和 VFine 商务按账户确认。

### B. 腾讯音乐：曲易买适合采购，TME 音乐云适合企业自动化

腾讯音乐官方业务页将“曲易买”定义为商用音乐授权平台，能够满足商业广告、影视、游戏、综艺、动漫和短视频等场景；“TME 音乐云”提供云端曲库、高自动化和高定制服务，客户不用自建曲库即可获得定制音乐内容和歌单。[TME 核心业务](https://www.tencentmusic.com/zh-cn/business.html)

腾讯云的“正版曲库直通车 AME”官方文档也描述了基于 TME 背景音乐曲库的 PaaS，通过 API 调用播放和应用正版 BGM。[腾讯云正版曲库直通车](https://cloud.tencent.com/document/product/629/96599)

自动化评价：

- 曲易买：**人工采购友好**，适合想使用更熟悉的华语/流行资产时逐项目授权。
- TME 音乐云/企业方案：**可自动化**，但更像商务合作，不应假设注册后即可获得任意曲目的本地下载和任意平台同步权。
- 任何流媒体会员、QQ 音乐/酷狗普通下载都不是商用同步授权，绝不能拿来当项目素材。

### C. Epidemic Sound：自动化能力最完整

Epidemic 的官方 Partner API 是目前最适合 Agent 的海外曲库能力：

- 音乐可按关键词、类型、情绪、BPM、是否有人声等搜索，并下载文件。
- SFX 可搜索、分类浏览和下载。
- 提供 waveform、beat timing、stems；有目标时长改版、相似音乐、参考音频搜索和视频匹配。
- 官方提供“用 LLM 自动配乐”的端到端指南和 Beta MCP Server；MCP 能检索音乐/SFX、下载 MP3/WAV 和 stems。

来源：[Epidemic API 指南](https://developers.epidemicsound.com/docs/guides/)、[Epidemic API Reference](https://developers.epidemicsound.com/docs/api-reference/)、[Epidemic MCP Server](https://developers.epidemicsound.com/docs/mcp/)

商业边界：官方 Business Plan 允许第三方客户项目，内容在有效订阅期间发布后可持续清权；商业 SFX 需要有效的 Pro/Enterprise 等合适方案，并应对发布渠道做 safelist。[Epidemic Business Plan](https://help.epidemicsound.com/hc/en-us/articles/33405023521554-Business-Plan)、[Epidemic Sound Effects](https://www.epidemicsound.com/sound-effects/)

自动化评价：**很高**。免费 API key 可用于原型评估，但正式将 API/MCP 用进生产和替客户发布，必须取得与产品形态匹配的 Partner/生产许可，不能拿普通网页订阅去模拟企业 API 集成。[Epidemic 开发者产品页](https://www.epidemicsound.com/business/developers/)

### D. Soundstripe：能力很好，但偏企业合作

Soundstripe 有正式开发者 API，覆盖歌曲、SFX、歌单、音频文件与搜索。它的 Supe Search 可用自然语言、项目上下文、图片或视频进行搜索，并返回歌曲元数据、签名音频地址和 stems，但该能力要求企业合作和 Supe add-on。[Soundstripe Developer Hub](https://docs.soundstripe.com/)、[Supe Search](https://docs.soundstripe.com/reference/supe-search)

其企业页明确 API 可做搜索、策展、播放和元数据，许可可按合作覆盖跨渠道商业使用。[Soundstripe API](https://www.soundstripe.com/api)

自动化评价：**很高但不是轻量自助 MVP**。客户项目和广告覆盖随方案不同，正式使用前必须让账户方案覆盖品牌广告、客户项目和目标地域，并保存 Proof of License。[Soundstripe 客户项目许可](https://www.soundstripe.com/knowledge/licensing-usage/music-for-client-projects)

### E. Adobe Stock Audio：许可清楚，适合单曲或 Adobe 工作流

Adobe Stock Audio 标准许可覆盖社交媒体、网站、数字广告和企业演示；获得许可后可全球、永久、多项目使用，但必须与画面或其他音频同步，不能单独分发。每条授权音乐都有 license validation code。[Adobe Stock FAQ](https://helpx.adobe.com/stock/faq.html)

Adobe Stock 有 Search、License History、License 和 Download API；但官方 API FAQ 说明音频资源默认被 Search API 隐藏，已知 ID 的 Files/License API 仍可处理。因此它技术上可集成，却不如 VFine/Epidemic 适合从零自动搜歌。[Adobe Stock API](https://developer.adobe.com/stock/docs/api/)、[Adobe Stock API FAQ](https://developer.adobe.com/stock/docs/faq/)

自动化评价：**中**。适合已有 Adobe 账户和已知候选曲目的采购、留证和下载，不是首选的全自动发现库。

### F. Artlist：许可适合，条款不允许 Agent 自动下载

Artlist Pro/Business 覆盖 TikTok、广告、付费推广和客户项目，资产可以下载并同步进视频；项目需在有效订阅期间完成并发布，之后可继续使用。[Artlist License](https://artlist.io/help-center/privacy-terms/artlist-license/)

但 Artlist 许可明确把软件、bot 等自动下载视为不合理并禁止；当前日下载上限也明确列出 40 首音乐和 100 个 SFX。其商业条款还禁止用机器人、爬虫或 scraper 自动访问和收集站点内容。[Artlist License 自动化限制](https://artlist.io/help-center/privacy-terms/artlist-license)、[Artlist Business Terms](https://artlist.io/help-center/privacy-terms/business-terms-of-use/)

自动化评价：**低**。可以保留为人工选曲、人工下载、再把合法本地文件交给 Skill 的路径；不能让 Agent 自动登录、爬取或批量下载。

### G. Envato Elements：适合人工项目制，自动化不理想

Envato 每次下载会产生“一项目一许可”的商业授权；客户项目允许转交成片，音乐必须同步在更大的作品中，不能单独分发。每个独立项目需要单独许可，并可下载 PDF 证书。[Envato License Terms](https://elements.envato.com/license-terms)、[Envato License Certificate](https://help.elements.envato.com/hc/en-us/articles/360000621443-Envato-Elements-item-license-certificate)

自动化评价：**低至中**。公开材料没有面向此用途的自助音频 API；适合人工挑选和下载后将文件及证书交给 Skill，不适合作为自动化主库。

## 三、免费库只适合作为兜底

### 1. Pixabay：可以商用，但必须接受平台和权利链风险

Pixabay 允许音乐和音效用于商业视频、客户视频和促销材料，只要音频是更大创作的一部分，不以独立文件分发。[Pixabay FAQ](https://pixabay.com/service/faq/)、[Pixabay Terms](https://pixabay.com/service/terms/)

主要风险：

- 内容由用户上传，Pixabay 明确不保证所有第三方权利或授权都已取得，责任最终在使用者。
- 一些音乐进入 YouTube Content ID，可能在不同平台触发静音、屏蔽或争议；带盾牌的曲目应保存下载证书。
- Pixabay 禁止未经授权的抓取、批量或系统化复制；公开 Content API 不应被假定为音乐/SFX 批量下载 API。

MVP 可用规则：只接受官方页面直接下载；保存曲目 URL、作者、文件 hash、下载日期、当日许可 PDF/网页快照；优先不带 Content ID 标记的曲目；商业客户交付默认仍优先换成付费库。

### 2. Freesound：适合单点节奏音效，不适合无脑全收

Freesound 每个音效由上传者选择 CC0、CC BY 或 CC BY-NC 等许可。商业项目可自动接受 CC0；CC BY 只有在交付流程能稳定提供署名时才接受；CC BY-NC 必须排除。[Freesound License FAQ](https://freesound.org/help/faq/)

Freesound API 支持文本搜索和预览；下载原始文件需要 OAuth2。其 API 条款说明商业 API 使用条件需要按个案与平台协商。[Freesound API](https://freesound.org/docs/api/overview.html)、[Freesound API Terms](https://freesound.org/help/tos_api/)

自动化评价：**技术高、授权治理要求高**。适合“whoosh、click、pop、hit、clock、splash”等短 SFX，不作为主要 BGM 库。

### 3. YouTube Audio Library：不作为抖音素材源

YouTube 官方将 Audio Library 定义为 YouTube Studio 内的 royalty-free music 与 SFX，并说明可用于“your videos”和 YouTube 获利；Creator Music 的许可则更明确不可转移到其他平台。[YouTube Audio Library](https://support.google.com/youtube/answer/3376882/use-music-and-sound-effects-from-the-audio-library)、[Creator Music 使用边界](https://support.google.com/youtube/answer/11611019)

公开帮助没有为中国大陆抖音商业发布提供明确跨平台授权，因此不应把它纳入抖音本地成片 Skill。若未来逐曲条款明确允许其他平台，再按该具体条款处理。

## 四、独立 Skill 应该解决什么

### 建议名称与调用关系

建议名称：`source-faithful-soundtrack`

工作流位置：

```text
生成视频
  → 最终剪辑与画面节奏修正
  → source-faithful-captions
  → source-faithful-soundtrack
  → 最终音画 QC 与交付
```

它应是独立 Skill，由 `viral-replica-finishing` 调用，而不是塞进字幕 Skill。原因是字幕以语音文字和视觉排版为核心；配乐则涉及外部资产采购、节拍分析、许可、混音和响度，输入、失败模式和证据完全不同。

### MVP 输入

1. `reference_video.mp4`：原爆款视频，用于理解声音语法，不抽取其 BGM 复用。
2. `generated_final.mp4`：已经完成画面和口播的目标成片。
3. `speech_timeline.json`：实际成片口播字/句时间。
4. `edit_markers.json`：切点、动作峰值、产品露出、字幕 impact 事件；没有时由 Skill 检测。
5. `delivery_scope.json`：品牌/客户主体、自然/广告、目标平台、地域、账号数量、项目期限。
6. `library_policy.json`：允许使用的曲库、账户/计划、是否允许付费、是否要求人工批准购买。

### MVP 输出

```text
soundtrack/
├── source_sound_grammar.json
├── candidates.json
├── selected_bgm.wav
├── sfx/
│   └── *.wav
├── audio_timeline.json
├── final_with_sound.mp4
├── mix_qc.json
└── licenses/
    ├── license_manifest.json
    ├── receipts/
    ├── certificates/
    └── terms_snapshots/
```

关键文件定义：

- `source_sound_grammar.json`：原片大致 BPM、情绪、乐器质感、能量段落、卡点类型、音效角色；不保存或复制原片受版权保护的音频。
- `candidates.json`：至少 3 个现成曲目候选，记录供应商、asset ID、BPM、时长、是否纯音乐、许可范围、选择理由和预览链接。
- `audio_timeline.json`：目标成片的 BGM 片段、beat grid、剪切/循环点、ducking 包络、SFX 事件、增益和淡入淡出。
- `license_manifest.json`：每个音频资产对应的最终成片、项目主体、平台、地域、下载日期、许可证书、条款快照和文件 hash。

### 自动工作流程

1. **识别原片声音语法**
   - 将人声、BGM、SFX 只用于分析。
   - 测 BPM、节拍强弱、能量曲线、静音/转场位置。
   - 用视频理解识别“这一个声音在叙事上做什么”，例如：开头两次动作 hit、字幕大字 pop、产品出现时 whoosh、效果对比时 sparkle、结尾 logo sting。

2. **按语义搜索现成曲库**
   - 搜索“轻快、干净、护肤、节奏明确、无主唱、95–115 BPM”等特征，而不是搜索或下载原视频那首歌。
   - 默认返回 3 个候选，不自动购买高价单曲。
   - 先检查 delivery scope 是否落在许可证内，再允许下载正式文件。

3. **把声音重映射到目标成片**
   - 不能按原片第 N 秒复制，因为生成视频动作不会完全同秒。
   - 把原片“功能事件”映射到目标事件：第一次“涂”的动作峰值、第二次“涂”的动作峰值、产品名出现、泥膜涂开、清洗、效果对比、结尾产品镜头。
   - 选择歌曲最合适的 20–30 秒段落；必要时在合法范围内做剪切、循环、淡入淡出，不进行许可证禁止的 remix/mashup。

4. **对白优先混音**
   - 口播存在时自动 duck BGM；句间和卡点处恢复能量。
   - SFX 必须短、准、少，只强化真实可见动作或字幕 impact，不用音效替虚构动作找理由。
   - 检查 true peak、响度、对白可懂度、头尾爆音和声道。

5. **版权闸门**
   - 没有 license manifest 或授权范围不覆盖项目，不能输出“可交付”。
   - 付费购买、商业 API 生产授权和失败重购都应保持用户审批边界。

### MVP 先不要做的事情

- 不生成 AI 音乐；用户要的是已有曲库里的成熟 BGM。
- 不从原视频、抖音、剪映草稿、热门视频、QQ 音乐/网易云会员缓存、TikTok CML 页面抓音频。
- 不以“免版税”“无版权”几个标签代替实际许可检查。
- 不把 TikTok CML 授权自动解释成抖音授权。
- 不让 Agent 绕过登录、抓包、缓存或下载限制；Artlist、Envato、剪映等没有明确 API 的渠道走人工下载。
- 不未经批准购买单曲或开通订阅。
- 不为追求卡点而把口播切碎、压住对白，或在每个剪切点都堆音效。
- 不把下载的音乐/SFX 作为独立素材再分发给客户；只交付嵌入成片的使用权和必要的授权证明。

## 五、推荐的实施顺序

### 第一阶段：现在就能做的 MVP

1. 接 VFine 作为大陆主库，确认 API 沙盒/生产接入、短视频广告许可、抖音自然与付费投放、多账号、客户项目和证书接口。
2. 免费兜底先实现 Pixabay 手工候选导入和 Freesound API 的 CC0/CC BY SFX 严格过滤。
3. Skill 完成原片声音语法、目标事件映射、BPM/beat grid、本地混音、QC 和 license manifest。
4. 用户批准候选曲后才下载正式文件或产生费用。

### 第二阶段：自动选曲和高质量音效

1. 申请 Epidemic Partner API / MCP 的生产试用，对同一条视频跑 VFine 与 Epidemic A/B。
2. 利用 Epidemic 的 video/reference search、beat timing 和 stems，提高对齐速度并减少对白冲突。
3. 若国内流行音乐需求显著，再评估 TME 音乐云/曲易买企业方案。

### 第三阶段：平台内发布分支

增加 `delivery_mode=douyin_platform`：Skill 不下载巨量/剪映曲库，而是输出推荐曲目 ID/名称、使用区间、站内添加步骤和平台许可证据，最终由抖音/巨量/剪映在许可平台内合成发布。这个分支不能冒充已经含 BGM 的本地 master。

## 六、每条成片必须保存的版权证据

最低清单：

- 供应商和官方网址。
- 曲目/SFX 名称、作者、asset ID、版本和文件 hash。
- 下载时间、购买时间、账户/订阅计划、订单/发票号。
- 被授权主体、客户、项目名、自然内容或广告、平台、账号数量、地域、期限。
- 许可证书/PDF/validation code/授权代码。
- 下载当日的曲目页和许可条款快照。
- 成片 ID、使用的时间区间、是否剪切/循环/变速、是否使用 stems。
- 免费库的原始 URL、许可类型、作者署名文本和 Content ID 标记。
- 供应商要求的 safelist/clearlist 记录。
- 最终 `license_manifest.json` 与成片一起归档，但不把原始音乐文件对外分发。

## 最终建议

这个方向值得单独做 Skill。最重要的不是“自动加一条 BGM”，而是把以下闭环做成系统能力：

```text
听懂原片的声音功能
→ 从合法现成曲库找三首真正可用的候选
→ 用户确认/费用闸门
→ 按新成片真实动作重新卡点
→ 对白优先混音
→ 保存可追溯的授权证据
→ 最终音画 QC
```

首选落地是 **VFine + Epidemic**：VFine 负责中国大陆商用、中文场景和授权凭证；Epidemic 负责最强的 Agent 搜索、beat/stem/SFX 和自动化能力。Pixabay/Freesound 只作为可控的 MVP 兜底，巨量/剪映曲库只作为站内发布和趋势发现，不当成本地音频仓库。
