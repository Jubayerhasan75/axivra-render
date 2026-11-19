#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
render_reel.py  --  Axivra Tech / Free AI Social Automation
Builds a 1080x1920 vertical reel from: images + narration audio + captions + music.
100% FFmpeg. No paid API.

Usage:  python3 render_reel.py /data/work/<job_id>

Expects <job_id>/manifest.json :
{
  "scenes": [ {"image":"scene_1.png", "audio":"scene_1.mp3", "text":"caption line"} , ... ],
  "music":  "music.mp3",            # optional, relative or absolute
  "output": "final.mp4",            # optional, default final.mp4
  "width": 1080, "height": 1920, "fps": 30,
  "transition": 0.4,                # seconds of crossfade between scenes
  "tail": 0.35,                     # silent padding added after each narration
  "music_volume": 0.12,
  "font": "Poppins",
  "subtitles": true
}
Prints a JSON result line on stdout:
  {"ok":true,"output":"/data/work/<id>/final.mp4","duration":38.4,"scenes":6}
"""

import glob
import json
import os
import random
import shlex
import subprocess
import sys

# --------------------------------------------------------------------------- utils

def run(cmd, label):
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if p.returncode != 0:
        tail = p.stderr.decode("utf-8", "replace").strip().splitlines()[-25:]
        raise RuntimeError("%s failed:\n%s" % (label, "\n".join(tail)))
    return p.stdout.decode("utf-8", "replace")


def probe_duration(path):
    out = run([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", path
    ], "ffprobe " + os.path.basename(path)).strip()
    try:
        return float(out)
    except ValueError:
        raise RuntimeError("could not read duration of " + path)


def ass_time(t):
    if t < 0:
        t = 0.0
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = t % 60
    return "%d:%02d:%05.2f" % (h, m, s)


def srt_time(t):
    if t < 0:
        t = 0.0
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = int(t % 60)
    ms = int(round((t - int(t)) * 1000))
    if ms == 1000:
        ms = 999
    return "%02d:%02d:%02d,%03d" % (h, m, s, ms)


def wrap_caption(text, max_chars=26):
    """Wrap to at most 2-3 short lines so it reads well on a phone."""
    words = str(text).split()
    lines, cur = [], ""
    for w in words:
        if not cur:
            cur = w
        elif len(cur) + 1 + len(w) <= max_chars:
            cur += " " + w
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return "\n".join(lines[:3])


def ass_escape(p):
    """Escape a path for use inside the subtitles= filter argument."""
    return p.replace("\\", "/").replace(":", "\\:").replace("'", "\\'")


# --------------------------------------------------------------------------- main

def main():
    if len(sys.argv) < 2:
        raise SystemExit("usage: render_reel.py <workdir>")
    work = os.path.abspath(sys.argv[1])
    man_path = os.path.join(work, "manifest.json")
    with open(man_path, "r", encoding="utf-8") as fh:
        man = json.load(fh)

    W = int(man.get("width", 1080))
    H = int(man.get("height", 1920))
    FPS = int(man.get("fps", 30))
    XF = float(man.get("transition", 0.4))
    TAIL = float(man.get("tail", 0.35))
    MUSIC_VOL = float(man.get("music_volume", 0.12))
    FONT = man.get("font", "Poppins")
    WANT_SUBS = bool(man.get("subtitles", True))
    FIT = man.get("fit", "blur")
    out_name = man.get("output", "final.mp4")
    out_path = out_name if os.path.isabs(out_name) else os.path.join(work, out_name)

    scenes = man.get("scenes") or []
    if not scenes:
        raise RuntimeError("manifest has no scenes")

    def rel(p):
        return p if os.path.isabs(p) else os.path.join(work, p)

    # ---------------------------------------------------------------- 1. per-scene clips
    # Oversample the still (4x-ish) so the Ken Burns zoom stays sharp, crop to the
    # target aspect, then zoompan down to exactly WxH.
    BIG_W, BIG_H = int(W * 1.5), int(H * 1.5)
    clips, durs = [], []

    for i, sc in enumerate(scenes):
        img = rel(sc["image"])
        aud = rel(sc["audio"]) if sc.get("audio") else None
        if not os.path.exists(img):
            raise RuntimeError("missing image: " + img)

        scene_fit = sc.get("fit", FIT)
        if scene_fit == "blur":
            prep = os.path.join(work, "prep_%02d.png" % i)
            run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", img,
                 "-vf",
                 "split=2[bg][fg];"
                 "[bg]scale=%d:%d:force_original_aspect_ratio=increase,crop=%d:%d,"
                 "gblur=sigma=%d,eq=brightness=-0.10:saturation=1.1[bgb];"
                 "[fg]scale=%d:%d:force_original_aspect_ratio=decrease[fgs];"
                 "[bgb][fgs]overlay=(W-w)/2:(H-h)/2,setsar=1"
                 % (BIG_W, BIG_H, BIG_W, BIG_H, max(12, BIG_W // 34), BIG_W, BIG_H),
                 "-frames:v", "1", prep], "scene %d blur-fill" % (i + 1))
            img = prep

        if aud:
            if not os.path.exists(aud):
                raise RuntimeError("missing audio: " + aud)
            d = probe_duration(aud) + TAIL
        else:
            d = float(sc.get("duration", 3.5))
        d = max(1.2, round(d, 3))
        durs.append(d)

        frames = max(2, int(round(d * FPS)))
        # alternate zoom-in / zoom-out and pan direction so the reel never feels static
        zoom_in = (i % 2 == 0)
        if zoom_in:
            zexpr = "min(1+0.0011*on,1.22)"
        else:
            zexpr = "max(1.22-0.0011*on,1.0)"
        pans = [
            ("iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"),                     # centre
            ("(iw-iw/zoom)*(on/%d)" % frames, "ih/2-(ih/zoom/2)"),        # pan right
            ("iw/2-(iw/zoom/2)", "(ih-ih/zoom)*(on/%d)" % frames),        # pan down
            ("(iw-iw/zoom)*(1-on/%d)" % frames, "ih/2-(ih/zoom/2)"),      # pan left
        ]
        px, py = pans[i % len(pans)]

        vf = (
            "scale=%d:%d:force_original_aspect_ratio=increase,"
            "crop=%d:%d,setsar=1,"
            "zoompan=z='%s':x='%s':y='%s':d=%d:s=%dx%d:fps=%d,"
            "format=yuv420p"
            % (BIG_W, BIG_H, BIG_W, BIG_H, zexpr, px, py, frames, W, H, FPS)
        )

        clip = os.path.join(work, "clip_%02d.mp4" % i)
        cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
               "-loop", "1", "-framerate", str(FPS), "-t", "%.3f" % d, "-i", img]
        if aud:
            cmd += ["-i", aud]
            fc = ("[0:v]" + vf + "[v];"
                  "[1:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,apad[a]")
        else:
            cmd += ["-f", "lavfi", "-t", "%.3f" % d,
                    "-i", "anullsrc=channel_layout=stereo:sample_rate=48000"]
            fc = ("[0:v]" + vf + "[v];"
                  "[1:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo[a]")
        cmd += ["-filter_complex", fc, "-map", "[v]", "-map", "[a]"]
        cmd += ["-t", "%.3f" % d,
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                "-pix_fmt", "yuv420p", "-r", str(FPS),
                "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2",
                clip]
        run(cmd, "scene %d render" % (i + 1))
        clips.append(clip)

    # ---------------------------------------------------------------- 2. concat + xfade
    n = len(clips)
    total = sum(durs) - XF * (n - 1) if n > 1 else durs[0]

    stitched = os.path.join(work, "stitched.mp4")
    if n == 1:
        stitched = clips[0]
    else:
        cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
        for c in clips:
            cmd += ["-i", c]
        parts, vprev, aprev, offset = [], "[0:v]", "[0:a]", 0.0
        for i in range(1, n):
            offset += durs[i - 1] - XF
            vout = "[v%d]" % i
            aout = "[a%d]" % i
            parts.append("%s[%d:v]xfade=transition=fade:duration=%.3f:offset=%.3f%s"
                         % (vprev, i, XF, offset, vout))
            parts.append("%s[%d:a]acrossfade=d=%.3f:c1=tri:c2=tri%s"
                         % (aprev, i, XF, aout))
            vprev, aprev = vout, aout
        cmd += ["-filter_complex", ";".join(parts),
                "-map", vprev, "-map", aprev,
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                "-pix_fmt", "yuv420p", "-r", str(FPS),
                "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2",
                stitched]
        run(cmd, "xfade concat")

    # ---------------------------------------------------------------- 3. subtitles
    sub_path = os.path.join(work, "captions.ass")
    has_subs = False
    if WANT_SUBS and any(s.get("text") for s in scenes):
        cap_size = int(man.get("caption_size", round(H * 0.038)))
        cap_margin = int(man.get("caption_margin", round(H * 0.17)))
        outline = max(3, int(cap_size * 0.11))
        side = int(W * 0.075)
        header = (
            "[Script Info]\n"
            "ScriptType: v4.00+\n"
            "PlayResX: %d\nPlayResY: %d\n"
            "WrapStyle: 0\nScaledBorderAndShadow: yes\nYCbCr Matrix: TV.709\n\n"
            "[V4+ Styles]\n"
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
            "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, "
            "ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, "
            "MarginL, MarginR, MarginV, Encoding\n"
            "Style: Cap,%s,%d,&H00FFFFFF,&H000000FF,&H00101010,&H90000000,"
            "-1,0,0,0,100,100,0,0,1,%d,%d,2,%d,%d,%d,1\n\n"
            "[Events]\n"
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, Effect, Text\n"
            % (W, H, FONT, cap_size, outline, max(2, outline // 2),
               side, side, cap_margin)
        )
        events, t0 = [], 0.0
        for i, sc in enumerate(scenes):
            start = t0
            end = start + durs[i] - (XF if i < n - 1 else 0.0) - 0.05
            txt = wrap_caption(sc.get("text", ""), int(man.get("caption_wrap", 28)))
            if txt.strip():
                events.append("Dialogue: 0,%s,%s,Cap,,0,0,,%s"
                              % (ass_time(start), ass_time(max(end, start + 0.6)),
                                 txt.replace("\n", "\\N")))
            t0 = end + 0.05
        if events:
            with open(sub_path, "w", encoding="utf-8") as fh:
                fh.write(header + "\n".join(events) + "\n")
            has_subs = True

    # ---------------------------------------------------------------- 4. music + burn-in
    music = man.get("music")
    music_path = None
    if music in ("auto", "random", True):
        pool = []
        for ext in ("*.mp3", "*.m4a", "*.wav", "*.ogg"):
            pool += glob.glob(os.path.join(rel(man.get("music_dir", "/data/music")), ext))
        if pool:
            music_path = random.choice(sorted(pool))
    elif music:
        music_path = rel(music)
    if music_path and not os.path.exists(music_path):
        music_path = None

    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", stitched]
    if music_path:
        cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
               "-i", stitched, "-stream_loop", "-1", "-i", music_path]

    chain = []
    vlabel = "[0:v]"
    if has_subs:
        chain.append("%ssubtitles='%s'[vsub]" % (vlabel, ass_escape(sub_path)))
        vlabel = "[vsub]"
    chain.append("%sfade=t=in:st=0:d=0.5,fade=t=out:st=%.3f:d=0.5[vout]"
                 % (vlabel, max(0.0, total - 0.5)))

    if music_path:
        chain.append("[1:a]volume=%.3f,afade=t=out:st=%.3f:d=1.2[mus]" % (MUSIC_VOL, max(0.0, total - 1.2)))
        chain.append("[0:a][mus]amix=inputs=2:duration=first:dropout_transition=0:normalize=0,"
                     "alimiter=limit=0.95,aresample=48000[aout]")
    else:
        chain.append("[0:a]alimiter=limit=0.95,aresample=48000[aout]")

    cmd += ["-filter_complex", ";".join(chain),
            "-map", "[vout]", "-map", "[aout]",
            "-t", "%.3f" % total,
            "-c:v", "libx264", "-preset", "medium", "-crf", "21",
            "-profile:v", "high", "-level", "4.1", "-pix_fmt", "yuv420p",
            "-r", str(FPS), "-g", str(FPS * 2),
            "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2",
            "-movflags", "+faststart", out_path]
    run(cmd, "final mux")

    real = probe_duration(out_path)
    size = os.path.getsize(out_path)
    print(json.dumps({
        "ok": True, "output": out_path, "duration": round(real, 2),
        "scenes": n, "bytes": size, "subtitles": has_subs,
        "music": bool(music_path)
    }))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": str(exc)}))
        sys.exit(1)
