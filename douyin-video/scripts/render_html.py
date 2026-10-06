#!/usr/bin/env python3
"""render_html.py — analysis.json → 单文件可视化 HTML（摘要版）

8 种视觉组件混合排版：
  数据卡组 / 时间线 / 对比卡 / 配对卡 / 架构图 / 流程图 / 金句卡 / 清单行
设计令牌系统：深色默认（DESIGN-SPEC），--theme=light 回落亮色，全部走 CSS 变量。
零 JS、零外部资源、单文件可直接双击打开。摘要版不含逐字稿（校正稿以独立 txt 文件交付）。

用法:
  python3 render_html.py analysis.json [transcript.txt] [--clean] [--theme=dark|light]

  输出文件名自动 = <title>_摘要版.html。
  transcript.txt 参数仅为兼容保留（校验需要），不再内嵌进 HTML。
"""

import argparse, json, sys, html, os

# ── 泛词校验 ──
BAN_WORDS = ["转写", "视频文案", "内容整理", "transcript", "未命名", "视频转写", "文本整理"]

def validate_title(title):
    t = title.strip().lower()
    for w in BAN_WORDS:
        if w.lower() in t:
            print(f"ERROR: 标题含泛词「{w}」，必须用具体主题。修改 analysis.json 的 title 字段。", file=sys.stderr)
            sys.exit(1)

# ── 设计令牌（DESIGN-SPEC.md：深色主题 + 渐变红金 + 毛玻璃卡片 + 动效）──
# 令牌已内联进下方 ALL_CSS 的 :root（深色默认）与 body[data-theme="light"] 回落块，
# 此处不再保留独立副本（避免双份维护漂移）。

