#!/usr/bin/env python3
"""mp4_extract_aac.py — 纯 Python 从 MP4/MOV 容器提取 AAC 音频轨，输出 ADTS 封装的 .aac 文件。

用法: python3 mp4_extract_aac.py <输入.mp4> <输出.aac>
退出码 0 成功; 1 失败（无音频轨 / 解析失败）
"""
import struct, sys

def children(buf, s, e):
    o = s; out = []
    while o + 8 <= e:
        sz = struct.unpack('>I', buf[o:o+4])[0]
        t = buf[o+4:o+8]
        if sz == 1:
            if o + 16 > e: break
            sz = struct.unpack('>Q', buf[o+8:o+16])[0]
        elif sz == 0:
            sz = e - o
        if o + sz > e: break
        out.append((t, o+8, o+sz)); o += sz
    return out

def main():
    if len(sys.argv) != 3:
        print('用法: mp4_extract_aac.py <输入.mp4> <输出.aac>', file=sys.stderr)
        sys.exit(1)
    src, dst = sys.argv[1], sys.argv[2]
    buf = open(src, 'rb').read()
    n = len(buf)

    i = 0
    moov = None
    while i + 8 <= n:
        sz = struct.unpack('>I', buf[i:i+4])[0]; t = buf[i+4:i+8]
        if sz == 1:
            if i + 16 > n: break
            sz = struct.unpack('>Q', buf[i+8:i+16])[0]
        if t == b'moov':
            moov = (i+8, i+sz); break
        i += sz
    if not moov:
        print('ERROR: 未找到 moov box', file=sys.stderr); sys.exit(1)

    traks = [c for c in children(buf, moov[0], moov[1]) if c[0] == b'trak']
    print(f'INFO: {len(traks)} 个 trak')

    audio = None
    for t, cs, ce in traks:
        mdias = [c for c in children(buf, cs, ce) if c[0] == b'mdia']
        if not mdias: continue
        mcs, mce = mdias[0][1], mdias[0][2]
        hdlrs = [c for c in children(buf, mcs, mce) if c[0] == b'hdlr']
        for h in hdlrs:
            htype = buf[h[1]+8: h[1]+12]
            if htype == b'soun':
                audio = (cs, ce, mcs, mce)
                break
        if audio: break

    if not audio:
        print('ERROR: 该 MP4 没有音频轨（soun）', file=sys.stderr); sys.exit(1)
    cs, ce, mcs, mce = audio
    print('INFO: 找到音频轨')

    minfs = [c for c in children(buf, mcs, mce) if c[0] == b'minf']
    if not minfs:
        print('ERROR: 音频 trak 缺 minf', file=sys.stderr); sys.exit(1)
    stbls = [c for c in children(buf, minfs[0][1], minfs[0][2]) if c[0] == b'stbl']
    if not stbls:
        print('ERROR: 音频 trak 缺 stbl', file=sys.stderr); sys.exit(1)
    stbl = stbls[0]

    def find(name):
        for c in children(buf, stbl[1], stbl[2]):
            if c[0] == name:
                return c
        return None

    stsd = find(b'stsd'); stsz = find(b'stsz'); stts = find(b'stts')
    stco = find(b'stco'); co64 = find(b'co64')
    for nm, v in (('stsd', stsd), ('stsz', stsz), ('stts', stts)):
        if not v:
            print(f'ERROR: 缺 {nm}', file=sys.stderr); sys.exit(1)
    if not stco and not co64:
        print('ERROR: 缺 stco/co64', file=sys.stderr); sys.exit(1)

    # --- stsd 音频参数 ---
    c = stsd[1]
    cnt = struct.unpack('>I', buf[c+4:c+8])[0]
    entry_start = c + 8
    esz = struct.unpack('>I', buf[entry_start:entry_start+4])[0]
    etype = buf[entry_start+4:entry_start+8]
    codec = etype.decode('latin1')
    # entry 内容（跳过 size+type 8 字节）：
    #   +0 ref(4) +4 reserved(4) +8 ch(2) +10 bits(2) +12 layout(4) +16 samplerate(4,16.16) +20 samplesize(4)
    e = entry_start + 8
    raw_ch = struct.unpack('>H', buf[e+8:e+10])[0]
    raw_sr = struct.unpack('>I', buf[e+16:e+20])[0] >> 16
    channels = raw_ch if raw_ch else 2
    sample_rate = raw_sr if raw_sr else 48000
    # 采样率在 16.16 定点中可能因打包而解析为 0 或错误值；用 stsd entry 中扫描 16.16 定点表修正
    if sample_rate in (0, 2):
        candidates = [48000, 44100, 32000, 22050, 16000, 12000, 8000]
        for cand in candidates:
            v = struct.pack('>I', cand << 16)
            pos = buf.find(v, entry_start, entry_start + esz)
            if pos >= 0:
                sample_rate = cand
                print(f'INFO: stsd 解析采样率异常，entry 内扫描得 {cand}Hz @ +{pos - entry_start}')
                break
    print(f'INFO: codec={codec} sample_rate={sample_rate} channels={channels} entry_size={esz}')

    if codec not in ('mp4a', 'aac ', 'aacS', 'soun'):
        print(f'WARN: 编码 {codec!r} 非标准 AAC；ASR 可能无法解码', file=sys.stderr)

    # --- stsz 每帧字节 ---
    c = stsz[1]
    ss_field = struct.unpack('>I', buf[c+4:c+8])[0]
    sample_count = struct.unpack('>I', buf[c+8:c+12])[0]
    if ss_field:
        sizes = [ss_field] * sample_count
    else:
        sizes = list(struct.unpack('>%dI' % sample_count, buf[c+12:c+12+4*sample_count]))

    # --- stco/co64 每帧偏移 ---
    if co64:
        c = co64[1]
        cnt2 = struct.unpack('>I', buf[c+4:c+8])[0]
        offsets = list(struct.unpack('>%dQ' % cnt2, buf[c+8:c+8+8*cnt2]))
    else:
        c = stco[1]
        cnt2 = struct.unpack('>I', buf[c+4:c+8])[0]
        offsets = list(struct.unpack('>%dI' % cnt2, buf[c+8:c+8+4*cnt2]))

    nn = min(len(sizes), len(offsets))
    if len(sizes) != len(offsets):
        print(f'WARN: stsz {len(sizes)} != stco {len(offsets)}，取 {nn}', file=sys.stderr)
    sizes = sizes[:nn]; offsets = offsets[:nn]
    print(f'INFO: 共 {nn} 帧')

    def adts_hdr(sampling_freq, ch, frame_len):
        sr_table = {8000: 7, 12000: 6, 16000: 5, 22050: 4, 24000: 3, 32000: 2, 44100: 1, 48000: 0}
        sr_idx = sr_table.get(sampling_freq, 15)
        ch_idx = max(0, min(ch - 1, 31))
        full = frame_len + 7
        b2 = ((2 - 1 + 1) << 6) | (sr_idx << 2) | (ch_idx >> 2)      # sync(12) profile(3)=2 sr(4) chan(2,high)
        b3 = ((ch_idx & 3) << 6) | ((full >> 11) & 0x3)
        b4 = (full & 0x7FF) >> 4
        b5 = ((full & 0xF) << 4)
        b6 = ((full >> 8) & 0xF) | 0xF
        b2 &= 0xFF; b3 &= 0xFF; b4 &= 0xFF; b5 &= 0xFF; b6 &= 0xFF
        return bytes([0xFF, 0xF1, b2, b3, b4, b5, b6])

    total = 0
    out = open(dst, 'wb')
    for sz, off in zip(sizes, offsets):
        frame = buf[off:off+sz]
        if len(frame) != sz:
            print(f'WARN: 帧 @{off} 越界（要 {sz} 实 {len(frame)}），跳过', file=sys.stderr)
            continue
        out.write(adts_hdr(sample_rate, channels, sz))
        out.write(frame)
        total += 1
    out.close()
    print(f'OK: 写出 {dst}（{total} 帧 ADTS/AAC，{sample_rate}Hz，{channels}ch）')

if __name__ == '__main__':
    main()
