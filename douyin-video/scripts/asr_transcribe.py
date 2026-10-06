#!/usr/bin/env python3
"""asr_transcribe.py — 把 16kHz mono WAV 分块转写为带时间戳的纯文本。

用法:
  SILICONFLOW_API_KEY=... python3 asr_transcribe.py <wav> <out.txt> \
      [--model XingChenAGI/XingChenASR-V3.2-Ultra] [--chunk-seconds 自动] [--out-dir <chunks dir>]

- 音频切成 chunk-seconds 块（默认按 总时长/并发数 自动分块，夹取到 [30s,150s]），逐块 POST 硅基流动 /audio/transcriptions
- 输出文本行格式: [mm:ss] 内容
- 每块原始 JSON 落盘到 --out-dir（默认 <wav>.chunks/），支持断点重跑
- 失败块重试共 3 次尝试；鉴权失败(401/403)立即放弃该块
- 任一失败块在输出里标注「(本块转写失败，已重试3次)」；有失败块则退出码 2（已有结果仍写出）
"""
import argparse, json, os, re, sys, time, struct, array, urllib.request, urllib.error, uuid, wave, threading, concurrent.futures

# 长视频自动并发的硬顶：块数多时并发随块数上调到此值以内。
# 硅基流动免费档限流较紧；若遇明显 429，可把此值调小（如 4~6）。
AUTO_MAX_WORKERS = 8

