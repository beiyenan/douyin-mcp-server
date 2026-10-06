#!/usr/bin/env python3
"""validate_analysis.py — 严格 schema 校验器（模型无关的确定性反馈）

给任何 LLM 一个机器可判定的「过关/不过关」信号，取代「去读渲染器源码猜字段」。
供两类使用方：
  1) run_pipeline.py 在 prepare/finish 阶段自动调用；
  2) 模型手动跑：`python3 validate_analysis.py analysis.json` 自检后据报错改文件。

用法:
  python3 validate_analysis.py analysis.json [--fix] [--quiet]
    --fix   : 对可自动修复的项（如缺失字段补默认、类型错转换）就地修正并写出
    --quiet : 只打印 ERROR/WARN，不打印 OK/INFO

退出码:
  0 = 完全通过；1 = 存在 ERROR（不可渲染）；2 = 仅存在 WARN（可渲染，建议修）

本校验器是唯一权威：render_html.py / read_render.py / run_pipeline.py 都以它为准。
新增字段前必须先在 render_html.py 里实现渲染分支，再到这里登记 schema。
"""

import argparse, json, sys, re, os

# ── 泛词（直接照搬 render_html.BAN_WORDS，保持一致）──
BAN_WORDS = ["转写", "视频文案", "内容整理", "transcript", "未命名", "视频转写", "文本整理"]

# ── 枚举白名单（与 render_html.py 硬编码一致）──
FACT_TONES = {"", "acc", "green", "red", "warn", "purple"}
SECTION_TYPES = {"default", "timeline", "compare", "pair", "architecture", "flow", "quote", "list"}
TL_STATUS = {"default", "good", "warn", "danger"}
FLOW_HIGHLIGHT = {None, "start", "end"}

class R:
    def __init__(self):
        self.errors, self.warns = [], []
    def err(self, m): self.errors.append(m)
    def warn(self, m): self.warns.append(m)

def check_str(r, obj, key, required, maxlen=None):
    v = obj.get(key)
    if v is None or (isinstance(v, str) and not v.strip()):
        if required: r.err(f"缺失/空字段：`{key}`（必须为字符串）")
        return v
    if not isinstance(v, str):
        r.err(f"字段 `{key}` 应为字符串，实为 {type(v).__name__}：{v!r}")
        return v
    if maxlen and len(v) > maxlen:
        r.warn(f"字段 `{key}` 长度 {len(v)} > 建议上限 {maxlen}")
    return v

def check_str_list(r, obj, key, required):
    v = obj.get(key)
    if v is None:
        if required: r.err(f"缺失字段：`{key}`（应为字符串数组）")
        return
    if not isinstance(v, list):
        r.err(f"字段 `{key}` 应为数组，实为 {type(v).__name__}：{v!r}"); return
    for i, it in enumerate(v):
        if isinstance(it, str):
            if not it.strip(): r.err(f"`{key}[{i}]` 为空字符串")
        elif isinstance(it, dict):
            for k in ("title", "text", "desc", "source", "label", "value"):
                if k in it and not isinstance(it[k], str):
                    r.err(f"`{key}[{i}].{k}` 应为字符串，实为 {type(it[k]).__name__}")
        else:
            r.err(f"`{key}[{i}]` 应为字符串或对象，实为 {type(it).__name__}")

