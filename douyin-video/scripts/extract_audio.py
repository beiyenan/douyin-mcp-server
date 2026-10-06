#!/usr/bin/env python3
"""extract_audio.py — 把视频/音频容器里的音频轨提取为 16kHz mono WAV。

策略（按可用性逐级降级）：
  1. 系统 PATH 有 ffmpeg → 直接 `ffmpeg -i in -ar 16000 -ac 1 out.wav`（万能）
  1b. Android/DSH 工具链 ffmpeg（usr/bin/ffmpeg）→ 自动注入 LD_LIBRARY_PATH+LD_PRELOAD 后同 1
  2. 输入是 WAV 且无 ffmpeg → 纯 Python 重采样/混音为 mono 16k（仅支持 16bit）
  3. 输入是 mp4/mov 且无 ffmpeg → 纯 Python 分离 AAC 轨 + 包络近似解码（精度差，会打 HINT），
     建议优先装工具链 ffmpeg
  4. 其余无解码器场景 → 明确失败并给降级提示（退出码 1）

用法: python3 extract_audio.py <输入文件> <输出.wav>
退出码: 0 成功(拿到 16k mono WAV); 1 失败(stderr 给出原因与下一步建议)
"""
import os, sys, shutil, struct, wave, subprocess

def has(name):
    """只找指定的可执行文件（不能拿 ffprobe 顶替 ffmpeg：两者参数集不同）。"""
    return shutil.which(name)

def fail(msg, hint=None):
    print(f"ERROR: {msg}", file=sys.stderr)
    if hint:
        print(f"HINT: {hint}", file=sys.stderr)
    sys.exit(1)

def probe_ffmpeg(ffmpeg, env):
    """自检 ffmpeg 能否真正执行。ELF 文件存在但缺依赖/架构不符时，调用会静默失败，
    不能因为 bin 文件存在就认为工具链可用（上一轮运行正栽在这里：找到了文件、跑不起来，
    浪费近 1 小时手工排查）。"""
    try:
        r = subprocess.run([ffmpeg, '-version'], capture_output=True, text=True,
                           timeout=30, env=env)
        return r.returncode == 0, (r.stderr or r.stdout or '')[-300:]
    except Exception as e:
        return False, str(e)

TOOLCHAIN_HINT = """本机工具链 ffmpeg 缺失或损坏。复装方案（Android/DSH 上已验证）：
  1) 准备 .deb：工作区已有 /storage/emulated/0/DSH/ffmpeg_8.1.3_aarch64.deb；依赖缺哪个就
     用 termux 源 `apt download <包名>` 补哪个（完整依赖清单见 SKILL.md「工具链复装」）。
  2) 解包平移（每个 .deb 都这样做，合并到同一个 usr）：
       TMP=$(mktemp -d)
       dpkg-deb -x <包.deb> "$TMP"
       cp -a "$TMP"/data/data/com.termux/files/usr/* /data/user/0/com.dsharnessmobile.shell/files/usr/
  3) 验证（必须带上 LD_PRELOAD，否则 Android 上直跑会缺 so）：
       LD_LIBRARY_PATH=/data/user/0/com.dsharnessmobile.shell/files/usr/lib \\
       LD_PRELOAD=/data/user/0/com.dsharnessmobile.shell/files/usr/lib/libtermux-exec-ld-preload.so \\
       /data/user/0/com.dsharnessmobile.shell/files/usr/bin/ffmpeg -version
  验证通过后重跑本脚本。或走降级方案：用剪映/手机工具把音频导成 .wav/.mp3 再上传。"""