# ── CSS（DESIGN-SPEC.md：深色主题 + 毛玻璃 + 渐变 + 动效 + 响应式，零外部依赖）──
# 默认渲染走深色（DESIGN-SPEC 核心目标）。body 加 data-theme="light" 时回落亮色变量。
ALL_CSS = """
:root{
  --primary:#1a1a2e;--secondary:#16213e;--accent-deep:#0f3460;
  --highlight:#e94560;--gold:#f5c518;
  --text-light:#f0f0f0;--text-muted:#b0b0b0;
  --card-bg:rgba(255,255,255,0.06);--card-border:rgba(255,255,255,0.1);
  --radius:16px;--shadow:0 8px 32px rgba(0,0,0,0.3);
  /* 组件级语义变量（深色默认，亮色 override 见下） */
  --bg:#1a1a2e;--bg2:#16213e;--card:rgba(255,255,255,0.06);--card2:rgba(255,255,255,0.03);
  --line:rgba(255,255,255,0.1);--txt:#f0f0f0;--muted:#b0b0b0;--dim:#888;
  --accent:#e94560;--accent2:#00d9ff;--warn:#f5c518;--danger:#ff5c7a;--purple:#a78bfa;
  --grad-a:#e94560;--grad-b:#f5c518;--grad-c:#ff6b6b;
  --glow:rgba(233,69,96,0.4);
}
body[data-theme="light"]{
  --bg:#f5f7fc;--bg2:#ffffff;--card:#ffffff;--card2:#eef2fa;
  --line:#e2e8f4;--txt:#16203a;--muted:#55617a;--dim:#8b96ac;
  --accent:#2f6bff;--accent2:#0d9f7d;--warn:#d98400;--danger:#e11d48;--purple:#7c5cf0;
  --grad-a:#2f6bff;--grad-b:#f5c518;--grad-c:#ff6b6b;
  --shadow:0 1px 2px rgba(22,32,58,.04),0 10px 28px -14px rgba(22,32,58,.14);
  --glow:rgba(47,107,255,0.3);
}
*{box-sizing:border-box;margin:0;padding:0}
html{scroll-behavior:smooth;overflow-x:clip}
body{overflow-x:clip}
body{
  background:var(--bg);
  background-image:radial-gradient(1100px 600px at 12% -8%,rgba(233,69,96,.10),transparent 55%),radial-gradient(900px 500px at 100% 0%,rgba(0,217,255,.06),transparent 50%);
  background-attachment:fixed;
  color:var(--txt);
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif;
  line-height:1.8;-webkit-font-smoothing:antialiased;
}
/* 背景浮动粒子（DESIGN-SPEC §4.3，数量 6 个，z-index:-1） */
.bg-particles{position:fixed;inset:0;overflow:hidden;z-index:-1;pointer-events:none}
.bg-particles span{position:absolute;border-radius:50%;background:rgba(233,69,96,0.08);animation:float 20s infinite}
body[data-theme="light"] .bg-particles span{background:rgba(47,107,255,0.07)}
.bg-particles span:nth-child(1){width:300px;height:300px;left:8%;top:18%;animation-duration:24s}
.bg-particles span:nth-child(2){width:220px;height:220px;left:72%;top:12%;animation-delay:-4s;animation-duration:18s}
.bg-particles span:nth-child(3){width:360px;height:360px;left:40%;top:58%;animation-delay:-8s;animation-duration:26s}
.bg-particles span:nth-child(4){width:180px;height:180px;left:85%;top:70%;animation-delay:-12s;animation-duration:20s}
.bg-particles span:nth-child(5){width:260px;height:260px;left:5%;top:80%;animation-delay:-6s;animation-duration:22s}
.bg-particles span:nth-child(6){width:140px;height:140px;left:55%;top:35%;animation-delay:-14s;animation-duration:16s}
@keyframes float{
  0%,100%{transform:translateY(0) rotate(0deg);opacity:.6}
  33%{transform:translateY(-30px) rotate(120deg);opacity:.8}
  66%{transform:translateY(20px) rotate(240deg);opacity:.4}
}
@keyframes fadeInUp{from{opacity:0;transform:translateY(30px)}to{opacity:1;transform:translateY(0)}}
.wrap{max-width:1100px;margin:0 auto;padding:0 22px}
section{padding:80px 20px}
/* 导航栏（DESIGN-SPEC §3.1 毛玻璃） */
nav.site-nav{position:fixed;top:0;left:0;right:0;z-index:100;background:rgba(26,26,46,0.85);backdrop-filter:blur(12px);-webkit-backdrop-filter:blur(12px);border-bottom:1px solid var(--card-border);padding:12px 22px;display:flex;align-items:center;justify-content:space-between}
body[data-theme="light"] nav.site-nav{background:rgba(255,255,255,0.85)}
nav.site-nav .nav-logo{font-weight:800;font-size:15px;background:linear-gradient(135deg,var(--grad-a),var(--grad-b),var(--grad-c));-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text}
nav.site-nav .nav-links{display:flex;gap:18px;flex:1}
nav.site-nav .nav-links a{color:var(--text-muted, #b0b0b0);font-size:13px;text-decoration:none;font-weight:600;transition:color .2s}
nav.site-nav .nav-links a:hover{color:var(--accent)}
/* 主题切换按钮（DESIGN-SPEC：毛玻璃圆钮，导航栏最右侧=页面右上角，明暗随时切） */
nav.site-nav .theme-toggle{width:38px;height:38px;border-radius:50%;border:1px solid var(--card-border);background:var(--card);color:var(--muted);display:grid;place-items:center;cursor:pointer;transition:.25s;backdrop-filter:blur(6px);flex-shrink:0}
nav.site-nav .theme-toggle:hover{border-color:var(--accent);color:var(--accent);transform:scale(1.08)}
nav.site-nav .theme-toggle svg{width:18px;height:18px}
/* 明暗切换时的柔和过渡（body 背景色 + 文字色） */
body{transition:background-color .35s ease,color .35s ease}
/* Hero 首屏（DESIGN-SPEC §3.2） */
.hero{padding:120px 20px 64px;text-align:center;max-width:1100px;margin:0 auto;position:relative}
.hero .tagline{display:inline-block;font-size:12px;font-weight:800;letter-spacing:.14em;text-transform:uppercase;color:var(--accent);border:1px solid var(--accent);border-radius:100px;padding:5px 16px;margin-bottom:24px;animation:fadeInUp 1s ease 0.1s both}
.hero h1{font-size:clamp(32px,6vw,56px);font-weight:800;line-height:1.2;margin-bottom:18px;
  color:var(--grad-a);animation:fadeInUp 1s ease 0.25s both}
@supports (-webkit-background-clip:text) or (background-clip:text){.hero h1{background:linear-gradient(135deg,var(--grad-a),var(--grad-b),var(--grad-c));-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text}}
.hero .sub{font-size:17px;color:var(--muted);max-width:720px;margin:0 auto 32px;animation:fadeInUp 1s ease 0.4s both}
.hero .sub strong{color:var(--txt)}
.hero .scroll-hint{margin-top:40px;animation:fadeInUp 1s ease 0.7s both}
.hero .scroll-hint .arrow{display:block;width:22px;height:22px;margin:0 auto;color:var(--dim);animation:bounce 2s infinite}
@keyframes bounce{0%,20%,50%,80%,100%{transform:translateY(0)}40%{transform:translateY(-10px)}60%{transform:translateY(-5px)}}
/* 数据卡组（毛玻璃 + hover 上浮） */
.facts{display:flex;flex-wrap:wrap;justify-content:center;gap:18px;margin-top:36px;animation:fadeInUp 1s ease 0.55s both}
.fact{background:var(--card);border:1px solid var(--card-border);border-radius:var(--radius);padding:22px 30px;box-shadow:var(--shadow);min-width:0;flex:1 1 150px;max-width:240px;transition:transform .3s,box-shadow .3s,border-color .3s;display:flex;flex-direction:column;align-items:center;backdrop-filter:blur(10px);-webkit-backdrop-filter:blur(10px)}
.fact:hover{transform:translateY(-8px);box-shadow:0 16px 48px rgba(0,0,0,0.4);border-color:var(--accent)}
body[data-theme="light"] .fact:hover{box-shadow:0 16px 40px rgba(22,32,58,.15)}
.fact .fact-ico{width:34px;height:34px;border-radius:10px;display:grid;place-items:center;background:rgba(233,69,96,.14);color:var(--accent);margin-bottom:12px}
.fact.green .fact-ico{background:rgba(0,217,255,.12);color:var(--accent2)}
.fact.red .fact-ico{background:rgba(255,92,122,.12);color:var(--danger)}
.fact.warn .fact-ico{background:rgba(245,197,24,.14);color:var(--warn)}
.fact.purple .fact-ico{background:rgba(167,139,250,.14);color:var(--purple)}
.fact .fact-ico svg{width:17px;height:17px}
.fact b{display:block;font-size:30px;font-weight:800;color:var(--grad-a);line-height:1.1;
  background:linear-gradient(135deg,var(--grad-a),var(--grad-b));-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text}
.fact.green b{background:linear-gradient(135deg,var(--accent2),var(--grad-b));-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text}
.fact.red b{background:linear-gradient(135deg,var(--danger),var(--grad-c));-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text}
.fact.warn b{background:linear-gradient(135deg,var(--grad-b),#ff8c00);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text}
.fact.purple b{background:linear-gradient(135deg,var(--purple),var(--accent2));-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text}
.fact span{display:block;font-size:13px;color:var(--dim);margin-top:8px;font-weight:600;text-align:center}
/* 章节头 */
.sec-head{display:flex;align-items:center;gap:14px;margin-bottom:8px}
.sec-icon{width:42px;height:42px;border-radius:12px;display:grid;place-items:center;background:rgba(233,69,96,.12);color:var(--accent);flex-shrink:0;border:1px solid rgba(233,69,96,.3);backdrop-filter:blur(6px)}
body[data-theme="light"] .sec-icon{background:rgba(47,107,255,.08);color:var(--accent);border-color:rgba(47,107,255,.25)}
.sec-head h2{font-size:clamp(20px,3vw,26px);font-weight:800}
.sec-desc{color:var(--dim);font-size:14px;margin:0 0 26px 56px}
/* 通用毛玻璃卡片（DESIGN-SPEC §7.1） */
.std-card{background:var(--card);border:1px solid var(--card-border);border-radius:var(--radius);padding:24px 26px;box-shadow:var(--shadow);margin-bottom:16px;backdrop-filter:blur(10px);-webkit-backdrop-filter:blur(10px);transition:transform .3s,box-shadow .3s,border-color .3s;position:relative}
.std-card:hover{transform:translateY(-8px);box-shadow:0 16px 48px rgba(0,0,0,0.4);border-color:var(--accent)}
body[data-theme="light"] .std-card:hover{box-shadow:0 16px 40px rgba(22,32,58,.15)}
.std-card h4{font-size:16px;font-weight:700;margin-bottom:8px}
.std-card p{color:var(--muted);font-size:15px;margin-bottom:8px}
.std-card ul{list-style:none;padding-left:0}
.std-card li{padding:6px 0 6px 22px;position:relative;color:var(--muted);font-size:15px}
.std-card li::before{content:"";position:absolute;left:4px;top:15px;width:6px;height:6px;border-radius:50%;background:var(--accent);box-shadow:0 0 8px var(--glow)}
/* 时间线 */
.timeline{position:relative;padding-left:34px}
.timeline::before{content:"";position:absolute;left:9px;top:8px;bottom:8px;width:2px;background:linear-gradient(180deg,var(--grad-a),var(--grad-b),var(--grad-c));border-radius:2px;opacity:.55}
.tl-item{position:relative;margin-bottom:20px}
.tl-item::before{content:"";position:absolute;left:-31px;top:20px;width:12px;height:12px;border-radius:50%;background:var(--bg2);border:3px solid var(--accent);box-shadow:0 0 0 4px rgba(233,69,96,.14)}
.tl-icon{position:absolute;left:-40px;top:14px;width:22px;height:22px;border-radius:50%;background:var(--accent);color:#fff;display:grid;place-items:center;z-index:2}
.tl-icon svg{width:12px;height:12px}
.tl-item.warn::before{border-color:var(--warn);box-shadow:0 0 0 4px rgba(245,197,24,.14)}.tl-item.warn .tl-icon{background:var(--warn)}
.tl-item.danger::before{border-color:var(--danger);box-shadow:0 0 0 4px rgba(255,92,122,.14)}.tl-item.danger .tl-icon{background:var(--danger)}
.tl-item.good::before{border-color:var(--accent2);box-shadow:0 0 0 4px rgba(0,217,255,.14)}.tl-item.good .tl-icon{background:var(--accent2)}
.tl-card{background:var(--card);border:1px solid var(--card-border);border-radius:var(--radius);padding:20px 22px;transition:transform .25s,border-color .25s;box-shadow:var(--shadow);backdrop-filter:blur(10px)}
.tl-card:hover{border-color:var(--accent);transform:translateX(4px)}
.tl-year{font-size:12px;font-weight:800;letter-spacing:.1em;color:var(--accent);margin-bottom:4px}
.tl-item.warn .tl-year{color:var(--warn)}.tl-item.danger .tl-year{color:var(--danger)}.tl-item.good .tl-year{color:var(--accent2)}
.tl-card h3{font-size:16px;font-weight:700;margin-bottom:6px}
.tl-card p{color:var(--muted);font-size:14px}
/* 对比卡 */
.compare{display:grid;grid-template-columns:1fr 1fr;border:1px solid var(--card-border);border-radius:var(--radius);overflow:hidden;margin-top:16px;backdrop-filter:blur(10px);box-shadow:var(--shadow)}
.compare>div{padding:18px}
.compare .old{background:rgba(255,92,122,.06)}.compare .new{background:rgba(0,217,255,.06);border-left:1px solid var(--card-border)}
.compare h5{font-size:13px;font-weight:800;margin-bottom:10px;letter-spacing:.05em;text-transform:uppercase}
.compare .old h5{color:var(--danger)}.compare .new h5{color:var(--accent2)}
.compare ul{list-style:none;padding:0}
.compare li{position:relative;font-size:14px;color:var(--muted);padding:4px 0 4px 18px}
.compare .old li::before{content:"✕";position:absolute;left:0;color:var(--danger);font-size:12px;font-weight:700}
.compare .new li::before{content:"✓";position:absolute;left:0;color:var(--accent2);font-size:12px;font-weight:700}
/* 配对卡（痛点-解法） */
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:18px}
.card{background:var(--card);border:1px solid var(--card-border);border-radius:var(--radius);padding:22px;box-shadow:var(--shadow);backdrop-filter:blur(10px)}
.label{font-size:11.5px;font-weight:800;letter-spacing:.12em;padding:4px 10px;border-radius:100px;display:inline-block;margin-bottom:12px}
.label.pain{background:linear-gradient(135deg,rgba(255,92,122,.2),rgba(255,92,122,.08));color:var(--danger);border:1px solid rgba(255,92,122,.35)}
.label.fix{background:linear-gradient(135deg,rgba(0,217,255,.2),rgba(0,217,255,.08));color:var(--accent2);border:1px solid rgba(0,217,255,.35)}
.card h4{font-size:16px;font-weight:700;margin-bottom:8px}
.card p{color:var(--muted);font-size:14px;margin-bottom:8px}
.card .quote{border-left:3px solid var(--accent);padding:6px 0 6px 14px;margin-top:14px;color:var(--muted);font-style:italic;font-size:14px}
/* 架构图 */
.diagram{background:var(--card);border:1px solid var(--card-border);border-radius:22px;padding:34px 24px;box-shadow:var(--shadow);backdrop-filter:blur(10px)}
.diagram .you{text-align:center}
.diagram .you .pill{display:inline-block;padding:10px 26px;border-radius:100px;font-weight:800;background:linear-gradient(135deg,rgba(233,69,96,.15),rgba(245,197,24,.1));border:1px solid rgba(233,69,96,.4);color:var(--grad-b);font-size:15px}
.diagram .you small{display:block;color:var(--dim);font-size:12px;margin-top:4px}
.diagram .arrow-down{width:2px;height:26px;background:linear-gradient(var(--grad-a),var(--grad-b));margin:8px auto}
.diagram .connector{height:2px;background:var(--card-border);margin:0 16.6%;position:relative}
.diagram .connector::before,.diagram .connector::after{content:"";position:absolute;top:0;width:2px;height:20px;background:var(--card-border)}
.diagram .connector::before{left:0}.diagram .connector::after{right:0}
.diagram .cols{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin-top:20px}
.diagram .col{border-radius:var(--radius);padding:18px;border:1px solid var(--card-border);background:var(--card);box-shadow:var(--shadow);backdrop-filter:blur(8px)}
.diagram .col.safe{border-top:3px solid var(--accent)}.diagram .col.show{border-top:3px solid var(--purple)}.diagram .col.biz{border-top:3px solid var(--accent2)}
.diagram .col .role{font-size:11.5px;font-weight:800;letter-spacing:.1em;text-transform:uppercase;margin-bottom:6px;display:flex;align-items:center;gap:6px}
.diagram .col .role svg{width:14px;height:14px}
.diagram .col.safe .role{color:var(--accent)}.diagram .col.show .role{color:var(--purple)}.diagram .col.biz .role{color:var(--accent2)}
.diagram .col h4{font-size:15px;font-weight:700;margin-bottom:8px}
.diagram .col ul{list-style:none;padding:0}
.diagram .col li{font-size:13px;color:var(--muted);padding:3px 0 3px 14px;position:relative}
.diagram .col li::before{content:"\\b7";position:absolute;left:2px;font-weight:700}
.diagram .col .nope{margin-top:12px;font-size:12.5px;color:var(--danger);border-top:1px dashed var(--card-border);padding-top:10px}
.diagram .bottomnote{margin-top:22px;background:rgba(0,217,255,.06);border:1px solid rgba(0,217,255,.24);border-radius:12px;padding:16px 18px;font-size:14px;color:var(--muted)}
.diagram .bottomnote b{color:var(--txt)}
/* 流程图（DESIGN-SPEC §3.5：节点卡片 + 呼吸箭头，移动端纵向） */
.flow{display:flex;flex-wrap:wrap;align-items:center;gap:10px;justify-content:center}
.flow .node{background:var(--card);border:1px solid var(--card-border);border-radius:var(--radius);padding:12px 16px;min-width:0;flex:1 1 140px;max-width:260px;text-align:center;font-weight:700;font-size:15px;box-shadow:var(--shadow);backdrop-filter:blur(10px);transition:transform .3s,border-color .3s;line-height:1.45}
.flow .node:hover{transform:translateY(-4px);border-color:var(--accent)}
.flow .node small{display:block;color:var(--muted);font-weight:400;font-size:13.5px;margin-top:6px;line-height:1.5}
.flow .arr{color:var(--grad-b);font-size:20px;font-weight:800;animation:pulse 2s infinite}
@keyframes pulse{0%,100%{opacity:.4}50%{opacity:1}}
.flow .node.hl{background:linear-gradient(135deg,rgba(233,69,96,.16),rgba(245,197,24,.1));border-color:rgba(233,69,96,.45)}
.flow .node.hl2{background:linear-gradient(135deg,rgba(0,217,255,.14),rgba(245,197,24,.08));border-color:rgba(0,217,255,.4)}
/* 金句引用区（DESIGN-SPEC §3.6：渐变背景 + 大引号装饰 + 斜体） */
.quotes{display:grid;gap:16px;max-width:800px;margin:0 auto}
.qcard{background:linear-gradient(135deg,rgba(233,69,96,.1),rgba(245,197,24,.05));border:1px solid var(--card-border);border-left:4px solid var(--accent);border-radius:var(--radius);padding:22px 26px;box-shadow:var(--shadow);position:relative;backdrop-filter:blur(10px);transition:transform .3s}
.qcard:hover{transform:translateY(-4px)}
.qcard::before{content:"\\201c";position:absolute;top:-8px;left:14px;font-size:44px;font-family:Georgia,serif;color:var(--grad-a);opacity:.3;line-height:1}
.qcard:nth-child(2){border-left-color:var(--accent2)}.qcard:nth-child(2)::before{color:var(--accent2)}
.qcard:nth-child(3){border-left-color:var(--warn)}.qcard:nth-child(3)::before{color:var(--warn)}
.qcard:nth-child(4){border-left-color:var(--purple)}.qcard:nth-child(4)::before{color:var(--purple)}
.qcard p{font-size:17px;color:var(--txt);font-weight:600;line-height:1.65;font-style:italic}
.qcard small{display:block;color:var(--dim);margin-top:10px;font-size:13px}
/* 核心要点 */
.takeaway{display:flex;gap:14px;padding:16px 0;border-bottom:1px dashed var(--card-border)}
.takeaway:last-child{border-bottom:none}
.takeaway .ico{width:40px;height:40px;border-radius:12px;display:grid;place-items:center;background:rgba(233,69,96,.12);color:var(--accent);font-weight:800;font-size:14px;flex-shrink:0;border:1px solid rgba(233,69,96,.3)}
.takeaway .ico svg{width:18px;height:18px}
.takeaway .ico.green{background:rgba(0,217,255,.1);color:var(--accent2);border-color:rgba(0,217,255,.3)}
.takeaway .ico.red{background:rgba(255,92,122,.1);color:var(--danger);border-color:rgba(255,92,122,.3)}
.takeaway .ico.warn{background:rgba(245,197,24,.12);color:var(--warn);border-color:rgba(245,197,24,.35)}
.takeaway .ico.purple{background:rgba(167,139,250,.12);color:var(--purple);border-color:rgba(167,139,250,.3)}
.takeaway h4{font-size:15px;font-weight:700;margin-bottom:4px}
.takeaway p{color:var(--muted);font-size:14px}
/* 页脚 */
footer{padding:32px 0 48px;border-top:1px solid var(--card-border);color:var(--dim);font-size:13px;text-align:center}
footer p{margin:4px 0}
/* 响应式（DESIGN-SPEC §5：768px 断点，卡片单列、流程纵向箭头 90°） */
@media(max-width:768px){
  .grid2{grid-template-columns:1fr}
  .diagram .cols{grid-template-columns:1fr}
  .diagram .connector{display:none}
  .compare{grid-template-columns:1fr}
  .compare .new{border-left:none;border-top:1px solid var(--card-border)}
  .facts{gap:12px}
  .fact{padding:16px 22px}
  .fact b{font-size:26px}
  .hero{padding:90px 16px 40px}
  .hero h1{font-size:clamp(24px,7vw,36px)}
  .hero .sub{font-size:15px}
  .diagram{padding:24px 16px}
  section{padding:48px 16px}
  .sec-desc{margin-left:0}
  .flow{flex-direction:column;align-items:stretch}
  .flow .arr{transform:rotate(90deg);margin:2px auto}
  .flow .node{max-width:none}
  /* 导航栏移动端：隐藏中间链接，只留 logo + 主题按钮，按钮贴右 */
  nav.site-nav{padding:10px 16px}
  nav.site-nav .nav-links{display:none}
}
"""