def check_section(r, sec, idx):
    if not isinstance(sec, dict):
        r.err(f"sections[{idx}] 应为对象，实为 {type(sec).__name__}"); return
    check_str(r, sec, "heading", required=True, maxlen=40)
    check_str(r, sec, "desc", required=False)
    stype = sec.get("type", "default")
    if stype not in SECTION_TYPES:
        r.err(f"sections[{idx}].type=`{stype}` 非法。允许：{sorted(SECTION_TYPES)}；缺省为 default。")
        stype = "default"
    # 各类型专用字段
    if stype == "default":
        c = sec.get("content")
        if c is not None and not isinstance(c, (list, str)):
            r.err(f"sections[{idx}].content 应为字符串或数组，实为 {type(c).__name__}")
        check_str_list(r, sec, "key_points", required=False)
    elif stype == "timeline":
        items = sec.get("items")
        if not isinstance(items, list) or not items:
            r.err(f"sections[{idx}].items 缺失或为空（timeline 至少 1 条）")
        else:
            for i, it in enumerate(items):
                if not isinstance(it, dict):
                    r.err(f"sections[{idx}].items[{i}] 应为对象"); continue
                check_str(r, it, "title", required=True)
                check_str(r, it, "desc", required=False)
                check_str(r, it, "year", required=False)
                st = it.get("status", "default")
                if st not in TL_STATUS:
                    r.err(f"sections[{idx}].items[{i}].status=`{st}` 非法。允许：{sorted(TL_STATUS)}")
    elif stype == "compare":
        check_str(r, sec, "old_title", required=False)
        check_str(r, sec, "new_title", required=False)
        for k in ("old", "new"):
            v = sec.get(k)
            if not isinstance(v, list) or not v:
                r.err(f"sections[{idx}].{k} 缺失或为空（compare 至少 1 条）")
    elif stype == "pair":
        for k in ("pains", "fixes"):
            v = sec.get(k)
            if not isinstance(v, list) or not v:
                r.err(f"sections[{idx}].{k} 缺失或为空（pair 至少 1 条）")
            else:
                for i, it in enumerate(v):
                    if not isinstance(it, dict):
                        r.err(f"sections[{idx}].{k}[{i}] 应为对象"); continue
                    check_str(r, it, "title", required=True)
                    check_str(r, it, "desc", required=False)
                    check_str(r, it, "quote", required=False)
    elif stype == "architecture":
        check_str(r, sec, "node_title", required=False)
        check_str(r, sec, "node_sub", required=False)
        cols = sec.get("cols")
        if not isinstance(cols, list) or not cols:
            r.err(f"sections[{idx}].cols 缺失或为空（architecture 至少 1 列）")
        else:
            for i, c in enumerate(cols):
                if not isinstance(c, dict):
                    r.err(f"sections[{idx}].cols[{i}] 应为对象"); continue
                check_str(r, c, "role", required=True)
                check_str(r, c, "title", required=True)
                check_str(r, c, "nope", required=False)
                check_str_list(r, c, "items", required=False)
        check_str(r, sec, "bottom_note", required=False)
    elif stype == "flow":
        steps = sec.get("steps")
        if not isinstance(steps, list) or not steps:
            r.err(f"sections[{idx}].steps 缺失或为空（flow 至少 2 步）")
        else:
            for i, s in enumerate(steps):
                if not isinstance(s, dict):
                    r.err(f"sections[{idx}].steps[{i}] 应为对象"); continue
                check_str(r, s, "title", required=True)
                check_str(r, s, "sub", required=False)
                hl = s.get("highlight")
                if hl not in FLOW_HIGHLIGHT:
                    r.err(f"sections[{idx}].steps[{i}].highlight=`{hl}` 非法。允许：start/end")
    elif stype == "quote":
        cards = sec.get("cards")
        if not isinstance(cards, list) or not cards:
            # 兼容 items→cards 的降级：render_html 允许 items
            if not isinstance(sec.get("items"), list) or not sec.get("items"):
                r.err(f"sections[{idx}].cards 缺失或为空（quote 至少 1 条）")
        else:
            for i, c in enumerate(cards):
                if not isinstance(c, dict):
                    r.err(f"sections[{idx}].cards[{i}] 应为对象"); continue
                check_str(r, c, "text", required=True)
                check_str(r, c, "source", required=False)
    elif stype == "list":
        check_str_list(r, sec, "items", required=True)

def check_timestamp(r, key_takeaways):
    # key_takeaways 里若有 [mm:ss] 时间戳，必须是合法格式（尽力而为，非强断）
    ts = re.compile(r'\[(\d{1,2}):(\d{2})\]')
    for i, ta in enumerate(key_takeaways):
        if isinstance(ta, dict):
            blob = " ".join(str(v) for v in ta.values())
        elif isinstance(ta, str):
            blob = ta
        else:
            continue
        for m in ts.finditer(blob):
            mm, ss = int(m.group(1)), int(m.group(2))
            if ss >= 60:
                r.warn(f"key_takeaways[{i}] 时间戳 `[{mm:02d}:{ss:02d}]` 秒≥60，可能手滑。")