def resample_wav_to_16k_mono(in_path, out_path):
    with wave.open(in_path, 'rb') as w:
        nch = w.getnchannels(); rate = w.getframerate(); sw = w.getsampwidth()
        n = w.getnframes()
        raw = w.readframes(n)
    if sw != 2:
        fail(f"WAV 采样宽度 {sw*8}bit 暂不支持，请换 16bit WAV 或先转码",
             "若原视频有音频，请在手机里导出为 16bit WAV 后再上传")
    import array
    buf = array.array('h', raw)  # little-endian assumed
    if nch > 1:
        # 混音 mono
        mono = [(buf[i] + buf[i+1]) // 2 for i in range(0, len(buf), 2)]
    else:
        mono = list(buf)
    if rate != 16000:
        ratio = 16000 / rate
        newlen = int(len(mono) * ratio)
        resampled = [int(mono[min(int(i/ratio), len(mono)-1)]) for i in range(newlen)]
        mono = resampled
    with wave.open(out_path, 'wb') as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
        w.writeframes(struct.pack('<%dh' % len(mono), *mono))
    print(f"OK: WAV -> 16kHz mono ({len(mono)/16000:.1f}s) -> {out_path}")

def main():
    if len(sys.argv) != 3:
        fail("用法: extract_audio.py <输入文件> <输出.wav>")
    src, dst = sys.argv[1], sys.argv[2]
    if not os.path.isfile(src):
        fail(f"文件不存在: {src}")
    ext = os.path.splitext(src)[1].lower()

    # 0) 系统 PATH 里的 ffmpeg；没有时尝试 DSH/Termux 工具链里的 ffmpeg。
    #    Android 上需注入 LD_LIBRARY_PATH + LD_PRELOAD 才能执行（apt 解包式安装的 ELF 依赖
    #    libandroid-support.so 等，且需 libtermux-exec-ld-preload.so 修正 linker 路径）。
    ffmpeg = has('ffmpeg')
    env = dict(os.environ)
    if not ffmpeg:
        for cand in ('/data/data/com.dsharnessmobile.shell/files/usr',
                     '/data/user/0/com.dsharnessmobile.shell/files/usr'):
            cand_bin = os.path.join(cand, 'bin', 'ffmpeg')
            if os.path.isfile(cand_bin):
                env['LD_LIBRARY_PATH'] = os.path.join(cand, 'lib')
                env['LD_PRELOAD'] = os.path.join(cand, 'lib/libtermux-exec-ld-preload.so')
                env['PATH'] = os.path.join(cand, 'bin') + ':' + env.get('PATH', '')
                ffmpeg = cand_bin
                break

    # 找到的 ffmpeg 必须真的能跑：文件存在 ≠ 依赖齐全（上一轮运行在这上面浪费了近 1 小时）。
    if ffmpeg:
        ok, probe_err = probe_ffmpeg(ffmpeg, env)
        if not ok:
            fail(f"找到 ffmpeg（{ffmpeg}）但无法执行（ELF 缺依赖/架构不符）: {probe_err}",
                 TOOLCHAIN_HINT)

    sox = has('sox')

    # 1) 有 ffmpeg → 万能（WAV 之外的所有格式都优先走这里）
    if ffmpeg and ext != '.wav':
        r = subprocess.run([ffmpeg, '-y', '-i', src, '-ar', '16000', '-ac', '1',
                            '-vn', dst], capture_output=True, text=True, timeout=900, env=env)
        if r.returncode == 0 and os.path.getsize(dst) > 0:
            print(f"OK: ffmpeg 提取 -> {dst}")
            return
        fail(f"ffmpeg 提取失败: {r.stderr[-400:]}",
             "该文件可能没有音频轨，或容器格式不受支持（若 ffmpeg 是刚装好的，"
             "先跑 ffmpeg -version 确认依赖完整）")

    # 2) 纯 WAV
    if ext == '.wav':
        resample_wav_to_16k_mono(src, dst)
        return

    # 3) 无 ffmpeg/sox 的兜底路径
    if ext in ('.mp3', '.m4a', '.aac', '.flac', '.ogg', '.opus'):
        fail(f"未找到 ffmpeg/sox，无法解码 {ext} 音频", TOOLCHAIN_HINT)
    if ext in ('.mp4', '.mov'):
        # 纯 Python 分离 AAC 轨 → 包络近似解码为 16k mono WAV（精度差，仅供应急）
        here = os.path.dirname(os.path.abspath(__file__))
        aac_out = dst.rsplit('.', 1)[0] + '.aac'
        r1 = subprocess.call([sys.executable, os.path.join(here, "mp4_extract_aac.py"), src, aac_out])
        if r1 != 0 or not os.path.getsize(aac_out):
            fail(f"MP4/MOV 音频轨分离失败（{aac_out}）",
                 "该文件可能无音频轨或容器异常；请用「降级方案」把音频导成 .wav/.mp3 再上传")
        r2 = subprocess.call([sys.executable, os.path.join(here, "decode_aac.py"), aac_out, dst])
        if r2 == 0 and os.path.getsize(dst) > 0:
            print(f"OK: MP4→AAC→WAV（包络近似） -> {dst}")
            print("HINT: 这是包络近似重建（非精确解码），转写质量差属预期。装好工具链 ffmpeg 后重跑即可，"
                  "或改传 .wav 原音频", file=sys.stderr)
            return
        fail(f"AAC 解码为 WAV 失败（退出码 {r2}），已产出中间文件 {aac_out}",
             f"请手动把 {aac_out} 在别处解码为 16kHz mono .wav 再上传，或提供 .srt/.vtt 字幕")
    if ext in ('.mkv', '.avi', '.webm', '.ts'):
        fail(f"本环境缺少 ffmpeg，无法从 {ext} 视频容器中分离音频轨", TOOLCHAIN_HINT)
    fail(f"不支持的文件类型: {ext}",
         "支持: .mp4 .mov .mkv .avi .webm .ts .mp3 .m4a .aac .flac .ogg .opus .wav")

if __name__ == '__main__':
    main()
