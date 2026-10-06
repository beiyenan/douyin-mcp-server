# 安装指南（给安装这个 skill 的人或 Agent 看）

本包是**自包含**的：除 Python 标准库外无任何 pip 依赖，无外部资源引用。
解压即用，照下面四步走。

## 1. 依赖清单

| 依赖 | 必需性 | 说明 |
|---|---|---|
| **Python ≥ 3.8** | 必需 | 纯标准库（argparse/json/os/re/sys/subprocess/urllib/struct/array/wave/hashlib/html/math/random/time/threading/concurrent.futures/uuid/shutil），**不需要 pip install 任何东西** |
| **ffmpeg** | 强烈建议 | 用于音频提取。没有时脚本自动降级到纯 Python 路径（mp4 解 AAC + 包络近似），能跑但转写精度差且会打 HINT |
| **SiliconFlow API key** | 必需（转写） | 免费 key，申请：https://cloud.siliconflow.cn 。模型 `XingChenAGI/XingChenASR-V3.2-Ultra`（免费） |
| **Zhipu（智谱）API key** | 必需（机器校正） | 申请：https://bigmodel.cn 。默认模型 `glm-4.7`。没有时 prepare 跳过机器校正（exit 3/4），后续手工填 analysis.json 时人工完成校正即可，流程仍可走完 |

## 2. 安装（按你的环境选一种）

### A. DeepSeek Harness（DSH）
把整个 `video-html-extractor/` 目录放进 DSH 的 skills 目录：
```bash
cp -r video-html-extractor ~/.dsh/skills/
```
DSH 会自动识别（靠目录名 + `SKILL.md` frontmatter 里的 `name`/`description`）。

### B. 其他 Agent 框架（Claude Code / Codex / 自研 harness 等）
skill 的实质 = `SKILL.md`（行为说明）+ `scripts/`（确定性逻辑）+ `examples/`（结构范本）。
只要把目录放到你的 agent 能读到的位置，并把 `SKILL.md` 的内容注册/链接进你的 skill 体系即可。
**关键约束：`scripts/`、`examples/`、`SKILL.md`、`DESIGN-SPEC.md` 四者的相对位置不能拆散**
（`run_pipeline.py` 用 `__file__` 相对定位 `../examples/analysis.example.json` 和同目录脚本）。

### C. 通用（不接 Agent，直接跑）
解压到任意目录，按 `SKILL.md` 的三条命令手动跑即可。命令里的 `<skill_dir>` 一律替换成实际解压路径。

## 3. 配置密钥（两种写法等价，二选一）

**方式一：文件（推荐，跨会话稳定）**
```bash
mkdir -p ~/.dsh/secrets
printf '%s' '<你的硅基流动key>' > ~/.dsh/secrets/siliconflow_api_key
printf '%s' '<你的智谱key>'     > ~/.dsh/secrets/zhipu_api_key
```

**方式二：环境变量**
```bash
export SILICONFLOW_API_KEY='<你的硅基流动key>'
export ZHIPU_API_KEY='<你的智谱key>'
```
代码读取顺序：环境变量 → `~/.dsh/secrets/<name>` → `~/.dsh/<name>`。
**不要把 key 写进任何会被提交的代码或文档里。**

## 4. 安装自检（跑一遍，全过才算装好）

```bash
cd <解压路径>/video-html-extractor

# ① 所有脚本可编译
for f in scripts/*.py; do python3 -m py_compile "$f" || exit 1; done && echo '① compile OK'

# ② 编排器两个子命令都认识
python3 scripts/run_pipeline.py --help >/dev/null && echo '② CLI OK'

# ③ 校验器 + 范本自洽（范本必须 0 error，否则 examples 本身有问题）
python3 scripts/validate_analysis.py examples/analysis.example.json
#   期望：校验结果：0 错误，N 警告（WARN 不阻塞）

# ④ ffmpeg 探测（可缺，缺了走降级）
command -v ffmpeg && ffmpeg -version | head -1 || echo '④ 无 ffmpeg（降级可用，建议安装）'
```