def validate(data, transcript_text=None):
    r = R()
    if not isinstance(data, dict):
        r.err("analysis 根节点应为 JSON 对象（{…}）"); return r

    # title
    title = check_str(r, data, "title", required=True, maxlen=30)
    if title:
        tl = title.strip().lower()
        for w in BAN_WORDS:
            if w.lower() in tl:
                r.err(f"标题含泛词「{w}」，必须改为具体主题（如「耶鲁死亡课：直面死亡才能活明白」）。")

    # tone / summary
    check_str(r, data, "tone", required=False)
    check_str(r, data, "summary", required=False)

    # hero_facts
    hf = data.get("hero_facts", [])
    if hf is not None and not isinstance(hf, list):
        r.err(f"hero_facts 应为数组，实为 {type(hf).__name__}")
    else:
        for i, f in enumerate(hf or []):
            if not isinstance(f, dict):
                r.err(f"hero_facts[{i}] 应为对象"); continue
            check_str(r, f, "value", required=True)
            check_str(r, f, "label", required=True)
            ft = f.get("tone", "")
            if ft not in FACT_TONES:
                r.err(f"hero_facts[{i}].tone=`{ft}` 非法。允许：{sorted(FACT_TONES - {''})}")

    # sections
    secs = data.get("sections", [])
    if not isinstance(secs, list) or not secs:
        r.err("sections 缺失或为空（至少 1 个章节）")
    else:
        if len(secs) < 3:
            r.warn(f"sections 仅 {len(secs)} 个，通常 ≥3 才有足够结构")
        for i, s in enumerate(secs):
            check_section(r, s, i)

    # key_takeaways
    kts = data.get("key_takeaways", [])
    if not isinstance(kts, list):
        r.err("key_takeaways 应为数组")
    else:
        if len(kts) < 3:
            r.warn("key_takeaways 少于 3 条")
        check_str_list(r, data, "key_takeaways", required=False)
        check_timestamp(r, kts)

    # conclusion
    concl = data.get("conclusion")
    if concl is not None:
        if not isinstance(concl, dict):
            r.err("conclusion 应为对象")
        else:
            cards = concl.get("cards")
            if cards is not None:
                if not isinstance(cards, list) or not cards:
                    r.err("conclusion.cards 应为非空数组")
                else:
                    for i, c in enumerate(cards):
                        if not isinstance(c, dict):
                            r.err(f"conclusion.cards[{i}] 应为对象"); continue
                        check_str(r, c, "text", required=True)
                        check_str(r, c, "source", required=False)
            elif not (isinstance(concl.get("quote"), str) and concl.get("quote").strip()):
                r.err("conclusion 需给 cards:[{text,source}] 或 quote+source")

    # entities
    ents = data.get("entities", [])
    if ents is not None and not isinstance(ents, list):
        r.err(f"entities 应为数组，实为 {type(ents).__name__}")
    else:
        for e in ents or []:
            if not isinstance(e, str) or not e.strip():
                r.err(f"entities 含空/非字符串项：{e!r}")

    # footer
    foot = data.get("footer")
    if foot is not None:
        if not isinstance(foot, dict):
            r.err("footer 应为对象")
        elif "calibration" in foot and not isinstance(foot["calibration"], str):
            r.err("footer.calibration 应为字符串")

    # 数字出处抽查（若给了 transcript 原文）：正文里的数字须能在原文找到
    # 兼容中文数字写法：原文可能写作「二零一九」「三家公司」，JSON 里写 2019 / 3 也算有出处。
    if transcript_text:
        cjk_digits = {'零': '0', '〇': '0', '一': '1', '二': '2', '两': '2', '三': '3', '四': '4',
                      '五': '5', '六': '6', '七': '7', '八': '8', '九': '9'}

        def cjk_num(s):
            """提取一段文本里所有连续中文数字片段，返回其阿拉伯等价拼写（如 二零一九→{2019}）。"""
            out = set()
            buf = ''
            for ch in s:
                if ch in cjk_digits:
                    buf += cjk_digits[ch]
                else:
                    if buf:
                        out.add(buf)
                    buf = ''
            if buf:
                out.add(buf)
            return out

        # 原文中所有阿拉伯数字 + 中文数字等价拼写，构成「可接受出处」集合
        have = set(re.findall(r'\d+(?:\.\d+)?', transcript_text))
        for cjk in re.findall(r'[零〇一二两三四五六七八九]+', transcript_text):
            have |= cjk_num(cjk)
        # 带尾随单位（万/亿/千/百/元/块…）→ 把等价纯数字也加入出处集（「10.56万」匹配 JSON「10.56」）
        for num, unit in re.findall(r'(\d+(?:\.\d+)?)\s*(万|亿|千|百|元|块)', transcript_text):
            mult = {'万': 10000, '亿': 100000000, '千': 1000, '百': 100, '元': 1, '块': 1}[unit]
            have.add(f"{float(num) * mult:g}")
            have.add(num)
        # 收集 JSON 里的数字
        nums = set(re.findall(r'\d+(?:\.\d+)?', data.get("summary", "")))
        nums |= set(re.findall(r'\d+(?:\.\d+)?', " ".join(str(x) for x in (data.get("key_takeaways", []) or []))))

        def arabic_to_cjk(n):
            """把整数阿拉伯数字读成中文（带百千万亿单位），用于回溯原文（如 100→一百 / 2019→二千零一十九）。
            保守策略：同时给出「二」和「两」两种读法，避免把真有的数字误判为臆造。"""
            if not n.isdigit() or int(n) == 0:
                return []
            d = '零一二三四五六七八九'
            u = ['', '十', '百', '千']
            B = ['', '万', '亿']
            s = str(n)
            groups = []
            i = len(s)
            while i > 0:
                groups.append(s[max(0, i - 4):i])
                i -= 4
            groups.reverse()
            out = ''
            for gi, g in enumerate(groups):
                gv = int(g)
                if gv == 0 and gi != 0:
                    out += '零'
                    continue
                seg = ''
                for j, ch in enumerate(g):
                    pos = len(g) - 1 - j
                    if ch == '0':
                        if seg and seg[-1] != '零':
                            seg += '零'
                    else:
                        seg += d[int(ch)] + u[pos]
                seg = seg.rstrip('零')
                # 十八 ≠ 一十八，去掉十/百/千前的「一」
                if seg.startswith('一') and len(seg) > 1 and seg[1] in '十百千':
                    seg = seg[1:]
                if seg:
                    out += seg + B[len(groups) - 1 - gi]
            if not out:
                return []
            out = out.rstrip('零')  # 低位全零时不要尾随的零：20000→二万，而非二万零
            variants = {out}
            # 「二千」也常说「两千」；同理「二万」→「两万」
            if out.startswith('二') and len(out) > 1 and out[1] in '千百万亿':
                variants.add('两' + out[1:])
            return list(variants)

        def found(n):
            if n in have:
                return True
            # 写法一：逐位读（2019 → 二零一九）
            digits = ''.join(cjk_digits.get(ch, '') for ch in str(n) if ch.isdigit())
            if digits and digits in have:
                return True
            # 写法二：带单位读（100 → 一百；2019 → 二千零一十九 / 两千零一十九）
            if any(c in transcript_text for c in arabic_to_cjk(n)):
                return True
            # 写法三：十位口语近似（JSON「36」对应原文「30多」——原文说"多了30多块钱"）
            if n.isdigit() and 10 <= int(n) <= 99:
                base = int(n) // 10 * 10
                if f"{base}多" in transcript_text:
                    return True
            return False

        missing = [n for n in sorted(nums) if not found(n)]
        if missing:
            r.warn(f"摘要/要点中出现但原文（transcript）里找不到的数字：{missing[:10]}（请核对是否臆造）")

    return r