# 亮色模式回落（保留 --theme light 可用；DESIGN-SPEC §8 配色替换指南）
LIGHT_CSS_OVERRIDE = """
body{background-image:radial-gradient(1100px 600px at 12% -8%,rgba(47,107,255,.13),transparent 55%),radial-gradient(900px 500px at 100% 0%,rgba(13,159,125,.10),transparent 50%)}
"""

def esc(s):
    return html.escape(str(s), quote=True)

def tone_class(tone):
    m = {"acc": "", "green": " green", "red": " red", "warn": " warn", "purple": " purple"}
    return m.get(tone, "")

# ── 内联 SVG 图标（全部 currentColor 继承设计系统颜色）──
ICONS = {
    "rocket":   '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4.5 16.5c-1.5 1.26-2 5-2 5s3.74-.5 5-2c.71-.84.7-2.13-.09-2.91a2.18 2.18 0 0 0-2.91-.09z"/><path d="m12 15-3-3a22 22 0 0 1 2-3.95A12.88 12.88 0 0 1 22 2c0 2.72-.78 7.5-6 11a22.35 22.35 0 0 1-4 2z"/><path d="M9 12H4s.55-3.03 2-4c1.62-1.08 5 0 5 0"/><path d="M12 15v5s3.03-.55 4-2c1.08-1.62 0-5 0-5"/></svg>',
    "compass":  '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><polygon points="16.24 7.76 14.12 14.12 7.76 16.24 9.88 9.88 16.24 7.76"/></svg>',
    "timeline": '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>',
    "scale":    '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v18"/><path d="m3 9 3-6h12l3 6"/><path d="M3 9h18"/><path d="M6 9l-3 6a3 3 0 0 0 6 0L6 9z"/><path d="M18 9l-3 6a3 3 0 0 0 6 0l-3-6z"/></svg>',
    "grid2":    '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="7" height="7" x="3" y="3" rx="1"/><rect width="7" height="7" x="14" y="3" rx="1"/><rect width="7" height="7" x="14" y="14" rx="1"/><rect width="7" height="7" x="3" y="14" rx="1"/></svg>',
    "building": '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 22V4a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v18Z"/><path d="M6 12H4a2 2 0 0 0-2 2v6a2 2 0 0 0 2 2h2"/><path d="M18 9h2a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2h-2"/><path d="M10 6h4"/><path d="M10 10h4"/><path d="M10 14h4"/><path d="M10 18h4"/></svg>',
    "flow":     '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="5" cy="6" r="3"/><circle cx="19" cy="18" r="3"/><path d="M5 9v3a4 4 0 0 0 4 4h6"/><path d="m18 12-3 3 3 3"/></svg>',
    "quote":    '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M16 3a2 2 0 0 0-2 2v6a2 2 0 0 0 2 2h1a1 1 0 0 1 1 1v3a1 1 0 0 1-1 1 1 1 0 0 0-1 1 1 1 0 0 1-1 1H7a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z"/><path d="M7 3a2 2 0 0 0-2 2v6a2 2 0 0 0 2 2h1a1 1 0 0 1 1 1v3a1 1 0 0 1-1 1 1 1 0 0 0-1 1 1 1 0 0 1-1 1"/></svg>',
    "list":     '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M8 6h13"/><path d="M8 12h13"/><path d="M8 18h13"/><path d="M3 6h.01"/><path d="M3 12h.01"/><path d="M3 18h.01"/></svg>',
    "alert":    '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><path d="M12 9v4"/><path d="M12 17h.01"/></svg>',
    "check":    '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><path d="m9 11 3 3L22 4"/></svg>',
    "x":        '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6 6 18"/><path d="M6 6l12 12"/></svg>',
    "shield":   '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/><path d="m9 12 2 2 4-4"/></svg>',
    "eye":      '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M2.062 12.348a1 1 0 0 1 0-.696 10.75 10.75 0 0 1 19.876 0 1 1 0 0 1 0 .696 10.75 10.75 0 0 1-19.876 0"/><circle cx="12" cy="12" r="3"/></svg>',
    "briefcase":'<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="20" height="14" x="2" y="7" rx="2"/><path d="M16 21V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16"/></svg>',
    "check2":   '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>',
    "footprint":'<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 16v-2.38C4 11.5 2.97 10.5 3 8c.03-2.72 1.49-6 4.5-6C9.37 2 10 3.8 10 5.5c0 2.12-.5 4-3 4"/><path d="M20 20v-2.38c0-2.12 1.03-3.12 1-5.62-.03-2.72-1.49-6-4.5-6C14.63 6 14 7.8 14 9.5c0 2.12.5 4 3 4"/><path d="M16 17h4"/><path d="M10 17H4"/><path d="M18 17v1a2 2 0 0 1-2 2h-4a2 2 0 0 1-2-2v-1"/><path d="M6 17v1a2 2 0 0 0 2 2h4a2 2 0 0 0 2-2v-1"/></svg>',
    "flag":     '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1z"/><line x1="4" x2="4" y1="22" y2="15"/></svg>',
    "heart":    '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 14c1.49-1.46 3-3.21 3-5.5A5.5 5.5 0 0 0 16.5 3c-1.76 0-3 .5-4.5 2-1.5-1.5-2.74-2-4.5-2A5.5 5.5 0 0 0 2 8.5c0 2.3 1.5 4.05 3 5.5l7 7Z"/></svg>',
}

