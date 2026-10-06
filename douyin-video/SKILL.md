---
name: video-html-extractor
description: 从用户上传的音/视频文件提取文案（语音转文字），转成结构化后生成两版单文件 HTML——摘要版（8 种视觉组件混合排版）与阅读版（分段排版、字号/字体/主题可调），并按文案主题自动命名。适用用户上传 .mp4/.mov/.mkv/.mp3/.wav/.m4a/.flac/.ogg 并要求「提取文案」「转成文字」「做成网页/HTML」「可视化」「整理内容」的场景。
---

# 视频文案提取 → 两版可视化 HTML

**一条 skill，一套流程，任何模型都能跑出一致的产物。** 你不需要自己编排步骤，也不要去读渲染器源码。

## 最短路径速查（照抄这 6 条命令即可）

```bash
# 1. 输入（推荐免 cp 用法）：脚本支持附件绝对路径 + --out 指定工作区，产物落 --out 目录，无需复制
python3 <skill>/scripts/run_pipeline.py prepare <附件绝对路径> --out /storage/emulated/0/DSH/<工作区>
#    仅当想保留本地 input.mp4 副本时才手动复制（附件目录只读）：
#    cp <附件路径> /workspace/input.mp4

# 2. prepare（全自动：提取 → ASR → 机器校正 → 骨架）
#    用免 cp 用法时省略第 1 步，直接到第 3 步填 analysis.json；用副本则跑：
python3 <skill>/scripts/run_pipeline.py prepare input.mp4

# 3. 人工填 analysis.json（唯一要动手的步骤，按 TASK.md + examples/analysis.example.json）
#    + 一次 web_search 批量校准 entities（<2min 全中文实体可跳过）

# 4. 自检到 0 error（用 --out 时先 cd 到工作区；finish 内部也会自动校验，此项为可选预检）
python3 <skill>/scripts/validate_analysis.py analysis.json --transcript transcript.txt

# 5. finish（自动渲染两版 HTML；路径须与 prepare 一致）
#    免 cp 用法：python3 <skill>/scripts/run_pipeline.py finish <附件绝对路径> --out /storage/emulated/0/DSH/<工作区>
#    副本用法：python3 <skill>/scripts/run_pipeline.py finish input.mp4

# 6. 交付 + 清理（finish 已自动删中间产物）。仅当用了 input.mp4 副本时，才手动删该副本（见 SKILL.md 第 5 节清理说明）
```

任何一步卡住、想看细节，再回 SKILL.md 对应小节。

## 你要做的只有三件事

1. 运行一次 `prepare`（脚本自动完成：提取音频 → ASR 转写 → 机器校正 → 生成骨架 `analysis.json` 和任务单 `TASK.md`）。
2. 按 `TASK.md` 把 `analysis.json` 从骨架填成完整文档；**填完做一轮网络校准**（见「网络校准」），跑 `validate_analysis.py` 自检到 **0 error**（仅 WARN 可留，不阻塞渲染），再运行 `finish`（脚本自动校验 + 按 DESIGN-SPEC 渲染两版 HTML + 按 title 重命名校正稿 + 自动清理中间产物，原始逐字稿 `transcript.txt` 一并删除，仅保留校正稿）。
   - **快路径**：若视频 < 2 分钟且 `entities` 里全是常见中文名（抖音/今日头条/小红书等，ASR 误写率极低），web_search 可以只做 1 次验证搜索（确认没把「快手」写成「头条」这类近义混用），不必逐条查；有英文音译词或冷门人名/产品名才需要批量搜索。
3. 交付前按「交付前自查清单」过一遍。

除此之外的转写、校正、渲染、校验、清理，全部由脚本完成。**不要手改 transcript 或 HTML。**

## 环境变量 / 密钥

已配置，无需向用户询问，也不要写进任何持久文件：

| 用途 | 自动读取 |
|------|---------|
| ASR（硅基流动） | `~/.dsh/secrets/siliconflow_api_key` |
| 机器校正（智谱） | `~/.dsh/secrets/zhipu_api_key` |

默认 ASR 模型：`XingChenAGI/XingChenASR-V3.2-Ultra`（免费，适合口语化）。

## 工作流（详细版；已走最短路径可跳过本节）

### 第 1 步：确认输入文件

确认文件存在、可读。>50MB 时脚本会自动分块，无需你做任何事。

### 第 2 步：prepare（全自动）