def fmt_ts(sec):
    m, s = divmod(int(sec), 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"

def pcm_to_wav_bytes(pcm: bytes, rate=16000, nch=1, sw=2) -> bytes:
    """给裸 PCM 数据加 RIFF/WAV 头，返回完整 wav 字节。"""
    data_size = len(pcm)
    header = b'RIFF' + struct.pack('<I', 36 + data_size) + b'WAVE'
    header += b'fmt ' + struct.pack('<IHHIIHH', 16, 1, nch, rate, rate * nch * sw, nch * sw, sw * 8)
    header += b'data' + struct.pack('<I', data_size)
    return header + pcm

def chunk_wav(src, seconds):
    with wave.open(src, 'rb') as w:
        rate = w.getframerate(); sw = w.getsampwidth(); nch = w.getnchannels()
        n = w.getnframes()
        if sw != 2 or nch != 1:
            print(f"ERROR: 输入必须是 16bit mono WAV（当前 {sw*8}bit {nch}ch），先跑 extract_audio.py", file=sys.stderr)
            sys.exit(1)
        buf = array.array('h', w.readframes(n))
    chunk = rate * seconds
    out = []
    for i in range(0, len(buf), chunk):
        piece = bytes(buf[i:i+chunk])
        if not piece:
            # 末尾空块（总时长恰好被块长整除，range 会步进到 len(buf)）：
            # 跳过，避免对 0 秒空块发起一次无效的 ASR 调用并占用并发槽。
            break
        out.append((i // rate, pcm_to_wav_bytes(piece, rate=rate)))
    return rate, out

def call_asr(api_key, base_url, model, wav_bytes, label):
    # 与 curl -F 等价的 multipart 字节（wav_bytes 须为含 RIFF 头的完整 wav）
    bnd = '----DSHFormBoundary' + uuid.uuid4().hex
    parts = []
    parts.append(f"--{bnd}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{label}.wav\"\r\nContent-Type: audio/wav\r\n\r\n".encode())
    parts.append(wav_bytes)
    parts.append(b"\r\n")
    parts.append(f"--{bnd}\r\nContent-Disposition: form-data; name=\"model\"\r\nContent-Type: text/plain\r\n\r\n".encode())
    parts.append(model.encode() + b"\r\n")
    parts.append(f"--{bnd}--\r\n".encode())
    data = b''.join(parts)
    req = urllib.request.Request(
        base_url.rstrip('/') + '/audio/transcriptions',
        data=data,
        headers={'Authorization': f'Bearer {api_key}',
                 'Content-Type': f'multipart/form-data; boundary={bnd}'}
    )
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(r.read().decode())

def wav_duration_seconds(path):
    """只读 WAV 头部拿时长，避免整载音频。"""
    with wave.open(path, 'rb') as w:
        return w.getnframes() / float(w.getframerate())

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('wav')
    ap.add_argument('out_txt')
    ap.add_argument('--model', default='XingChenAGI/XingChenASR-V3.2-Ultra')
    ap.add_argument('--chunk-seconds', type=int, default=None,
                    help='每块秒数；默认按 总时长/并发数 自动分块（让块数≈并发数，一轮并行跑完最快）')
    ap.add_argument('--out-dir', default=None)
    ap.add_argument('--workers', type=int, default=3,
                    help='基础并发块数（默认 3，作下限）；长视频块数多时自动上调到 AUTO_MAX_WORKERS 硬顶以内。'
                         '硅基流动 ASR 免费档限流较紧，不建议基础值 >4')
    args = ap.parse_args()

    api_key = os.environ.get('SILICONFLOW_API_KEY', '').strip()
    if not api_key:
        # 免询问约定：从用户密钥文件读取（600 权限，用户自行放置）
        for kf in (os.path.expanduser('~/.dsh/secrets/siliconflow_api_key'),
                   os.path.expanduser('~/.dsh/siliconflow_api_key')):
            if os.path.isfile(kf):
                api_key = open(kf).read().strip()
                print(f"INFO: 已从 {kf} 读取 API key", file=sys.stderr)
                break
    base_url = os.environ.get('SILICONFLOW_BASE_URL', 'https://api.siliconflow.cn/v1')
    if not api_key:
        print('ERROR: 无 API key。三选一：export SILICONFLOW_API_KEY=... / '
              '把 key 写入 ~/.dsh/secrets/siliconflow_api_key / 向用户索取', file=sys.stderr)
        sys.exit(1)

    out_dir = args.out_dir or args.wav + '.chunks'
    os.makedirs(out_dir, exist_ok=True)

    # 自动分块：让块数≈并发数（一轮并行跑完），并按区间 [30s, 150s] 夹取。
    # 上限从 240s 压到 150s：大块 → 单次请求 token 高、延迟长、超时/失败重试代价大；
    # 宁多分几块，用并发兜底，既降低单块风险，又让并行负载更均衡。
    if args.chunk_seconds:
        chunk_secs = args.chunk_seconds
    else:
        dur = wav_duration_seconds(args.wav)
        chunk_secs = int(min(max(round(dur / args.workers), 30), 150))
        print(f"INFO: 自动分块 -> {chunk_secs}s（音频 {dur:.0f}s / workers={args.workers}）去最接近整块", file=sys.stderr)

    rate, chunks = chunk_wav(args.wav, chunk_secs)
    total = len(chunks)
    # 并发自动上调：块数多（长视频）时并发随块数提到基础值之上、硬顶以内，
    # 让「轮数≈块数/并发」随视频变长而下降，而非线性增长。
    # --workers 是基础值（下限）；短/中视频块数少时并发保持基础值，行为不变。
    workers = max(1, min(max(args.workers, total), AUTO_MAX_WORKERS))
    print(f"INFO: 共 {total} 块 x {chunk_secs}s, model={args.model}, workers={workers}"
          + ("（auto 上调）" if workers > args.workers else ""))

    lines = [None] * total
    failures = 0
    fails_lock = threading.Lock()

    def process(i, offset, wav_bytes):
        nonlocal failures
        cjson = os.path.join(out_dir, f'chunk_{i:04d}.json')
        if os.path.isfile(cjson):
            d = json.load(open(cjson))
            print(f"[{i+1}/{total}] cached  {fmt_ts(offset)}")
            ok = True
        else:
            ok = False
            for attempt in (1, 2, 3):
                try:
                    d = call_asr(api_key, base_url, args.model, wav_bytes, f'chunk_{i:04d}')
                    json.dump(d, open(cjson, 'w'), ensure_ascii=False)
                    ok = True
                    print(f"[{i+1}/{total}] done    {fmt_ts(offset)} +{len(wav_bytes)//2//rate}s")
                    break
                except urllib.error.HTTPError as e:
                    err = e.read().decode()[:400]
                    print(f"[{i+1}/{total}] HTTP {e.code} attempt {attempt}: {err}", file=sys.stderr)
                    if e.code in (401, 403):
                        print('FATAL: 鉴权失败（401/403），检查 SILICONFLOW_API_KEY', file=sys.stderr)
                        ok = False
                        break
                    time.sleep(2 * attempt)
                except Exception as e:
                    print(f"[{i+1}/{total}] {type(e).__name__} attempt {attempt}: {e}", file=sys.stderr)
                    time.sleep(2 * attempt)
        text = (d.get('text') or d.get('result') or '') if ok else ''
        text = re.sub(r'\s+', ' ', text).strip()
        seg = text or ('(静默)' if ok else '(本块转写失败，已重试3次)')
        lines[i] = f"[{fmt_ts(offset)}] {seg}"
        if not ok:
            with fails_lock:
                failures += 1

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(process, i, off, wb) for i, (off, wb) in enumerate(chunks)]
        for f in futs:
            f.result()

    out_txt = args.out_txt
    with open(out_txt, 'w', encoding='utf-8') as f:
        meta = f"# 转写元信息\n# model={args.model}\n# 块数={total} 失败={failures}\n# 采样率={rate}\n"
        f.write(meta)
        f.write('\n'.join(lines) + '\n')
    print(f"OK: 写出 {out_txt}（{len(lines)} 行，{failures} 块失败）")
    sys.exit(0 if failures == 0 else 2)

if __name__ == '__main__':
    main()
