#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
axivra_job.py -- runs inside GitHub Actions for one render job sent by n8n.

n8n (AX4 Create Reel / AX5 Animate Image) sends a repository_dispatch event:
    event_type: axivra-render
    client_payload:
      reel    -> {job_id, kind:"reel", title, voice_lang, scenes:[{narration, caption, image_prompt}]}
      animate -> {job_id, kind:"animate", telegram_file_id, text, duration}

This script:
  1. builds every asset for free (Cloudflare Workers AI images + voice, or the
     Telegram photo for "animate"),
  2. renders the MP4 with render_reel.py (FFmpeg),
  3. writes result.json for the workflow to upload and report back to n8n.

Standard library only.
"""

import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CF_ACCOUNT = os.environ.get("CF_ACCOUNT_ID", "").strip()
CF_TOKEN = os.environ.get("CF_API_TOKEN", "").strip()
TG_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
FLUX = "@cf/black-forest-labs/flux-1-schnell"
TTS = "@cf/deepgram/aura-2-en"


def log(msg):
    sys.stderr.write("[axivra] %s\n" % msg)
    sys.stderr.flush()


def http(url, data=None, headers=None, timeout=180, tries=3):
    last = None
    for attempt in range(1, tries + 1):
        try:
            req = urllib.request.Request(url, data=data, headers=headers or {},
                                         method="POST" if data is not None else "GET")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read(), resp.headers.get("Content-Type", "")
        except urllib.error.HTTPError as exc:
            body = exc.read()[:400].decode("utf-8", "replace")
            last = "HTTP %s from %s: %s" % (exc.code, url.split("?")[0], body)
            if exc.code in (400, 401, 403, 404):
                break
        except Exception as exc:  # noqa: BLE001
            last = "%s calling %s" % (exc, url.split("?")[0])
        log("attempt %d failed: %s" % (attempt, last))
        time.sleep(4 * attempt)
    raise RuntimeError(last or "request failed")


def cf_run(model, payload):
    if not CF_ACCOUNT or not CF_TOKEN:
        raise RuntimeError("CF_ACCOUNT_ID / CF_API_TOKEN secrets are missing in the GitHub repo")
    url = "https://api.cloudflare.com/client/v4/accounts/%s/ai/run/%s" % (CF_ACCOUNT, model)
    raw, ctype = http(url, json.dumps(payload).encode("utf-8"),
                      {"Authorization": "Bearer " + CF_TOKEN, "Content-Type": "application/json"})
    return raw, ctype


def b64_from_json(raw, key):
    data = json.loads(raw.decode("utf-8"))
    if isinstance(data, dict) and data.get("success") is False:
        raise RuntimeError("Cloudflare error: %s" % json.dumps(data.get("errors"))[:300])
    res = data.get("result", data) if isinstance(data, dict) else {}
    val = res.get(key) if isinstance(res, dict) else None
    if not val:
        raise RuntimeError("Cloudflare response has no '%s' field" % key)
    return base64.b64decode(val)


def make_image(prompt, path):
    raw, ctype = cf_run(FLUX, {"prompt": prompt[:2000], "steps": 6})
    img = raw if ctype.startswith("image/") else b64_from_json(raw, "image")
    with open(path, "wb") as fh:
        fh.write(img)


EDGE_VOICES = {
    "EN": "en-US-AndrewNeural", "BN": "bn-BD-NabanitaNeural", "HI": "hi-IN-SwaraNeural",
    "ES": "es-ES-ElviraNeural", "FR": "fr-FR-DeniseNeural", "AR": "ar-SA-ZariyahNeural",
    "UR": "ur-PK-UzmaNeural", "ZH": "zh-CN-XiaoxiaoNeural", "JP": "ja-JP-NanamiNeural",
}


def voice_name(lang):
    lang = str(lang or "EN").strip()
    if "Neural" in lang:
        return lang
    return EDGE_VOICES.get(lang.upper(), EDGE_VOICES["EN"])


def make_voice(text, lang, path):
    """Free Microsoft Edge neural voice (no key). Falls back to Cloudflare aura-2-en for English."""
    import subprocess
    voice = voice_name(lang)
    last = ""
    for attempt in range(1, 4):
        proc = subprocess.run(["edge-tts", "--voice", voice, "--text", text[:1500], "--write-media", path],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)
        if proc.returncode == 0 and os.path.exists(path) and os.path.getsize(path) > 2000:
            return
        last = proc.stderr.decode("utf-8", "replace")[-300:]
        log("edge-tts attempt %d failed: %s" % (attempt, last))
        time.sleep(3 * attempt)
    if voice.startswith("en-"):
        log("falling back to Cloudflare aura-2-en")
        raw, ctype = cf_run(TTS, {"text": text[:1500]})
        audio = raw if ctype.startswith("audio/") else b64_from_json(raw, "audio")
        with open(path, "wb") as fh:
            fh.write(audio)
        return
    raise RuntimeError("voice generation failed: " + last)


def telegram_download(file_id, path):
    if not TG_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN secret is missing in the GitHub repo")
    raw, _ = http("https://api.telegram.org/bot%s/getFile?file_id=%s" % (TG_TOKEN, urllib.request.quote(file_id)))
    info = json.loads(raw.decode("utf-8"))
    if not info.get("ok"):
        raise RuntimeError("Telegram getFile failed: %s" % info.get("description"))
    fpath = info["result"]["file_path"]
    raw, _ = http("https://api.telegram.org/file/bot%s/%s" % (TG_TOKEN, fpath), timeout=120)
    with open(path, "wb") as fh:
        fh.write(raw)


def main():
    event_path = os.environ.get("GITHUB_EVENT_PATH", "")
    with open(event_path, "r", encoding="utf-8") as fh:
        event = json.load(fh)
    p = event.get("client_payload") or {}
    if not p and event.get("inputs", {}).get("payload"):
        p = json.loads(event["inputs"]["payload"])
    job = "".join(c for c in str(p.get("job_id") or "test_job") if c.isalnum() or c in "_-")[:60]
    kind = str(p.get("kind") or "reel")
    work = os.path.join(ROOT, "work", job)
    os.makedirs(work, exist_ok=True)
    out_name = job + ".mp4"
    manifest = {
        "output": os.path.join(ROOT, "out", out_name),
        "music": "auto",
        "music_dir": os.path.join(ROOT, "music"),
        "music_volume": 0.12,
        "font": "Noto Sans Bengali" if voice_name(p.get("voice_lang")).startswith("bn-") else "DejaVu Sans",
        "subtitles": True,
    }
    os.makedirs(os.path.join(ROOT, "out"), exist_ok=True)

    if kind == "reel":
        scenes = p.get("scenes") or []
        if len(scenes) < 1:
            raise RuntimeError("reel job has no scenes")
        built = []
        for i, sc in enumerate(scenes[:7], start=1):
            img = os.path.join(work, "scene_%d.jpg" % i)
            aud = os.path.join(work, "scene_%d.mp3" % i)
            log("scene %d: image" % i)
            make_image(str(sc.get("image_prompt") or sc.get("caption") or "abstract background"), img)
            entry = {"image": img, "text": str(sc.get("caption") or "")}
            narration = str(sc.get("narration") or "").strip()
            if narration:
                log("scene %d: voice" % i)
                make_voice(narration, p.get("voice_lang"), aud)
                entry["audio"] = aud
            else:
                entry["duration"] = 3.5
            built.append(entry)
        manifest["scenes"] = built
    elif kind == "animate":
        img = os.path.join(work, "source.jpg")
        log("downloading source image from Telegram")
        telegram_download(str(p.get("telegram_file_id") or ""), img)
        dur = max(4.0, min(20.0, float(p.get("duration") or 8)))
        manifest["scenes"] = [{"image": img, "duration": dur, "text": str(p.get("text") or "")}]
        manifest["transition"] = 0.0
    else:
        raise RuntimeError("unknown job kind: " + kind)

    with open(os.path.join(work, "manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=2)

    import subprocess
    proc = subprocess.run([sys.executable, os.path.join(HERE, "render_reel.py"), work],
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    lines = [l for l in proc.stdout.decode("utf-8", "replace").splitlines() if l.strip()]
    result = json.loads(lines[-1]) if lines else {}
    if proc.returncode != 0 or not result.get("ok"):
        raise RuntimeError("render failed: %s %s" % (result.get("error", ""),
                                                     proc.stderr.decode("utf-8", "replace")[-600:]))
    result.update({"job_id": job, "kind": kind, "file": result["output"], "name": out_name})
    return result


if __name__ == "__main__":
    status_file = os.path.join(ROOT, "result.json")
    try:
        res = main()
        res["status"] = "done"
    except Exception as exc:  # noqa: BLE001
        log("FAILED: %s" % exc)
        res = {"status": "failed", "error": str(exc)[:900]}
        try:
            with open(os.environ.get("GITHUB_EVENT_PATH", ""), "r", encoding="utf-8") as fh:
                ev = json.load(fh)
            res["job_id"] = str((ev.get("client_payload") or {}).get("job_id") or "")
        except Exception:  # noqa: BLE001
            pass
    with open(status_file, "w", encoding="utf-8") as fh:
        json.dump(res, fh)
    print(json.dumps(res))