```bash
python3 <skill_dir>/scripts/run_pipeline.py prepare <输入文件> [--workers 3] [--out 输出目录]
```

脚本依次做：提取 16k mono WAV → ASR 分块转写 → 智谱机器校正 → **交叉验证（检查 changes 清单中的修正是否真的应用到了校正稿文本，未应用的自动补全）** → 生成骨架 + 任务单。**若工作区已有 `transcript.txt`/`transcript_calibrated.txt` 缓存会直接跳过对应步骤（命中缓存近零成本），且绝不覆盖已有的 `analysis.json`。** 退出码 `0` 成功；`1` 提取失败（看上方输出，若为解码问题走文末降级方案）；`3/4` 校正 key 不可用（跳过校正，你在填 analysis.json 时手工完成即可）。

完成后它会打印：骨架路径、任务单路径、以及低置信度校正项清单。骨架未填完时 validate 报 ERROR 是**预期现象**，不要慌。

### 第 3 步：填 analysis.json（这是你唯一要动的）

1. **读** `TASK.md`（任务单）+ `transcript.txt`（内容来源）+ `transcript_calibrated.txt`（校正稿，正文以它为准）+ `examples/analysis.example.json`（**结构照抄它，别猜字段名**）。
2. 用 write 工具**整体覆盖** `analysis.json`，保留骨架里的正确键名，只填内容：
   - `title`：具体、可检索、≤30 字。禁用泛词（转写/文案/内容整理/transcript/未命名/原始文件名）。例：「耶鲁死亡课：直面死亡才能活明白」。
   - `tone` / `summary` / `hero_facts`(3–6 个记忆点数字) / `sections`(6–10) / `key_takeaways`(5–10，带 [mm:ss] 引用) / `conclusion` / `entities` / `footer.calibration`。
   - **`summary` 必须写「核心观点」，不是「内容摘要」**。3–5 句话，只保留：① 文案的中心论点（1 句，可加引号原文）；② 支撑论点的 2–3 个关键数字/数据；③ 一句行动指令或结论。**不要写「博主用 X 经历切入」「后来他读到 Y」「由此他给出 Z」「结尾邀请观众 W」这类叙事流水账**——视频讲了什么、谁说的、怎么转折的，全都不进 summary，这些留给 `sections` 和 `key_takeaways` 去讲。读者打开 HTML 第一眼看到的 summary 是「文案本身在讲什么」，不是「视频怎么讲的」。例：原文核心是「人是需要间歇性堕落的，精力管理比时间管理更重要」，那 summary 就写「间歇性堕落是自救：人就像弹簧……老教授 5+2 / 6+1……有效工作时间只有 4 小时，用 20% 有效时间干 20% 最重要的事」，不写「博主傻白用高三经历切入、崩溃后读了一篇文章」。
   - `sections` 的 `type` 按内容本质选并配对该字段：`timeline`(时序)/`compare`(对比)/`pair`(痛点解法)/`architecture`(结构)/`flow`(流向)/`quote`(金句)/`list`(清单)/`default`(论述)。**不要全堆成 default。** 具体字段形状看 `examples/analysis.example.json` 与 TASK.md。
3. **网络校准（必填一步）**：填完 `entities` 后，**用 web_search 批量核实专有名词的官方写法**——把 `entities` 按类别分组，**一次 web_search 调用放 2–4 条 queries 同时搜**（如「作家名 + 代表作」「公司 + 产品名」「人名 + 身份」），不要一个词一行单独搜；搜不到官方写法的再补一轮。要核实：
   - **公司/团队名**（快手/字节/腾讯/阿里/OpenAI/谷歌…），确认视频里提到的是哪家。
   - **产品/模型名**（如「可林」→「可灵 Kling」、「C Dance」→「Seedance」），ASR 对英文/音译词误写率极高，必须按官方英文名或官方中文名回填。
   - **人名**（主播/科学家/企业家），确认拼音或汉字写法。
   - **地名/机构名**。
   把校准结果写进 `footer.calibration`（格式：`「ASR 原文」→「官方写法」（出处：URL 或"官方名"）`），并同步替换正文中所有出现该词的位置。**校准只改名词写法，不改观点、数字量级。** 如果 web_search 返回结果与你的先验知识冲突，**以搜索到的官方页面为准**，在 calibration 里标注「网络校准推翻先验」。