# 章节类型→图标映射
SEC_ICON = {
    "timeline": "timeline", "compare": "scale", "pair": "grid2",
    "architecture": "building", "flow": "flow", "quote": "quote",
    "list": "list", "default": "compass",
}

# 状态→图标映射
STATUS_ICON = {
    "default": "footprint", "good": "check2", "warn": "alert", "danger": "x",
}

# 架构列类型→图标映射
COL_ICON = {"safe": "shield", "show": "eye", "biz": "briefcase"}

def render_hero(data):
    parts = []
    tone = data.get("tone", "")
    parts.append('<section class="hero" id="hero"><div class="wrap">')
    if tone:
        parts.append(f'<span class="tagline">{esc(tone)}</span>')
    title = data.get("title", "")
    parts.append(f"<h1>{esc(title)}</h1>")
    sub = data.get("summary", "")
    if sub:
        parts.append(f'<p class="sub">{esc(sub)}</p>')
    facts = data.get("hero_facts", [])
    if facts:
        fact_icons = ["rocket", "check", "flag", "heart"]
        parts.append('<div class="facts">')
        for i, f in enumerate(facts):
            tc = tone_class(f.get("tone", ""))
            ico_name = fact_icons[i % len(fact_icons)]
            parts.append(f'<div class="fact{tc}"><div class="fact-ico">{ICONS.get(ico_name,"")}</div><b>{esc(f.get("value",""))}</b><span>{esc(f.get("label",""))}</span></div>')
        parts.append('</div>')
    # 滚动指示器（DESIGN-SPEC §4.4）
    parts.append('<div class="scroll-hint"><svg class="arrow" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="m6 9 6 6 6-6"/></svg></div>')
    parts.append('</div></section>')
    return "\n".join(parts)

