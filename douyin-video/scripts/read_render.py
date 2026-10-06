#!/usr/bin/env python3
"""read_render.py — transcript.txt → 单文件阅读版 HTML

逐字稿按段落分段排版，带时间戳导航，适合细读。
设计令牌系统：深色默认（DESIGN-SPEC），用户可点顶栏按钮切亮色/调字号/换字体，偏好存 localStorage。
零外部资源、单文件可直接双击打开。

用法:
  python3 read_render.py transcript.txt [analysis.json] [--theme=dark|light] [--title "标题"] [--calibrated]

--calibrated: 优先用 <同名>_calibrated.txt（llm_calibrate.py 的校正稿）渲染，阅读体验更好；
              不存在时回退原稿。默认不加则用 ASR 原稿（存证）。

输出:
  文件名自动 = <标题>_阅读版.html
"""

import argparse, json, re, sys, html, os

def esc(s):
    return html.escape(str(s), quote=True)

def parse_transcript(text):
    """Parse transcript into paragraphs (no timestamps)."""
    lines = [l for l in text.strip().split("\n") if not l.startswith("#")]
    paragraphs = []
    for line in lines:
        m = re.match(r'^\[?(\d{2}:\d{2})\]?\s*(.*)', line)
        if m:
            text = m.group(2).strip()
        else:
            text = line.strip()
        # Split on sentence-ending punctuation
        sentences = re.split(r'(?<=[。？！])', text)
        sentences = [s.strip() for s in sentences if s.strip()]
        # Group into paragraphs: aim for ~50-150 chars per paragraph
        para = ""
        for sent in sentences:
            if len(para) + len(sent) > 150 and para:
                paragraphs.append(para)
                para = sent
            else:
                para += sent
        if para:
            paragraphs.append(para)
    return paragraphs

def format_paragraph(text):
    """Apply visual formatting to a paragraph: bold key quotes, stats, and highlights."""
    # 1. Bold direct quotes in 「」or "" (Chinese quotes)
    text = re.sub(r'「([^」]+)」', r'<strong>「\1」</strong>', text)
    
    # Chinese double quotes (U+201C and U+201D)
    def replace_chinese_quote(match):
        return '<strong>' + match.group(0) + '</strong>'
    text = re.sub(r'[\u201c][^\u201d]+[\u201d]', replace_chinese_quote, text)
    
    # Regular ASCII quotes
    text = re.sub(r'"([^"]+)"', r'<strong>"\1"</strong>', text)
    text = re.sub(r"'([^']+)'", r'<strong>''\1''</strong>', text)
    
    # 2. Bold numbers and statistics (e.g., 26讲, 6100万, 9倍, 33%, 140%)
    text = re.sub(r'(\d+\s*(?:个|讲|小时|万|亿|倍|%|美元|人|年|岁|次|天|月))', r'<strong>\1</strong>', text)
    
    # 3. Bold key transition/emphasis phrases
    emphasis_phrases = [
        r'(第一[句，]?)', r'(第二[句，]?)', r'(第三[句，]?)', r'(第四[句，]?)',
        r'(首先)', r'(其次)', r'(最后)', r'(总之)',
        r'(因此)', r'(所以)', r'(但是)', r'(然而)', r'(可是)',
        r'(这意味着)', r'(换句话说)',
    ]
    for phrase in emphasis_phrases:
        text = re.sub(phrase, r'<strong>\1</strong>', text)
    
    return text