4. **红线**：只改高置信度错；不改观点/数字量级/不加事实；金句原样加引号；**所有数字必须能在 transcript.txt 找到出处，禁止编造**（校验器兼容中文数字：原文「二零一九」= JSON「2019」，「三家」= 3，不会误报）；**不要把原文说法「雅化」成原文没有的短语**（校验器查不出，交差前人工抽查 `summary`/`key_takeaways`/`quote` 里的短语，拿不准回 `transcript.txt` 搜）。
5. **通顺度**：转写稿可能含 ASR 把开场音乐/噪音误输出的句首杂字（如「等」）。终审校正稿时若该字使句首不通且无实义，应删除以恢复通顺。这与「拒绝雅化」不冲突——雅化是改写实义措辞，删除句首无义杂字仅是修正 ASR 噪音。
5. **自检到 0 error**（照 TASK.md 末尾的命令）：
   ```bash
   python3 <skill_dir>/scripts/validate_analysis.py analysis.json --transcript transcript.txt
   ```
   它只报 ERROR（不让过）和 WARN（建议修，不阻塞渲染）。照提示改，重跑，直到 ERROR 全消。

**失败退出码对照表**（`validate_analysis.py` 单独跑）：

| 退出码 | 含义 | 怎么办 |
|---|---|---|
| `0` | 校验通过（0 error） | 直接进 finish |
| `1` | 有 ERROR（硬伤：字段/类型/枚举/泛词标题等） | 按输出逐条修，重跑直到 0；ERROR 会拦住 finish，不修好不出网页 |
| `2` | 仅 WARN（小建议，如要点条数略少） | 可修可不修；**不阻塞 finish，照常渲染** |

**无 key 时的降级路径**（完整分支，别懵）：

- **没有硅基流动 key**：ASR 转写跑不了。让用户手动提供文字稿（文件名任意，格式 `[mm:ss] 文本`），放到工作目录后重命名为 `transcript.txt`，从「机器校正」步骤继续。
- **没有智谱 key**（prepare 报 exit 3/4）：机器校正跳过，**不影响后续**——你在第 3 步填 analysis.json 时把校正工作手工完成（对照 transcript 把明显错别字/音译词改对，写进 `footer.calibration`）。
- 两条 key 都缺：手动文字稿 + 手工填 analysis.json + 手工自检，流程仍可走完，只是转写与校正质量取决于人工。

**已知盲区（校验器查不出来，需人工抽查）**：数字出处会校验（兼容中文数字写法，原文「二零一九」与 JSON「2019」互认），但**术语/口诀/短语是否原文存在不校验**。写 analysis.json 时偶发把原文说法「雅化」成原文没有的短语（例：原文「不饿就不吃」被写成「过六不食」）。交差前扫一眼 `summary`、`key_takeaways`、`quote` 卡片里的中文短语，拿不准的就去 `transcript.txt` 里搜一下，搜不到就别用。

### 第 4 步：finish（全自动）

```bash
python3 <skill_dir>/scripts/run_pipeline.py finish <输入文件> [--theme dark|light] [--out 输出目录]
```

先校验（仅 ERROR 拒渲染，WARN 放行），再按 `DESIGN-SPEC.md` 的设计规范生成两版 HTML：
- **摘要版** `<title>_摘要版.html`：8 种视觉组件混合。**不含逐字稿**（校正稿以 `<title>_校正稿.txt` 独立文件交付，不再内嵌到 HTML）。**默认深色主题**（DESIGN-SPEC 核心目标：深色主题 + 渐变红金强调 + 毛玻璃卡片 + 入场/悬浮/背景粒子动效 + 响应式网格）。**导航栏右上角带明暗主题切换按钮**（太阳/月亮图标，点一下换主题，偏好存 `localStorage` 键 `dsh_theme`，下次打开沿用）。
- **阅读版** `<title>_阅读版.html`：校正稿分段排版，A-/A+ 字号、4 款字体、亮暗主题，偏好存 localStorage。**默认深色**；`finish` 的 `--theme light` 同时作用于摘要版与阅读版（两版初始主题一致），页内按钮仍可随时切换。

**render 后自动重命名**：`finish` 渲染完两版 HTML 后，将 `transcript_calibrated.txt` 重命名为 `<title>_校正稿.txt`（文件名与 HTML 保持同一前缀）。原始逐字稿 `transcript.txt` 不重命名，而是由清理步骤自动删除。

