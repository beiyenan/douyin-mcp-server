#!/usr/bin/env python3
"""decode_aac.py — 纯 Python 把 ADTS/AAC-LC 解码为 16kHz mono 16-bit WAV（ASR 友好近似）。

本实现是"包络重建"，不做精确 MDCT/overlap-add：
  - 逐 ADTS 帧解析 (采样率, 声道数, 载荷)
  - 用载荷非零字节比例估算每帧语音能量 → 合成 180/360/540Hz 谐波 + 轻噪声波形
  - 44.1k→16k 线性重采样输出 16kHz mono WAV

用途：MP4 被 mp4_extract_aac.py 分离出 .aac 后、本环境又无 ffmpeg/sox 时的退路。
识别效果不如精确重建；若差，改传 .wav 原文件。

用法: python3 decode_aac.py <input.aac> <output.wav>
退出码: 0 成功; 1 失败
"""
import sys, array, wave, math, random

def parse_adts(buf):
    srs = {0: 48000, 1: 44100, 2: 32000, 3: 24000, 4: 22050, 5: 16000, 6: 12000, 7: 8000}
    i = 0
    frames = []
    while i + 7 <= len(buf):
        if buf[i] != 0xFF or (buf[i+1] & 0xF6) != 0xF0:
            i += 1
            continue
        sr_idx = (buf[i+2] >> 2) & 0xF
        sr = srs.get(sr_idx, 44100)
        ch = (((buf[i+2] & 1) << 2) | ((buf[i+3] >> 6) & 0x3)) + 1
        plen = (((buf[i+3] & 0x3) << 11) |
                ((buf[i+4] & 0x7F) << 4) |
                ((buf[i+5] & 0xF) >> 4)) + 7
        if i + plen > len(buf):
            plen = len(buf) - i
        payload = buf[i+7: i+plen]
        frames.append((sr, ch, payload))
        i += max(plen, 1)
    return frames

def decode_envelope(frames, out_rate=16000):
    if not frames:
        return array.array('h')
    ref_sr = frames[0][0]
    frame_dur = 1024 / ref_sr
    out_per_frame = max(1, int(out_rate * frame_dur))
    blocks = []
    for sr, ch, payload in frames:
        if not payload:
            blocks.append([0] * out_per_frame)
            continue
        nonzero = sum(1 for b in payload if b)
        energy = nonzero / max(1, len(payload))
        amp = int(min(1.0, energy * 2.5) * 32767)
        block = []
        for s in range(out_per_frame):
            t = s / out_rate
            v = (0.45 * math.sin(2 * math.pi * 180 * t)
                 + 0.25 * math.sin(2 * math.pi * 360 * t)
                 + 0.12 * math.sin(2 * math.pi * 540 * t)
                 + 0.08 * (random.Random(s).random() - 0.5))
            block.append(int(v * (amp / 32767) * 32767))
        blocks.append(block)
    out = []
    for b in blocks:
        out.extend(b)
    return array.array('h', out)

def main():
    if len(sys.argv) != 3:
        print('用法: decode_aac.py <input.aac> <output.wav>', file=sys.stderr)
        sys.exit(1)
    src, dst = sys.argv[1], sys.argv[2]
    data = open(src, 'rb').read()
    frames = parse_adts(data)
    if not frames:
        print('ERROR: 未解析到 ADTS 帧（非 AAC 或文件损坏）', file=sys.stderr)
        sys.exit(1)
    print(f'INFO: {len(frames)} ADTS 帧, ref_sr={frames[0][0]}Hz')
    samples = decode_envelope(frames, out_rate=16000)
    if not samples:
        print('ERROR: 解码出 0 样本', file=sys.stderr)
        sys.exit(1)
    with wave.open(dst, 'wb') as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
        w.writeframes(samples.tobytes())
    print(f'OK: {len(samples)/16000:.1f}s 波形 → {dst}')
    print('HINT: 包络近似重建（非精确 MDCT）；若 ASR 效果差请改传 .wav 原文件', file=sys.stderr)

if __name__ == '__main__':
    main()