def render_section(sec, idx):
    parts = [f'<section id="sec{idx}"><div class="wrap">']
    stype = sec.get("type", "default")
    ico_key = SEC_ICON.get(stype, "compass")
    num = f"{idx + 1:02d}"
    parts.append(f'<div class="sec-head"><span class="sec-icon">{ICONS.get(ico_key,"")}</span><h2>{esc(sec.get("heading",""))}</h2></div>')
    desc = sec.get("desc", "")
    if desc:
        parts.append(f'<p class="sec-desc">{esc(desc)}</p>')
    stype = sec.get("type", "default")
    if stype == "timeline":
        parts.append(render_timeline(sec))
    elif stype == "compare":
        parts.append(render_compare(sec))
    elif stype == "pair":
        parts.append(render_pair(sec))
    elif stype == "architecture":
        parts.append(render_architecture(sec))
    elif stype == "flow":
        parts.append(render_flow(sec))
    elif stype == "quote":
        parts.append(render_quote_section(sec))
    elif stype == "list":
        parts.append(render_list_section(sec))
    else:
        parts.append(render_default_section(sec))
    parts.append('</div></section>')
    return "\n".join(parts)

def render_timeline(sec):
    items = sec.get("items", [])
    p = ['<div class="timeline">']
    for item in items:
        s = item.get("status", "default")
        cls = f"tl-item {s}" if s != "default" else "tl-item"
        ico_name = STATUS_ICON.get(s, "footprint")
        p.append(f'<div class="{cls}"><div class="tl-icon">{ICONS.get(ico_name,"")}</div><div class="tl-card">')
        if item.get("year"):
            p.append(f'<span class="tl-year">{esc(item["year"])}</span>')
        p.append(f'<h3>{esc(item.get("title",""))}</h3>')
        if item.get("desc"):
            p.append(f'<p>{esc(item["desc"])}</p>')
        p.append('</div></div>')
    p.append('</div>')
    return "\n".join(p)

