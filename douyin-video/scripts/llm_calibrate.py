#!/usr/bin/env python3
"""llm_calibrate.py — 用智谱 GLM 对 ASR 转写稿做「机器校正」，产出校正稿 + 可审计改动清单。

设计定位：这是第 4a 步（校正）的**预筛**。LLM 只做高置信度修正并逐条登记，
主模型（终审）只需要读 report 里的 changes 逐条 accept/reject，
不必再逐字精读全文重写——把校正耗时从几分钟压到 1 分钟内。

用法:
  python3 llm_calibrate.py <transcript.txt> <out_calibrated.txt> \
      [--report report.json] [--model glm-4.7] [--workers 3] [--max-chars 2500]

- key: 环境变量 ZHIPU_API_KEY，否则读 ~/.dsh/secrets/zhipu_api_key（600 权限）
- 端点: 智谱 OpenAI 兼容 /chat/completions（默认关闭思考模式，快且省）
- 校正红线（写死在 prompt 里）:
    只改高置信度的同音字/专名/数字规范/ASR 断句碎句；
    成语/典故/惯用语一律不改（疑似时标 low 保留原文，由终审判）；
    不改观点、不改数字量级、不添加原文没有的事实；不确定就不改（confidence=low 仅供终审参考）
- 术语表跨块滚动累积（glossary_add），保证同一专名前后块写法一致
- 每块响应缓存到 <out>.calib_cache/，支持断点重跑（输入 hash 变了自动重算）
- 并发 --workers（默认 3）；单块失败重试 3 次，仍失败则该块保留原文
- 退出码: 0 全部成功 | 2 部分块失败(保留原文) | 3 无余额/无资源包(1113) | 4 鉴权失败
- 校正稿保留原 [mm:ss] 行结构；跨块碎句的最终缝合交给主模型终审

输出:
  out_calibrated.txt          校正稿（头部注释标明为预筛）
  <out>.report.json           {model, changes[], glossary, final_text, failed_chunks}
"""
import argparse, concurrent.futures, hashlib, json, os, re, sys, threading, time
import urllib.request, urllib.error

SYS_PROMPT = """你是中文语音转写稿（ASR 输出）的校对助手。对给定文本做最小必要修正，规则按优先级：
1. 只修高置信度错误：同音字/近音字误听、专有名词（人名/书名/机构/作品）误写、行内断句碎句缝合（如"高。出整整九倍"→"高出整整九倍"、"对价。值观"→"对价值观"）。
1b. 成语、典故、名言、惯用语、固定表达一律不得改动——即使听上去可疑（如"从庐山里边跳了出来"是借"不识庐山真面目"的典故，意为跳出冲突看全局；"纸老虎""不卑不亢"同理）。若你怀疑某处误听但原文可自然读作某个成语/典故/惯用语，保留原文，只在 changes 里登记 confidence="low"，由下游终审判断。
1c. 通顺度：ASR 常把开场音乐/环境音/无意义语气助词误输出为句首杂字（如开头的「等」「嗯」等）。若某字置于句首使整句不通或无实义，可删除该杂字以恢复通顺，并在 changes 登记；但不得改变观点、不得改写实义词汇、不得润色句子结构。
2. 数字规范化：口语数字转阿拉伯数字（如"PHIL幺七六"→"PHIL 176"、"四百五十五美元"→"455 美元"），但不得改变任何数量级。
3. 禁止改写：不改变观点、语气、用词习惯，不删实义内容，不润色句式，不添加原文没有的事实。口癖（"这个这个"）可删。
4. 不确定就不改。拿不准的猜测放进 changes 并把 confidence 标为 "low"，corrected 正文里保持原文。
5. 输出格式硬约束：只输出一个 JSON 对象，不要代码块围栏，不要任何解释文字。修改后的文本必须完整输出全文，禁止省略或用省略号代替。
6. 行结构红线：输入每行以 [mm:ss] 时间戳开头。每个时间戳行必须原样保留行首时间戳、行数必须与输入一致；禁止跨行合并、禁止删除或移动时间戳。若发现跨行被劈开的句子（上一行末尾与下一行时间戳后本是一句），不要合并，只在 changes 里登记一条 confidence="low" 的缝合建议，由下游终审处理。"""