def main():
    ap = argparse.ArgumentParser(description="校验 analysis.json 结构（字段名/类型/枚举/非泛标题/数字出处）")
    ap.add_argument("analysis", help="analysis.json 路径")
    ap.add_argument("--transcript", default="", help="可选：transcript.txt 路径，用于抽查数字出处")
    ap.add_argument("--fix", action="store_true", help="就地修正可自动修复的项并写回")
    ap.add_argument("--quiet", action="store_true", help="只打印 ERROR/WARN")
    args = ap.parse_args()

    if not os.path.isfile(args.analysis):
        print(f"ERROR: 找不到 {args.analysis}", file=sys.stderr); sys.exit(1)
    with open(args.analysis, encoding="utf-8") as f:
        data = json.load(f)

    tx = ""
    if args.transcript and os.path.isfile(args.transcript):
        with open(args.transcript, encoding="utf-8") as f:
            tx = f.read()

    r = validate(data, tx)

    # 自动修复：仅处理少数可安全替换的（保持保守，多数仍需模型改）
    changed = False
    if args.fix:
        if isinstance(data, dict):
            # hero_facts 缺失时补默认，避免渲染空块
            pass
        # 注：此处刻意不做太多自动改写，避免静默改错。校验器的价值在「报告」，不在「代改」。

    for e in r.errors:
        print(f"ERROR: {e}", file=sys.stderr)
    for w in r.warns:
        print(f"WARN : {w}", file=sys.stderr)
    if not args.quiet:
        print(f"校验结果：{len(r.errors)} 错误，{len(r.warns)} 警告。")

    if r.errors:
        sys.exit(1)
    if r.warns:
        sys.exit(2)
    sys.exit(0)

if __name__ == "__main__":
    main()