`--theme light` 可回落亮色（CSS 变量切换，结构不变；摘要版渲染出的 HTML 仍可点按钮随时切回深色）。

### 第 5 步：交付 + 清理

用 `present` 交付摘要版 + 阅读版 + `<title>_校正稿.txt`（用户只要部分则按需）。**注意：`present` 每次调用最多渲染 4 张卡，3 件交付物必须放同一次调用里传完整**（漏传会被静默吞掉，用户看不到第 3 件）。

**规则：交付物自动复制到系统 Download 目录**。`finish` 渲染完成后，脚本会把本次 `<title>_摘要版.html`、`<title>_阅读版.html`、`<title>_校正稿.txt` 复制一份到 `/storage/emulated/0/Download`（目录不存在则自动创建；复制失败仅警告，不影响主流程）。工作区与 Download 各存一份，用户用系统文件管理器或分享入口可直接找到。

**清理（默认自动）**：`finish` 渲染完成后，**默认自动删除本次任务产生的中间产物**（含原始逐字稿 `transcript.txt`），只留交付物。脚本只按精确路径删自己生成的东西（不 glob 通配），自动满足「不碰历史文件」的红线：

| 自动删除（精确路径） | 说明 |
|---|---|
| `<输入名>.wav` | 音频中间件 |
| `<输入名>.wav.chunks/` | ASR 分块目录 |
| `transcript.txt` | ASR 原始逐字稿（仅保留校正稿） |
| `transcript_calibrated.txt.calib_cache/` | 校正缓存 |
| `report.json` | 机器预筛报告（填完 analysis.json 后已无用） |
| `TASK.md` | 任务单（填完 analysis.json 后已无用） |

保留交付物：`<title>_摘要版.html`、`<title>_阅读版.html`、`<title>_校正稿.txt`、`analysis.json`。若想保留缓存以便断点重跑（重跑 `prepare` 时命中缓存跳过 ASR），用 `finish --keep-cache`。

**仍需人工处理的两件事**：
- 若 `cp` 了输入文件到工作区（如 `input.mp4`），手动删掉这份副本——脚本不知道副本叫什么名字（用户附件目录里的原件**绝不动**）。
- 为装 ffmpeg 下载的 `.deb` 与临时目录（若有）手动清理。

**保留**已装进 `usr/bin/ffmpeg` 的工具链本身。

**红线**：脚本自动清理只删它自己生成的精确路径；若你手动删，只删本次任务产生的文件，删前用 `ls`/文件名特征确认归属，拿不准就问用户；绝不删输出目录里的历史文件。

## 交付前自查清单（照抄，过一遍即可）

- 校验器已 0 error（title 非泛词、字段名/类型/枚举正确、数字能回溯到原文，中文数字写法互认）。
- **专有名词已网络校准**（`footer.calibration` 里有「网络校准」条目，正文已同步替换）。
- **抽查过「雅化」短语**：`summary`/`key_takeaways`/`quote` 里的中文说法都能在 `transcript.txt` 搜到原文，没有原文没有的「雅词」。
- 阅读版可正常打开、字号/主题按钮可用；两版均为单文件、无外部依赖；`finish --theme light` 时两版初始主题一致。
- **视觉符合 DESIGN-SPEC**：深色主题、毛玻璃卡片、渐变强调、入场动画、背景粒子、响应式网格（摘要版）；阅读版有字号/字体/主题控件。
- **主题切换按钮（§3.1.1）**：两版导航栏最右都有圆形毛玻璃按钮，点一下换明暗、偏好写 localStorage（摘要版 `dsh_theme`、阅读版 `theme`）；深色默认、`--theme light` 回落亮色。切换后不会出现文字消失（渐变标题带 `@supports` fallback）。
- 术语校正说明已写在 `footer.calibration`。
- **compare 组件无双图标**：摘要版里 compare 章节的 `<li>` 不应包含 `ico-mark` span（CSS 已用 `::before` 画 ✕/✓，HTML 里再塞 SVG 会双图标）。grep 验证：`grep -c ico-mark *.html` 应为 0；若 >0 说明渲染器回归，改 render_html.py 的 `render_compare`。
- **速度自查**：本次流程里 `web_search` 调用 ≤ 2 次（按实体类别分组批量搜）；没有重复 `ls` 确认同一目录；`prepare`/`finish` 各只跑 1 次（命中缓存时跳过）；`present` 只调 1 次、把 3 件交付物一次性传齐。若违反，下次按「最短路径速查」6 条命令直接照抄。