def render_html(paragraphs, title, theme, source_note="所有文字来自原始转写"):
    parts = []
    # HTML head；--theme light 时给 <html> 打上 data-theme="light"（CSS 选择器 [data-theme="light"] 挂在 html 元素上才生效）
    html_attrs = ' lang="zh-CN"' + (' data-theme="light"' if theme == "light" else '')
    parts.append(f'<!DOCTYPE html><html{html_attrs}><head><meta charset="UTF-8">')
    parts.append('<meta name="viewport" content="width=device-width, initial-scale=1.0">')
    parts.append(f'<title>{esc(title)}</title>')
    parts.append('<style>')

    # CSS（DESIGN-SPEC：深色默认，毛玻璃 + 渐变强调；保留 A-/A+/字体/主题 控件）
    css = """:root{
  /* DESIGN-SPEC 深色（默认） */
  --primary:#1a1a2e;--secondary:#16213e;
  --highlight:#e94560;--gold:#f5c518;
  --bg:#1a1a2e;--bg2:#16213e;
  --card:rgba(255,255,255,0.06);--card2:rgba(255,255,255,0.04);
  --line:rgba(255,255,255,0.1);--card-border:rgba(255,255,255,0.1);
  --txt:#f0f0f0;--muted:#b0b0b0;--dim:#888;
  --accent:#e94560;--accent2:#00d9ff;--warn:#f5c518;
  --grad-a:#e94560;--grad-b:#f5c518;--grad-c:#ff6b6b;
  --radius:16px;--shadow:0 8px 32px rgba(0,0,0,0.3);
  --glow:rgba(233,69,96,0.4);
  --fs-body:16px;--fs-title:44px;--fs-small:14px;--fs-toc:13px;
  --font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif;
}
html[data-theme="light"]{
  --bg:#f5f7fc;--bg2:#ffffff;
  --card:#ffffff;--card2:#eef2fa;
  --line:#e2e8f4;--card-border:#e2e8f4;
  --txt:#16203a;--muted:#55617a;--dim:#8b96ac;
  --accent:#2f6bff;--accent2:#0d9f7d;--warn:#d98400;
  --grad-a:#2f6bff;--grad-b:#f5c518;--grad-c:#ff6b6b;
  --shadow:0 1px 2px rgba(22,32,58,.04),0 10px 28px -14px rgba(22,32,58,.14);
  --glow:rgba(47,107,255,0.3);
}
body{
  background:var(--bg);
  background-image:radial-gradient(1100px 600px at 12% -8%,rgba(233,69,96,.08),transparent 55%),radial-gradient(900px 500px at 100% 0%,rgba(0,217,255,.05),transparent 50%);
  background-attachment:fixed;
  color:var(--txt);transition:background .3s,color .3s;
}
html[data-theme="light"]{
  background-image:radial-gradient(1100px 600px at 12% -8%,rgba(47,107,255,.10),transparent 55%),radial-gradient(900px 500px at 100% 0%,rgba(13,159,125,.08),transparent 50%);
}
/* 背景粒子 */
.bg-particles{position:fixed;inset:0;overflow:hidden;z-index:-1;pointer-events:none}
.bg-particles span{position:absolute;border-radius:50%;background:rgba(233,69,96,0.06);animation:float 22s infinite}
html[data-theme="light"] .bg-particles span{background:rgba(47,107,255,0.06)}
.bg-particles span:nth-child(1){width:260px;height:260px;left:10%;top:20%;animation-duration:26s}
.bg-particles span:nth-child(2){width:200px;height:200px;left:70%;top:15%;animation-delay:-5s;animation-duration:19s}
.bg-particles span:nth-child(3){width:320px;height:320px;left:45%;top:60%;animation-delay:-9s;animation-duration:28s}
.bg-particles span:nth-child(4){width:150px;height:150px;left:82%;top:75%;animation-delay:-13s;animation-duration:17s}
@keyframes float{
  0%,100%{transform:translateY(0) rotate(0deg);opacity:.5}
  33%{transform:translateY(-28px) rotate(120deg);opacity:.75}
  66%{transform:translateY(18px) rotate(240deg);opacity:.35}
}
"""
    parts.append(css)
    parts.append("""
*{box-sizing:border-box;margin:0;padding:0}
html{scroll-behavior:smooth}
body{font-family:var(--font-family);line-height:1.85;-webkit-font-smoothing:antialiased}
.wrap{max-width:780px;margin:0 auto;padding:0 22px}
.hero{padding:64px 0 28px;text-align:center}
.hero .tagline{display:inline-block;font-size:var(--fs-small);font-weight:800;letter-spacing:.14em;text-transform:uppercase;color:var(--accent);border:1px solid var(--accent);border-radius:100px;padding:4px 14px;margin-bottom:16px}
.hero h1{font-size:clamp(28px,4.5vw,var(--fs-title));font-weight:800;line-height:1.25;margin-bottom:12px;
  background:linear-gradient(135deg,var(--grad-a),var(--grad-b),var(--grad-c));
  -webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text}
.hero .meta{font-size:var(--fs-small);color:var(--dim)}
.topbar{position:sticky;top:0;z-index:100;background:rgba(26,26,46,0.85);backdrop-filter:blur(12px);-webkit-backdrop-filter:blur(12px);border-bottom:1px solid var(--card-border);padding:8px 16px;display:flex;align-items:center;justify-content:flex-end;gap:8px;transition:background .3s,border-color .3s}
html[data-theme="light"] .topbar{background:rgba(255,255,255,0.85);border-bottom-color:var(--card-border)}
.ctrl-btn{width:32px;height:32px;border-radius:50%;border:1px solid var(--card-border);background:var(--card);color:var(--muted);display:grid;place-items:center;cursor:pointer;transition:.2s;font-size:13px;font-weight:700;line-height:1;backdrop-filter:blur(6px)}
.ctrl-btn:hover{border-color:var(--accent);color:var(--accent);transform:scale(1.1)}
.ctrl-btn:disabled{opacity:.35;cursor:default;transform:none}
.ctrl-btn svg{width:15px;height:15px}
.fs-label{display:grid;place-items:center;font-size:10px;font-weight:800;letter-spacing:-.5px;min-width:28px;color:var(--muted)}
.font-select{position:relative}
.font-menu{display:none;position:absolute;top:38px;right:0;background:var(--card);border:1px solid var(--card-border);border-radius:8px;box-shadow:0 8px 32px rgba(0,0,0,.35);z-index:200;min-width:80px;padding:4px;backdrop-filter:blur(10px)}
.font-menu.show{display:block}
.font-menu button{display:block;width:100%;padding:6px 10px;border:none;background:none;color:var(--txt);font-size:12px;cursor:pointer;border-radius:4px;text-align:left}
.font-menu button:hover{background:var(--card2)}
.font-menu button.active{color:var(--accent);font-weight:700}
.content{padding:36px 0}
.para{margin-bottom:28px;font-size:var(--fs-body);line-height:1.85;color:var(--txt);text-align:justify;transition:font-size .2s}
.para strong{color:var(--grad-b);font-weight:700}
.divider{width:40px;height:2px;background:linear-gradient(90deg,var(--grad-a),var(--grad-b));margin:0 auto 36px;border-radius:1px}
footer{padding:40px 0 48px;border-top:1px solid var(--card-border);color:var(--dim);font-size:var(--fs-small);text-align:center}
footer p{margin:4px 0}
::-webkit-scrollbar{width:6px;height:6px}
::-webkit-scrollbar-track{background:var(--bg)}
::-webkit-scrollbar-thumb{background:var(--line);border-radius:3px}
::-webkit-scrollbar-thumb:hover{background:var(--dim)}
@media(max-width:768px){.hero{padding:40px 0 20px}.hero h1{font-size:clamp(22px,7vw,32px)}.content{padding:24px 0}.topbar{padding:6px 10px}.ctrl-btn{width:28px;height:28px;font-size:12px}.fs-label{min-width:24px;font-size:9px}}
""")
    parts.append('</style></head><body>')
    # 背景粒子（阅读版 4 个，轻量）
    parts.append('<div class="bg-particles"><span></span><span></span><span></span><span></span></div>')

    # Topbar with controls
    parts.append('<div class="topbar">')
    parts.append('<button class="ctrl-btn" id="fsMinus" onclick="changeFont(-1)" title="减小字体">A-</button>')
    parts.append('<span class="fs-label" id="fsLabel">16</span>')
    parts.append('<button class="ctrl-btn" id="fsPlus" onclick="changeFont(1)" title="增大字体">A+</button>')
    parts.append('<div class="font-select">')
    parts.append('<button class="ctrl-btn" onclick="toggleFontMenu()" title="选择字体" id="fontBtn">宋</button>')
    parts.append('<div class="font-menu" id="fontMenu">')
    parts.append('<button onclick="setFontFamily(0)" id="fontOpt0">宋体</button>')
    parts.append('<button onclick="setFontFamily(1)" id="fontOpt1">黑体</button>')
    parts.append('<button onclick="setFontFamily(2)" id="fontOpt2">仿宋</button>')
    parts.append('<button onclick="setFontFamily(3)" id="fontOpt3">等线</button>')
    parts.append('</div>')
    parts.append('</div>')
    parts.append('<button class="ctrl-btn" onclick="toggleTheme()" title="切换亮/暗主题">')
    parts.append('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="5"/><path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/></svg>')
    parts.append('</button>')
    parts.append('</div>')

    # Hero
    parts.append(f'<div class="hero"><div class="wrap"><span class="tagline">校正稿 · 阅读版</span>')
    parts.append(f'<h1>{esc(title)}</h1>')
    parts.append(f'<p class="meta">共 {len(paragraphs)} 段</p>')
    parts.append('</div></div>')

    # Content - paragraphs with dividers every ~10 paragraphs
    parts.append('<div class="content"><div class="wrap">')
    for i, para in enumerate(paragraphs):
        if i > 0 and i % 10 == 0:
            parts.append('<div class="divider"></div>')
        # 先转义防注入，再应用高亮（引号/数字/强调词加粗）
        parts.append(f'<p class="para">{format_paragraph(esc(para))}</p>')
    parts.append('</div></div>')

    # Footer
    parts.append(f'<footer><div class="wrap"><p>由视频文案提取 skill 生成 · {source_note}</p>')
    parts.append(f'<p style="margin-top:8px">共 {len(paragraphs)} 段 · 单文件、无外部依赖</p>')
    parts.append('</div></footer>')

    # JS
    parts.append('<script>')
    parts.append('var FS=[14,16,18,20,22,25];')
    parts.append('var fsi=1;')
    parts.append('var FONTS=[')
    parts.append('  {n:"宋体",f:"SimSun,\\"Songti SC\\",serif",s:"宋"},')
    parts.append('  {n:"黑体",f:"SimHei,\\"Heiti SC\\",sans-serif",s:"黑"},')
    parts.append('  {n:"仿宋",f:"FangSong,\\\"FangSong_GB2312\\\",serif",s:"仿"},')
    parts.append('  {n:"等线",f:"DengXian,\\\"DengXian Light\\\",sans-serif",s:"等"}')
    parts.append('];')
    parts.append('var ffonti=0;')
    parts.append('function setFont(idx){')
    parts.append('  fsi=Math.max(0,Math.min(FS.length-1,idx));')
    parts.append('  var fs=FS[fsi];')
    parts.append('  document.documentElement.style.setProperty("--fs-body",fs+"px");')
    parts.append('  document.documentElement.style.setProperty("--fs-title",Math.round(fs*2.75)+"px");')
    parts.append('  document.documentElement.style.setProperty("--fs-small",Math.max(11,fs-2)+"px");')
    parts.append('  document.getElementById("fsLabel").textContent=fs;')
    parts.append('  document.getElementById("fsMinus").disabled=(fsi===0);')
    parts.append('  document.getElementById("fsPlus").disabled=(fsi===FS.length-1);')
    parts.append('  try{localStorage.setItem("fontSize",fs)}catch(e){}')
    parts.append('}')
    parts.append('function changeFont(dir){setFont(fsi+dir);}')
    parts.append('function setFontFamily(idx){')
    parts.append('  ffonti=Math.max(0,Math.min(FONTS.length-1,idx));')
    parts.append('  var ff=FONTS[ffonti];')
    parts.append('  document.documentElement.style.setProperty("--font-family",ff.f);')
    parts.append('  document.getElementById("fontBtn").textContent=ff.s;')
    parts.append('  for(var i=0;i<FONTS.length;i++){document.getElementById("fontOpt"+i).classList.toggle("active",i===ffonti);}')
    parts.append('  try{localStorage.setItem("fontFamily",ff.n)}catch(e){}')
    parts.append('  document.getElementById("fontMenu").classList.remove("show");')
    parts.append('}')
    parts.append('function toggleFontMenu(){document.getElementById("fontMenu").classList.toggle("show");}')
    parts.append('function toggleTheme(){')
    parts.append('  var h=document.documentElement;')
    parts.append('  var isLight=h.getAttribute("data-theme")==="light";')
    parts.append('  h.setAttribute("data-theme",isLight?"":"light");')
    parts.append('  try{localStorage.setItem("theme",isLight?"dark":"light")}catch(e){}')
    parts.append('}')
    parts.append('document.addEventListener("click",function(e){if(!e.target.closest(".font-select")){document.getElementById("fontMenu").classList.remove("show");}});')
    parts.append('try{')
    parts.append('  var t=localStorage.getItem("theme");')
    parts.append('  if(t==="light")document.documentElement.setAttribute("data-theme","light");')
    parts.append('  var fs=parseInt(localStorage.getItem("fontSize"));')
    parts.append('  if(!isNaN(fs)&&FS.indexOf(fs)>=0){setFont(FS.indexOf(fs));}')
    parts.append('  var fn=localStorage.getItem("fontFamily");')
    parts.append('  if(fn){for(var i=0;i<FONTS.length;i++){if(FONTS[i].n===fn){setFontFamily(i);break;}}}')
    parts.append('}catch(e){}')
    parts.append('</script>')
    parts.append('</body></html>')
    return "\n".join(parts)