## 5. 快速上手（装好后跑一个视频）

```bash
python3 scripts/run_pipeline.py prepare <输入.mp4>        # 提取音频→ASR→机器校正→骨架+任务单
# 按 TASK.md + examples/analysis.example.json 手工填好 analysis.json（这是 Agent 唯一要动手的一步）
python3 scripts/validate_analysis.py analysis.json --transcript transcript.txt   # 自检到 0 error
python3 scripts/run_pipeline.py finish <输入.mp4>        # 校验 + 渲染两版 HTML
```
三条命令都可用 `--out <目录>` 显式指定工作目录（默认 = 输入文件所在目录）。
产物（与输入同目录）：`<标题>_摘要版.html`、`<标题>_阅读版.html`、`transcript.txt`、`analysis.json`。
细节、故障排查、降级方案全部见 `SKILL.md`。

## 6. 无 key 时的降级路径

- **没有 SiliconFlow key**：转写这步没法跑。用户手动提供文字稿（`transcript.txt`，`[mm:ss] 文本` 格式）后从「机器校正」步骤继续。
- **没有智谱 key**：prepare 会跳过机器校正（WARN 提示，exit 3/4），流程照常走——填 analysis.json 时人工完成校正，写进 `footer.calibration`。
- **没有 ffmpeg**：降级可用（纯 Python 解 AAC），但转写精度差；或 `apt-get install -y ffmpeg` / `brew install ffmpeg` 装上最省心。

## 7. 目录结构与文件职责

```
video-html-extractor/
├── SKILL.md                  ← 主文档：给执行 Agent 的完整工作流/规范/故障排查（从这里读起）
├── INSTALL.md                ← 本文件：给安装者的依赖与安装说明
├── DESIGN-SPEC.md            ← 视觉设计规范：两版 HTML 的 CSS 权威来源（改渲染器须与它同步）
├── examples/
│   └── analysis.example.json ← analysis.json 的结构范本（手工填时照抄结构；也是校验器自检基准）
└── scripts/
    ├── run_pipeline.py       ← 单命令编排器：prepare / finish（对外唯一入口）
    ├── extract_audio.py      ← 视频/音频 → 16k mono WAV（ffmpeg 优先，纯 Python 降级）
    ├── mp4_extract_aac.py    ← 降级用：纯 Python 从 MP4 容器分离 AAC 轨
    ├── decode_aac.py         ← 降级用：纯 Python ADTS/AAC 包络近似解码（精度有限，会打 HINT）
    ├── asr_transcribe.py     ← 分块并行 ASR（SiliconFlow），输出带 [mm:ss] 时间戳
    ├── llm_calibrate.py      ← 机器校正预筛（Zhipu）：校正稿 + report.json（改动清单可审计）
    ├── validate_analysis.py  ← 严格 schema 校验器：exit 0 通过 / 1 ERROR 拦截 / 2 WARN 放行；数字出处校验兼容中文数字写法
    ├── render_html.py        ← 摘要版渲染器（8 种视觉组件，单文件零外部依赖）
    └── read_render.py        ← 阅读版渲染器（分段排版，字号/字体/主题可调，支持 --theme dark|light）
```

**不要改** `scripts/` 里的脚本（改了出问题没人兜底）；想定制视觉改 `render_html.py`/`read_render.py` 顶部 CSS 块，且须与 `DESIGN-SPEC.md` 同步。

## 8. 版本

- 打包日期：2026-10-05
- 状态：本机实测过完整流程（3 分钟视频 prepare → 手工填 analysis.json → 0 error → finish 出两版 HTML，阅读版主题跟随 + 中文数字校验兼容均验证通过）
- 本包**不含** autofill（LLM 自动填 analysis.json 子命令）：填 analysis.json 这一步由执行 Agent 手工完成，见 `SKILL.md` 第 3 步
- 已知限制：见 `SKILL.md`「降级方案」与「边界」两节（无 key 降级、小语种转写可能不准、术语/口诀幻觉需人工抽查）