## 设计规范（DESIGN-SPEC）

两版 HTML 的视觉层由 `DESIGN-SPEC.md`（本目录）定义，**不要凭经验自由发挥 CSS**：

| 维度 | 规定 |
|------|------|
| 主题 | 深色默认（底色 `#1a1a2e`）；`--theme light` 回落亮色 |
| 强调色 | 红 `#e94560` + 金 `#f5c518` 渐变；价值/数字用金色 |
| 卡片 | Glassmorphism：`rgba(255,255,255,0.06)` 背景 + `backdrop-filter:blur(10px)` + `rgba(255,255,255,0.1)` 细边框 + `border-radius:16px` + `0 8px 32px rgba(0,0,0,0.3)` 阴影 |
| 动效 | `fadeInUp` 入场（stagger 0.1s 增量）+ `float` 背景粒子（6 个，`z-index:-1`）+ `pulse` 流程箭头 + `bounce` 滚动指示 |
| 主题切换 | 导航栏最右 38×38 圆形毛玻璃按钮（§3.1.1）：摘要版太阳/月亮 SVG 挂 `body[data-theme]`、localStorage 键 `dsh_theme`；阅读版太阳 SVG 挂 `html[data-theme]`、localStorage 键 `theme`；两版默认深色、`--theme light` 回落亮色 |
| 响应式 | 768px 断点：卡片单列、流程图纵向（箭头 90°）、导航隐藏链接（主题切换按钮保留贴右） |
| 字体 | 系统字体栈（`-apple-system, "PingFang SC", "Microsoft YaHei"…`），零外部加载 |
| 约束 | 单文件零依赖、纯原生 HTML/CSS/JS、语义化标签、动画只用 `transform`/`opacity` |

改渲染器时：`render_html.py`（摘要版）与 `read_render.py`（阅读版）的 CSS 块必须与 `DESIGN-SPEC.md` 同步；新增视觉组件先查 spec §7 片段库。

## 工具链复装（ffmpeg，模型无关）

当 `prepare` 报「本机工具链 ffmpeg 缺失或损坏」时，**不要再让模型手写解包配方**
（过去多次 1 小时卡在这）。正确做法：

1. 若当前会话**已有 dsh-backup 包**（任意一个 `dsh-backup-*.zip`），直接：
   ```bash
   unzip dsh-backup-*.zip -d /tmp/dsh-rest
   sh /tmp/dsh-rest/install-deps.sh install-ffmpeg
   # 无 apt 的机器离线即可；有 apt 且允许联网时:
   sh /tmp/dsh-rest/install-deps.sh install-ffmpeg --net
   ```
   脚本会自动读包内 `toolchain-deps/TARGET_PREFIX`（备份机实测过的 usr 前缀），
   注入 `LD_LIBRARY_PATH` + `LD_PRELOAD`，解包平移全部 `.deb`，跑 `ffmpeg -version` 自检。

2. 若没有现成备份包，按 `TOOLCHAIN_HINT`（脚本 stderr 自动打印）手工走：
   在目标机 usr 前缀下 `apt-get install -y --download-only ffmpeg`，
   再把 `var/cache/apt/archives/*.deb` 逐个 `dpkg-deb -x` 解包，
   把其中 `data/data/com.termux/files/usr/.` 整树 cp 到 `<usr前缀>/`，
   执行/验证必须注入 `LD_LIBRARY_PATH=<前缀>/lib` 与 `LD_PRELOAD=<前缀>/lib/libtermux-exec-ld-preload.so`。

**恢复备份包时（README-RESTORE.md 第 3 节）一律用包内 `install-deps.sh`，**
不要手写 ffmpeg 安装步骤。

## 降级方案（提取失败时）

1. 告知用户无法解码该容器音频轨。
2. 给三个选择：a. 用户手动导成 `.wav`/`.mp3` 再传（从第 2 步起）；b. 有外挂字幕（.srt/.vtt）直接读字幕跳过 ASR；c. 放弃转写，只整理已有文本。
3. **不要**在拿不到真实语音时假装完成转写。

## 边界

- 只处理用户提供的本地文件；不做需登录/付费墙的 URL。
- 不做语音合成、视频剪辑。转写语言以音频实际语言为准；中文效果最好，小语种可能不准需告知用户。
- 所有数字/引语必须能在 `transcript.txt` 找到出处。