def render_compare(sec):
    p = ['<div class="compare">']
    # h5 标题里的图标保留（用 x/check SVG 做标题前缀）；li 列表项依赖 CSS ::before 画的 ✕/✓，不再塞 SVG 避免双图标
    p.append(f'<div class="old"><h5>{ICONS.get("x","")}{esc(sec.get("old_title","原来的做法"))}</h5><ul>')
    for it in sec.get("old", []):
        p.append(f'<li>{esc(it)}</li>')
    p.append('</ul></div>')
    p.append(f'<div class="new"><h5>{ICONS.get("check","")}{esc(sec.get("new_title","更好的做法"))}</h5><ul>')
    for it in sec.get("new", []):
        p.append(f'<li>{esc(it)}</li>')
    p.append('</ul></div></div>')
    return "\n".join(p)

def render_pair(sec):
    p = ['<div class="grid2">']
    for i, item in enumerate(sec.get("pains", [])):
        p.append('<div class="card"><span class="label pain">痛点 ' + str(i+1) + '</span>')
        p.append(f'<h4>{esc(item.get("title",""))}</h4>')
        if item.get("desc"):
            p.append(f'<p>{esc(item["desc"])}</p>')
        if item.get("quote"):
            p.append(f'<div class="quote">"{esc(item["quote"])}"</div>')
        p.append('</div>')
    for i, item in enumerate(sec.get("fixes", [])):
        p.append('<div class="card"><span class="label fix">解法 ' + str(i+1) + '</span>')
        p.append(f'<h4>{esc(item.get("title",""))}</h4>')
        if item.get("desc"):
            p.append(f'<p>{esc(item["desc"])}</p>')
        if item.get("quote"):
            p.append(f'<div class="quote">"{esc(item["quote"])}"</div>')
        p.append('</div>')
    p.append('</div>')
    return "\n".join(p)