USER_TMPL = """【全局术语表（前文已确定的写法，遇到同一实体必须沿用）】
{glossary}

【上一块结尾（仅供上下文衔接，不要重复输出）】
...{prev_tail}

【本块原文（每行以 [mm:ss] 开头）】
{chunk}

请校正本块，输出 JSON（严格合法）：
{{"corrected":"校正后的本块全文。行数必须与输入一致，每行行首时间戳必须逐字保留且顺序不变",
"changes":[{{"original":"原文片段","corrected":"修正后片段","reason":"一句话依据","confidence":"high或low"}}],
"glossary_add":[{{"term":"实体规范写法","note":"一句说明（含原文误写，如有）"}}]}}
changes 只登记实际发生的修正与 low 置信度的存疑/跨行缝合建议；没有就给空数组。"""

_print_lock = threading.Lock()
RATE_WAIT = 45   # 智谱 1302 限流退避基数（秒）；短退避只会撞墙

def log(msg):
    with _print_lock:
        print(msg, flush=True)

class AuthError(Exception): pass
class NoQuota(Exception): pass
class TransientError(Exception): pass
class RateLimitedError(TransientError): pass

def parse_ts_line(line):
    m = re.match(r'^\[(\d{1,2}:\d{2})\]\s*(.*)$', line)
    return (m.group(1), m.group(2)) if m else (None, None)

def load_key():
    k = os.environ.get('ZHIPU_API_KEY', '').strip()
    if k:
        return k
    for kf in (os.path.expanduser('~/.dsh/secrets/zhipu_api_key'),
               os.path.expanduser('~/.dsh/zhipu_api_key')):
        if os.path.isfile(kf):
            log(f"INFO: 已从 {kf} 读取 API key")
            return open(kf).read().strip()
    return ''

_thinking_ok = True  # 首次 400 判定模型不支持 thinking 字段后翻转为 False