def main():
    ap = argparse.ArgumentParser(description="transcript.txt → 单文件阅读版 HTML")
    ap.add_argument("transcript", help="transcript.txt 路径")
    ap.add_argument("analysis", nargs="?", default="", help="analysis.json 路径（取 title）")
    ap.add_argument("--title", default="", help="手动指定标题")
    ap.add_argument("--output", default="")
    ap.add_argument("--calibrated", action="store_true",
                    help="优先使用 <transcript 同名>_calibrated.txt（校正稿）渲染；不存在则回退原稿")
    ap.add_argument("--theme", choices=["light", "dark"], default="dark",
                    help="初始主题：dark（默认，DESIGN-SPEC 深色）或 light")
    args = ap.parse_args()

    if not os.path.isfile(args.transcript):
        print(f"ERROR: 找不到 {args.transcript}", file=sys.stderr)
        sys.exit(1)

    # 可选：优先用校正稿（阅读体验更好）；默认仍用 ASR 原稿作存证
    src, source_note = args.transcript, "所有文字来自原始转写"
    if args.calibrated:
        base, ext = os.path.splitext(args.transcript)
        cand = base + "_calibrated" + ext
        if os.path.isfile(cand):
            src, source_note = cand, "基于校正稿渲染（已修正 ASR 常见错别字/断句）"
        else:
            print(f"WARN: 未找到 {cand}，回退使用原稿", file=sys.stderr)
    with open(src, "r", encoding="utf-8") as f:
        text = f.read()

    # Get title
    title = args.title
    if not title and args.analysis and os.path.isfile(args.analysis):
        with open(args.analysis, "r", encoding="utf-8") as f:
            data = json.load(f)
            title = data.get("title", "")
    if not title:
        title = "逐字稿"

    paragraphs = parse_transcript(text)
    if not paragraphs:
        print("ERROR: transcript 为空或格式不正确", file=sys.stderr)
        sys.exit(1)

    html_out = render_html(paragraphs, title, args.theme, source_note)
    out_path = args.output if args.output else f"{title}_阅读版.html"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html_out)
    sz = os.path.getsize(out_path)
    print(f"OK: {out_path}  ({sz:,} bytes)")
    print(f"   {len(paragraphs)} paragraphs, theme={args.theme}, source={'calibrated' if args.calibrated else 'raw'}")

if __name__ == "__main__":
    main()