def render_architecture(sec):
    p = ['<div class="diagram">']
    p.append('<div class="you"><span class="pill">' + esc(sec.get("node_title","主体")) + '</span>')
    if sec.get("node_sub"):
        p.append(f'<small>{esc(sec["node_sub"])}</small>')
    p.append('</div><div class="arrow-down"></div><div class="connector"></div><div class="cols">')
    ct = ["safe","show","biz"]
    for i, col in enumerate(sec.get("cols", [])):
        p.append(f'<div class="col {ct[i%3]}">')
        col_ico = COL_ICON.get(ct[i%3], "briefcase")
        p.append(f'<span class="role">{ICONS.get(col_ico,"")}{esc(col.get("role",""))}</span>')
        p.append(f'<h4>{esc(col.get("title",""))}</h4>')
        if col.get("items"):
            p.append('<ul>')
            for it in col["items"]:
                p.append(f'<li>{esc(it)}</li>')
            p.append('</ul>')
        if col.get("nope"):
            p.append(f'<div class="nope">\u2715 {esc(col["nope"])}</div>')
        p.append('</div>')
    p.append('</div>')
    if sec.get("bottom_note"):
        p.append(f'<div class="bottomnote"><b>关键机制：</b>{esc(sec["bottom_note"])}</div>')
    p.append('</div>')
    return "\n".join(p)

def render_flow(sec):
    p = ['<div class="flow">']
    steps = sec.get("steps", [])
    for i, step in enumerate(steps):
        cls = "node"
        if step.get("highlight") == "start": cls = "node hl"
        elif step.get("highlight") == "end": cls = "node hl2"
        p.append(f'<div class="{cls}">{esc(step.get("title",""))}')
        if step.get("sub"):
            p.append(f'<small>{esc(step["sub"])}</small>')
        p.append('</div>')
        if i < len(steps)-1:
            p.append('<span class="arr">→</span>')
    p.append('</div>')
    return "\n".join(p)

def render_quote_section(sec):
    cards = sec.get("cards", [])
    if not cards:
        cards = [{"text": it.get("title",""), "source": it.get("desc","")} for it in sec.get("items",[])]
    p = ['<div class="quotes">']
    for c in cards:
        p.append('<div class="qcard"><p>"' + esc(c.get("text","")) + '"</p>')
        if c.get("source"):
            p.append(f'<small>{esc(c["source"])}</small>')
        p.append('</div>')
    p.append('</div>')
    return "\n".join(p)

def render_list_section(sec):
    items = sec.get("items", [])
    tones = ["","green","red","warn","purple"]
    p = ['<div>']
    for i, item in enumerate(items):
        tc = tones[i % len(tones)]
        cls = f"ico {tc}" if tc else "ico"
        p.append('<div class="takeaway"><div class="' + cls + '">' + f'{i+1:02d}' + '</div><div>')
        p.append(f'<h4>{esc(item.get("title",""))}</h4>')
        if item.get("desc"):
            p.append(f'<p>{esc(item["desc"])}</p>')
        p.append('</div></div>')
    p.append('</div>')
    return "\n".join(p)

def render_default_section(sec):
    p = []
    items = sec.get("content", []) or sec.get("items", [])
    if isinstance(items, str):
        items = [items]
    for item in items:
        if isinstance(item, dict):
            p.append('<div class="std-card">')
            if item.get("title"):
                p.append(f'<h4>{esc(item["title"])}</h4>')
            if item.get("desc"):
                p.append(f'<p>{esc(item["desc"])}</p>')
            p.append('</div>')
        else:
            p.append(f'<div class="std-card"><p>{esc(item)}</p></div>')
    if sec.get("key_points"):
        kps = sec["key_points"]
        if isinstance(kps, str):
            kps = [kps]
        p.append('<div class="std-card"><ul>')
        for kp in kps:
            p.append(f'<li>{esc(kp)}</li>')
        p.append('</ul></div>')
    return "\n".join(p)

def render_key_takeaways(data):
    tks = data.get("key_takeaways", [])
    if not tks:
        return ""
    tones = ["","green","red","warn","purple"]
    p = ['<section id="takeaways"><div class="wrap"><div class="sec-head"><span class="sec-icon">' + ICONS.get("list","") + '</span><h2>核心要点</h2></div>']
    for i, ta in enumerate(tks):
        if isinstance(ta, dict):
            title = ta.get("title", ta.get("text",""))
            desc = ta.get("desc", ta.get("source",""))
        else:
            title, desc = ta, ""
        tc = tones[i % len(tones)]
        cls = f"ico {tc}" if tc else "ico"
        p.append('<div class="takeaway"><div class="' + cls + '">' + f'{i+1:02d}' + '</div><div>')
        p.append(f'<h4>{esc(title)}</h4>')
        if desc:
            p.append(f'<p>{esc(desc)}</p>')
        p.append('</div></div>')
    p.append('</div></section>')
    return "\n".join(p)

def render_conclusion(data):
    c = data.get("conclusion", {})
    if not c:
        return ""
    cards = c.get("cards", [])
    if not cards and c.get("quote"):
        cards = [{"text": c["quote"], "source": c.get("source","")}]
    if not cards:
        return ""
    p = ['<section id="quotes"><div class="wrap"><div class="sec-head"><span class="sec-icon">' + ICONS.get("quote","") + '</span><h2>金句</h2></div>']
    p.append(render_quote_section({"cards": cards}))
    p.append('</div></section>')
    return "\n".join(p)

def render_footer(data):
    p = ['<footer><div class="wrap">']
    cal = data.get("footer", {}).get("calibration", "")
    if cal:
        p.append(f'<p><b>校正说明：</b>{esc(cal)}</p>')
    ents = data.get("entities", [])
    if ents:
        p.append(f'<p><b>实体：</b>{"、".join(esc(e) for e in ents)}</p>')
    p.append('<p style="margin-top:12px">由视频文案提取 skill 生成 · 校正稿以随附 txt 文件交付 · 所有数字与引语来自原始转写</p>')
    p.append('</div></footer>')
    return "\n".join(p)