def zhipu_chat(key, base_url, model, messages, max_tokens, timeout=300):
    global _thinking_ok
    body = {"model": model, "messages": messages,
            "temperature": 0.1, "max_tokens": max_tokens}
    if _thinking_ok:
        body["thinking"] = {"type": "disabled"}
    req = urllib.request.Request(
        base_url.rstrip('/') + '/chat/completions',
        data=json.dumps(body).encode(),
        headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors='replace')
        if e.code in (401, 403):
            raise AuthError(raw[:200])
        if e.code == 429 and ('1113' in raw or '余额' in raw or '资源包' in raw):
            raise NoQuota(raw[:200])
        if e.code == 429:   # 1302 等速率限制：单独长退避
            raise RateLimitedError(f"HTTP 429 速率限制: {raw[:120]}")
        if e.code == 400 and _thinking_ok and 'thinking' in raw.lower():
            # 该模型不识别 thinking 字段：翻转后重试一次
            _thinking_ok = False
            body2 = {k: v for k, v in body.items() if k != 'thinking'}
            req2 = urllib.request.Request(
                base_url.rstrip('/') + '/chat/completions',
                data=json.dumps(body2).encode(),
                headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'})
            try:
                with urllib.request.urlopen(req2, timeout=timeout) as r:
                    return json.loads(r.read().decode())
            except urllib.error.HTTPError as e2:
                raise TransientError(f"HTTP {e2.code} (no-thinking 重试): {e2.read().decode(errors='replace')[:200]}")
        raise TransientError(f"HTTP {e.code}: {raw[:200]}")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise TransientError(f"{type(e).__name__}: {e}")

def extract_json(text):
    """健壮解析：直解 → 剥代码围栏 → 首 { 到末 } 截取。"""
    t = text.strip()
    cands = [t, re.sub(r'^```(?:json)?\s*|\s*```\s*$', '', t, flags=re.S).strip()]
    s, e = t.find('{'), t.rfind('}')
    if 0 <= s < e:
        cands.append(t[s:e+1])
    for cand in cands:
        try:
            return json.loads(cand)
        except Exception:
            pass
    return None

def repair_lines(key, base_url, model, bad_lines, glossary, idx, total):
    """二次修复：只把时间戳校验失败的行成组重发，返回 {ts: fixed_line}。"""
    fixed = {}
    for ln in bad_lines:
        ts, _ = parse_ts_line(ln)
        user = ("修正下面这一行 ASR 转写文本。硬性要求：输出的第一行必须以 "
                f"[{ts}] 原样开头（该行内容跟在后面）；可以额外补充续行来承接被时间戳劈开的句子。"
                "只做高置信度修正（同音字/专名/数字规范/行内碎句），不改观点不改数量级。\n"
                f'只输出 JSON：{{"lines":"以[{ts}]开头的修正后文本"}}\n'
                f'\n【全局术语表（沿用写法）】\n{glossary or "（暂无）"}\n\n'
                f'原文行：\n{ln}')
        msgs = [{"role": "system", "content": "你是中文 ASR 转写稿校对助手。严格遵守输出格式，只输出 JSON 对象，无围栏无解释。"},
                {"role": "user", "content": user}]
        try:
            resp = zhipu_chat(key, base_url, model, msgs, 1200)
        except (AuthError, NoQuota):
            raise
        except TransientError as e:
            log(f"[{idx+1}/{total}] 行修复 {ts} 失败: {e}")
            continue
        d = extract_json((resp.get('choices') or [{}])[0].get('message', {}).get('content') or '')
        lines = (d or {}).get('lines', '')
        if isinstance(lines, str) and lines.lstrip().startswith(f'[{ts}]'):
            fixed[ts] = lines.strip()
            log(f"[{idx+1}/{total}] 行修复 {ts} OK")
    return fixed

def call_chunk(key, base_url, model, chunk_text, glossary, prev_tail, idx, total):
    user = USER_TMPL.format(glossary=glossary or '（暂无）',
                            prev_tail=(prev_tail or '')[-120:], chunk=chunk_text)
    msgs = [{"role": "system", "content": SYS_PROMPT},
            {"role": "user", "content": user}]
    max_tokens = min(8000, 1500 + 2 * len(chunk_text))
    last_err = ''
    for attempt in (1, 2, 3):
        m = list(msgs)
        if attempt > 1:
            m.append({"role": "assistant", "content": '{"提示": "上一次输出不合法或残缺"}'})
            m.append({"role": "user", "content": "重新输出。必须只输出一个合法 JSON 对象，禁止围栏、禁止省略正文。"})
        try:
            resp = zhipu_chat(key, base_url, model, m, max_tokens)
        except (AuthError, NoQuota):
            raise
        except RateLimitedError as e:
            last_err = str(e)
            wait = RATE_WAIT * attempt
            log(f"[{idx+1}/{total}] 尝试{attempt} {last_err}，等待 {wait}s 退避")
            time.sleep(wait)
            continue
        except TransientError as e:
            last_err = str(e)
            log(f"[{idx+1}/{total}] 尝试{attempt} 网络/HTTP 失败: {last_err}")
            time.sleep(2 * attempt)
            continue
        content = (resp.get('choices') or [{}])[0].get('message', {}).get('content') or ''
        d = extract_json(content)
        if d and isinstance(d.get('corrected'), str) and len(d['corrected']) >= 0.5 * len(chunk_text):
            # 行级校验：按源行序对齐输出；缺行做行级修复；补不回则整块重试
            src = {}
            for sl in chunk_text.split('\n'):
                ts, _ = parse_ts_line(sl)
                if ts:
                    src[ts] = sl
            got = {}
            for cl in d['corrected'].split('\n'):
                ts, _ = parse_ts_line(cl)
                if ts and ts in src:
                    got.setdefault(ts, cl)
            missing = [ts for ts in src if ts not in got]
            if not missing:
                log(f"[{idx+1}/{total}] done  改动{len(d.get('changes', []) or [])}处"
                    f" tokens={resp.get('usage', {}).get('total_tokens')}")
                return d
            last_err = f'丢失时间戳 {missing}'
            log(f"[{idx+1}/{total}] 尝试{attempt} {last_err}，进入行级修复")
            fixed = repair_lines(key, base_url, model,
                                 [src[ts] for ts in missing], glossary, idx, total)
            still = [ts for ts in missing if ts not in fixed]
            if still:
                log(f"[{idx+1}/{total}] 行修复仍缺 {still}，整块重试")
                time.sleep(1)
                continue
            d['corrected'] = '\n'.join(got.get(ts) or fixed[ts] for ts in src)
            d.setdefault('lines_fixed', {})
            d['lines_fixed'].update({ts: fixed[ts] for ts in missing})
            log(f"[{idx+1}/{total}] 行级修复完成，放行")
            return d
        last_err = f'JSON 解析失败或输出残缺（{len(content)} 字符）'
        log(f"[{idx+1}/{total}] 尝试{attempt} {last_err}")
        time.sleep(1)
    raise TransientError(f"3 次尝试均失败: {last_err}")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('transcript')
    ap.add_argument('out_txt')
    ap.add_argument('--report', default=None, help='默认 <out_txt>.report.json')
    ap.add_argument('--model', default='glm-4.7')
    ap.add_argument('--base-url', default='https://open.bigmodel.cn/api/paas/v4')
    ap.add_argument('--max-chars', type=int, default=1500, help='每块最大字符数（按行切，默认 1500：块更小→失败粒度小、并发利用率高、缓存复用多）')
    ap.add_argument('--workers', type=int, default=2, help='并发数（双泳道：workers 条泳道内按序号顺序，术语表沿泳道前滚；默认 2）')
    ap.add_argument('--cache-dir', default=None, help='默认 <out_txt>.calib_cache')
    args = ap.parse_args()

    key = load_key()
    if not key:
        log('ERROR: 无智谱 key。export ZHIPU_API_KEY=... 或写入 ~/.dsh/secrets/zhipu_api_key')
        sys.exit(1)

    raw = open(args.transcript, encoding='utf-8').read().splitlines()
    entries = [ln for ln in raw if not ln.startswith('#') and parse_ts_line(ln)[0] is not None]
    if not entries:
        log('ERROR: 未解析到任何 [mm:ss] 行'); sys.exit(1)

    # 按行聚块，每块 <= max_chars
    chunks, cur, cur_len = [], [], 0
    for ln in entries:
        if cur and cur_len + len(ln) > args.max_chars:
            chunks.append(cur); cur, cur_len = [], 0
        cur.append(ln); cur_len += len(ln) + 1
    if cur:
        chunks.append(cur)
    total = len(chunks)
    log(f"INFO: {len(entries)} 段 -> {total} 块, model={args.model}, workers={args.workers}")

    cache_dir = args.cache_dir or args.out_txt + '.calib_cache'
    os.makedirs(cache_dir, exist_ok=True)

    tasks = []   # (idx, chunk_text, cache_path)；文件名带输入+prompt hash，任一变则重算
    phash = hashlib.sha256((SYS_PROMPT + USER_TMPL).encode()).hexdigest()[:8]
    prev_tails = [''] * total
    for i, c in enumerate(chunks):
        text = '\n'.join(c)
        if i > 0:
            prev_tails[i] = '\n'.join(chunks[i-1])[-120:]
        h = hashlib.sha256((text + args.model + phash).encode()).hexdigest()[:16]
        tasks.append((i, text, os.path.join(cache_dir, f'chunk_{i:03d}_{h}.json')))

    results = [None] * total
    failures = []
    glossary_state = {}
    g_lock = threading.Lock()
    quota_lost = threading.Event()

    def work(i, text, cp):
        if os.path.isfile(cp):
            log(f"[{i+1}/{total}] cached")
            d = json.load(open(cp))
            with g_lock:   # 缓存命中也要回填术语表，保证汇总报告完整
                for item in d.get('glossary_add', []) or []:
                    if item.get('term'):
                        glossary_state.setdefault(item['term'], item.get('note', ''))
            return d
        if quota_lost.is_set():
            raise NoQuota('aborted: 配额已失效')
        with g_lock:
            g = '\n'.join(f"- {t}：{n}" for t, n in glossary_state.items())
        d = call_chunk(key, args.base_url, args.model, text, g, prev_tails[i], i, total)
        with g_lock:
            for item in d.get('glossary_add', []) or []:
                if item.get('term'):
                    glossary_state.setdefault(item['term'], item.get('note', ''))
        json.dump(d, open(cp, 'w'), ensure_ascii=False)
        return d

    # 双泳道调度：workers 条泳道并发，每条泳道内按块序号顺序处理。
    # 这样术语表（glossary）沿每条泳道前滚：块 i 能看到块 i-1、i-2（同泳道）的新增术语，
    # 修复纯并发下「后块看不到前块术语决定」导致专名前后不一致的竞态。
    def run_lane(lane, count):
        out = {}
        for i in range(lane, total, count):
            text, cp = tasks[i][1], tasks[i][2]
            try:
                out[i] = ('ok', work(i, text, cp))
            except NoQuota:
                out[i] = ('quota', None); break
            except AuthError as e:
                out[i] = ('auth', e); break
            except TransientError as e:
                out[i] = ('fail', e)
        return out

    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.workers)) as ex:
        runners = {ex.submit(run_lane, l, max(1, args.workers)): l for l in range(max(1, args.workers))}
        for f in concurrent.futures.as_completed(runners):
            lane = runners[f]
            for i, (status, payload) in f.result().items():
                if status == 'ok':
                    results[i] = payload
                elif status == 'quota':
                    quota_lost.set()
                    log('ERROR: 无余额/无资源包。改回主模型手工校正，或充值后重跑（已完成块有缓存）。')
                    sys.exit(3)
                elif status == 'auth':
                    log(f'ERROR: 鉴权失败: {payload}'); sys.exit(4)
                else:
                    failures.append(i)
                    log(f"[{i+1}/{total}] 失败（保留原文）: {payload}")

    # 汇总：失败块用原文顶替（changes 记一条 skipped）
    final_parts, all_changes = [], []
    for i, (ix, text, cp) in enumerate(tasks):
        d = results[i]
        if d is None:
            final_parts.append(text)
            all_changes.append({"time": text.split(']')[0][1:], "original": "(整块)",
                                "corrected": "(校正失败，保留原文)", "reason": "LLM 调用失败",
                                "confidence": "skipped", "chunk": ix})
        else:
            final_parts.append(d['corrected'].strip())
            for ch in d.get('changes', []) or []:
                # 过滤无意义条目：original == corrected 的"自我确认"不算改动
                if ch.get('original') == ch.get('corrected'):
                    continue
                ch['chunk'] = ix
                all_changes.append(ch)
    final_text = '\n'.join(final_parts)

    # ── 交叉验证：检查 changes 中声称的修正是否真的应用到了 final_text ──
    # LLM 可能在 changes 数组里登记了修正，但在 corrected 文本里忘了替换。
    # 这里补上：如果 original 存在于 final_text 中，则自动替换为 corrected。
    auto_fix_log = []
    for ch in all_changes:
        conf = ch.get('confidence', '')
        if conf not in ('high', 'low'):
            continue
        orig = ch.get('original', '')
        corr = ch.get('corrected', '')
        if not orig or not corr or orig == corr:
            continue
        if orig in final_text:
            count = final_text.count(orig)
            if count > 0:
                final_text = final_text.replace(orig, corr)
                auto_fix_log.append({
                    'original': orig,
                    'corrected': corr,
                    'count': count,
                    'reason': ch.get('reason', ''),
                    'chunk': ch.get('chunk', -1)
                })

    auto_fixed_count = sum(x['count'] for x in auto_fix_log)
    if auto_fixed_count:
        log(f"⚠️  交叉验证：{auto_fixed_count} 处修正在 changes 清单中声明但未实际应用到文本，已自动补全")
        for fix in auto_fix_log:
            log(f"   自动补全: 「{fix['original']}」→「{fix['corrected']}」 x{fix['count']}（chunk {fix['chunk']}）")

    with open(args.out_txt, 'w', encoding='utf-8') as f:
        f.write(f"# 校正稿（llm_calibrate.py 预筛，model={args.model}；终审前仅供参考）\n")
        f.write(f"# 原始存证见 {os.path.basename(args.transcript)}\n")
        f.write(final_text + '\n')

    report_path = args.report or args.out_txt + '.report.json'
    hi = sum(1 for c in all_changes if c.get('confidence') == 'high')
    lo = sum(1 for c in all_changes if c.get('confidence') == 'low')
    report = {"model": args.model, "source": args.transcript, "chunks": total,
              "failed_chunks": len(failures), "changes": all_changes,
              "glossary": glossary_state, "stats": {"high": hi, "low": lo},
              "auto_fixes": auto_fix_log,
              "final_text": final_text}
    json.dump(report, open(report_path, 'w'), ensure_ascii=False, indent=1)

    log(f"OK: 校正稿 {args.out_txt}")
    log(f"OK: 报告   {report_path}（改动 high={hi} low={lo} 跳过块={len(failures)} 术语表={len(glossary_state)} 自动补全={auto_fixed_count}）")

    # 清理缓存目录里旧 prompt 版本的残留文件（文件名含 phash，当前 phash 的保留）
    keep = {os.path.basename(t[2]) for t in tasks}
    for fn in os.listdir(cache_dir):
        if fn not in keep:
            p = os.path.join(cache_dir, fn)
            try:
                os.remove(p)
            except OSError:
                pass
    log(f"OK: 已清理 {cache_dir} 中旧版本缓存（保留 {len(keep)} 个当前块）")

    log("下一步：主模型逐条终审 report.changes（accept/reject），reject 的片段按原文回改校正稿。")
    sys.exit(0 if not failures else 2)

if __name__ == '__main__':
    main()