def render_html(data, theme):
    validate_title(data.get("title",""))
    css = ALL_CSS
    if theme == "light":
        css = css + LIGHT_CSS_OVERRIDE
    # 导航锚点：hero / 各 section + 右上角主题切换按钮（按钮放在 nav-links 外，靠 flex:1 推到最右）
    nav_links = [("hero", "首屏")]
    if data.get("sections"):
        nav_links.append(("sec0", "目录"))
    nav_html = '<nav class="site-nav"><div class="nav-logo">视频文案 · 可视化</div>'
    nav_html += '<div class="nav-links">'
    for nid, nlabel in nav_links:
        nav_html += f'<a href="#{nid}">{esc(nlabel)}</a>'
    nav_html += '</div>'
    # 主题切换按钮（太阳/月亮 SVG，点一下换明暗；默认深色 → 显示太阳=切亮）
    sun_icon = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41"/></svg>'
    nav_html += f'<button class="theme-toggle" id="themeToggle" onclick="toggleTheme()" title="切换明/暗主题" aria-label="切换明暗主题">{sun_icon}</button>'
    nav_html += '</nav>'
    theme_attr = f'data-theme="{theme}"' if theme == "light" else ""
    parts = [f'<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">']
    parts.append('<meta name="viewport" content="width=device-width, initial-scale=1.0">')
    parts.append(f'<title>{esc(data.get("title",""))}</title><style>{css}</style></head><body {theme_attr}>')
    # 背景粒子（DESIGN-SPEC §4.3）
    parts.append('<div class="bg-particles"><span></span><span></span><span></span><span></span><span></span><span></span></div>')
    parts.append(nav_html)
    parts.append(render_hero(data))
    parts.append('<main>')
    for i, sec in enumerate(data.get("sections", [])):
        parts.append(render_section(sec, i))
    kt = render_key_takeaways(data)
    if kt:
        parts.append(kt)
    cl = render_conclusion(data)
    if cl:
        parts.append(cl)
    parts.append('</main>')
    parts.append(render_footer(data))
    # 主题切换 JS（明暗随时切，偏好存 localStorage，与阅读版一致）
    parts.append(
        '<script>'
        'function toggleTheme(){'
        '  var b=document.body;'
        '  var isDark=b.getAttribute("data-theme")!=="light";'
        '  b.setAttribute("data-theme",isDark?"light":"dark");'
        '  updateToggleIcon();'
        '  try{localStorage.setItem("dsh_theme",isDark?"light":"dark")}catch(e){}'
        '}'
        'function updateToggleIcon(){'
        '  var btn=document.getElementById("themeToggle");'
        '  if(!btn)return;'
        '  var isDark=document.body.getAttribute("data-theme")!=="light";'
        '  var sun=btn.querySelector("svg");'
        '  var moon=document.createElement("span");'
        '  btn.innerHTML=isDark?'
        '"<svg viewBox=\\"0 0 24 24\\" fill=\\"none\\" stroke=\\"currentColor\\" stroke-width=\\"2\\"><path d=\\"M21 12.79A9 9 0 1 1 11.21 3a7 7 0 0 0 9.79 9.79z\\"/></svg>"'
        ':"<svg viewBox=\\"0 0 24 24\\" fill=\\"none\\" stroke=\\"currentColor\\" stroke-width=\\"2\\"><circle cx=\\"12\\" cy=\\"12\\" r=\\"4\\"/><path d=\\"M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41\\"/></svg>";'
        '  btn.title=isDark?"切换到亮色":"切换到暗色";'
        '}'
        'document.addEventListener("DOMContentLoaded",function(){'
        '  try{var t=localStorage.getItem("dsh_theme");'
        '    if(t==="dark"){document.body.removeAttribute("data-theme");}'
        '    else if(t==="light"){document.body.setAttribute("data-theme","light");}'
        '  }catch(e){}'
        '  updateToggleIcon();'
        '});'
        '</script>'
    )
    parts.append('</body></html>')
    return "\n".join(parts)

def main():
    ap = argparse.ArgumentParser(description="analysis.json → 单文件可视化 HTML（摘要版，不含逐字稿）")
    ap.add_argument("analysis", help="analysis.json 路径")
    ap.add_argument("transcript", nargs="?", default="", help="transcript.txt 路径（仅用于校验，不内嵌）")
    ap.add_argument("--theme", choices=["light","dark"], default="dark",
                    help="默认 dark（DESIGN-SPEC 深色主题）；light 为回落亮色")
    ap.add_argument("--output", default="")
    args = ap.parse_args()
    if not os.path.isfile(args.analysis):
        print(f"ERROR: 找不到 {args.analysis}", file=sys.stderr)
        sys.exit(1)
    with open(args.analysis, "r", encoding="utf-8") as f:
        data = json.load(f)
    # 自检：调用统一 schema 校验器（发现 ERROR 直接拒绝渲染，保证任意调用方一致）
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    try:
        import validate_analysis as VA
        tx0 = ""
        if args.transcript and os.path.isfile(args.transcript):
            with open(args.transcript, encoding="utf-8") as f:
                tx0 = f.read()
        r = VA.validate(data, tx0)
        for e in r.errors:
            print(f"ERROR: {e}", file=sys.stderr)
        for w in r.warns:
            print(f"WARN : {w}", file=sys.stderr)
        if r.errors:
            sys.exit(1)
    except ImportError:
        pass
    # 逐字稿一律不内嵌（用户要求：摘要版不带逐字稿）；逐字稿以独立 txt 文件交付
    html_out = render_html(data, args.theme)
    title = data.get("title", "output")
    out_path = args.output if args.output else f"{title}_摘要版.html"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html_out)
    sz = os.path.getsize(out_path)
    nsec = len(data.get("sections", []))
    nkt = len(data.get("key_takeaways", []))
    print(f"OK: {out_path}  ({sz:,} bytes)")
    print(f"   {nsec} sections, {nkt} takeaways, theme={args.theme}, 摘要版（不含逐字稿）")

if __name__ == "__main__":
    main()
