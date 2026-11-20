#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
render_poster.py -- builds a 1080x1350 (4:5) brand poster for
Digital Automation & IT Solutions and renders it with headless Chrome.

    python3 render_poster.py data.json background.jpg out.jpg

data.json fields (all text is written by Gemini in n8n AX8):
  theme        "dark" | "light" | "warm"
  headline     text; words to highlight go in [[double brackets]]
  subline      one short line (may contain " • " separators)
  features     [{"icon": "<icon key>", "label": "Faster Websites"}, ...]  (3 or 4)
  cta          button text
  corner_left  [3-4 short words]   corner_right [3-4 short words]
  tagline      short letter-spaced line
  website, email, company   (footer; filled from ax_config)

Everything is local: fonts and logo live next to this file, so the output is
identical on every run. Standard library only (+ Google Chrome, preinstalled on
GitHub's ubuntu runners).
"""

import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
W, H = 1080, 1350

ICONS = {
    "gauge": '<path d="m12 14 4-4"/><path d="M3.34 19a10 10 0 1 1 17.32 0"/>',
    "shield": '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><path d="m9 12 2 2 4-4"/>',
    "lock": '<rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>',
    "refresh": '<path d="M21 12a9 9 0 1 1-3-6.7L21 8"/><path d="M21 3v5h-5"/>',
    "cloud": '<path d="M17.5 19H9a7 7 0 1 1 6.71-9h1.79a4.5 4.5 0 1 1 0 9Z"/>',
    "cloud_upload": '<path d="M4 14.9A7 7 0 1 1 15.7 8h1.8a4.5 4.5 0 0 1 2.5 8.2"/><path d="M12 12v9"/><path d="m16 16-4-4-4 4"/>',
    "lightbulb": '<path d="M9 18h6"/><path d="M10 22h4"/><path d="M12 2a7 7 0 0 0-4 12.7V17h8v-2.3A7 7 0 0 0 12 2z"/>',
    "gear": '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1A1.7 1.7 0 0 0 9 19.4a1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1A1.7 1.7 0 0 0 4.6 15a1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1A1.7 1.7 0 0 0 4.6 9a1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1A1.7 1.7 0 0 0 9 4.6a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8 1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>',
    "chart": '<path d="M3 3v18h18"/><path d="M7 16v-3"/><path d="M12 16V9"/><path d="M17 16V5"/>',
    "trending": '<path d="m22 7-8.5 8.5-5-5L2 17"/><path d="M16 7h6v6"/>',
    "code": '<path d="m16 18 6-6-6-6"/><path d="m8 6-6 6 6 6"/>',
    "target": '<circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/>',
    "mail": '<rect x="2" y="4" width="20" height="16" rx="2"/><path d="m22 7-10 6L2 7"/>',
    "globe": '<circle cx="12" cy="12" r="10"/><path d="M2 12h20"/><path d="M12 2a15 15 0 0 1 0 20a15 15 0 0 1 0-20"/>',
    "rocket": '<path d="M4.5 16.5c-1.5 1.3-2 5-2 5s3.7-.5 5-2c.7-.8.7-2.1-.1-2.9a2.2 2.2 0 0 0-2.9-.1z"/><path d="m12 15-3-3a22 22 0 0 1 2-4A12.9 12.9 0 0 1 22 2c0 2.7-.8 7.5-6 11a22.4 22.4 0 0 1-4 2z"/>',
    "clock": '<circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/>',
    "users": '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.9"/><path d="M16 3.1a4 4 0 0 1 0 7.8"/>',
    "workflow": '<rect x="3" y="3" width="8" height="8" rx="2"/><path d="M7 11v4a2 2 0 0 0 2 2h4"/><rect x="13" y="13" width="8" height="8" rx="2"/>',
    "check": '<circle cx="12" cy="12" r="10"/><path d="m9 12 2 2 4-4"/>',
    "smartphone": '<rect x="5" y="2" width="14" height="20" rx="2"/><path d="M12 18h.01"/>',
    "database": '<ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5v14a9 3 0 0 0 18 0V5"/><path d="M3 12a9 3 0 0 0 18 0"/>',
    "cart": '<circle cx="8" cy="21" r="1"/><circle cx="19" cy="21" r="1"/><path d="M2 2h3l2.7 12.4a2 2 0 0 0 2 1.6h9.7a2 2 0 0 0 2-1.6L23 6H6"/>',
    "message": '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>',
    "search": '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>',
    "zap": '<path d="M13 2 3 14h9l-1 8 10-12h-9l1-8z"/>',
    "bot": '<rect x="3" y="11" width="18" height="10" rx="2"/><circle cx="12" cy="5" r="2"/><path d="M12 7v4"/><path d="M8 16h.01"/><path d="M16 16h.01"/>',
    "file": '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/><path d="M9 13h6"/><path d="M9 17h4"/>',
    "layout": '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18"/><path d="M9 21V9"/>',
    "handshake": '<path d="m11 17 2 2a1 1 0 1 0 3-3"/><path d="m14 14 2.5 2.5a1 1 0 1 0 3-3l-3.9-3.9a2 2 0 0 0-2.8 0l-.9.9a1 1 0 1 1-3-3l2.8-2.8a5.8 5.8 0 0 1 7.1-.9l.5.3a2 2 0 0 0 1.3.3H21"/><path d="m21 3 1 11h-2"/><path d="M3 3 2 14l6.5 6.5a1 1 0 1 0 3-3"/><path d="M3 4h8"/>',
    "wallet": '<path d="M19 7V4a1 1 0 0 0-1-1H5a2 2 0 0 0 0 4h15a1 1 0 0 1 1 1v4h-3a2 2 0 0 0 0 4h3a1 1 0 0 0 1-1v-2a1 1 0 0 0-1-1"/><path d="M3 5v14a2 2 0 0 0 2 2h15a1 1 0 0 0 1-1v-4"/>',
    "calendar": '<rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4"/><path d="M8 2v4"/><path d="M3 10h18"/>',
    "star": '<path d="m12 2 3.1 6.3 6.9 1-5 4.9 1.2 6.8L12 17.8 5.8 21l1.2-6.8-5-4.9 6.9-1z"/>',
    "arrow": '<path d="M5 12h14"/><path d="m12 5 7 7-7 7"/>',
}
ICON_ALIASES = {"speed": "gauge", "security": "shield", "update": "refresh", "backup": "cloud_upload",
                "idea": "lightbulb", "settings": "gear", "growth": "trending", "analytics": "chart",
                "automation": "workflow", "crm": "database", "support": "message", "ai": "bot",
                "website": "layout", "mobile": "smartphone", "time": "clock", "team": "users",
                "money": "wallet", "invoice": "file", "email": "mail", "ecommerce": "cart"}


def svg(name, size=48, stroke=1.8, extra=""):
    key = ICON_ALIASES.get(str(name or "").lower().strip(), str(name or "").lower().strip())
    body = ICONS.get(key, ICONS["check"])
    return ('<svg %s width="%d" height="%d" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
            'stroke-width="%s" stroke-linecap="round" stroke-linejoin="round">%s</svg>' % (extra, size, size, stroke, body))


def esc(s):
    return html.escape(str(s or ""), quote=True)


def headline_html(text):
    """[[word]] -> highlighted span. If nothing is marked, highlight the last line-ish half."""
    text = str(text or "").strip()
    if "[[" not in text:
        words = text.split()
        cut = max(1, len(words) // 2)
        text = " ".join(words[:cut]) + " [[" + " ".join(words[cut:]) + "]]"
    out, pos = [], 0
    for m in re.finditer(r"\[\[(.+?)\]\]", text):
        out.append(esc(text[pos:m.start()]))
        out.append('<span class="hl">%s</span>' % esc(m.group(1)))
        pos = m.end()
    out.append(esc(text[pos:]))
    return "".join(out).replace("\n", "<br>")


def stack(words):
    return "<br>".join(esc(w) for w in (words or [])[:5])


def lines(text, n=3):
    words = str(text or "").split()
    if not words:
        return ""
    n = max(1, min(n, len(words)))
    target = sum(len(w) for w in words) / n
    out, cur = [], []
    for w in words:
        cur.append(w)
        if len(out) < n - 1 and sum(len(x) for x in cur) >= target:
            out.append(" ".join(cur)); cur = []
    if cur:
        out.append(" ".join(cur))
    return "<br>".join(esc(l) for l in out)


def font_faces():
    rows = []
    for weight, name in ((400, "Regular"), (500, "Medium"), (600, "SemiBold"), (700, "Bold"), (800, "ExtraBold"), (900, "Black")):
        rows.append("@font-face{font-family:'Poppins';font-weight:%d;src:url('fonts/Poppins-%s.ttf');}" % (weight, name))
    rows.append("@font-face{font-family:'Montserrat';font-weight:100 900;src:url('fonts/Montserrat.ttf');}")
    return "\n".join(rows)


BASE_CSS = """
*{margin:0;padding:0;box-sizing:border-box}
html,body{width:1080px;height:1350px;overflow:hidden}
body{font-family:'Poppins',sans-serif;position:relative;-webkit-font-smoothing:antialiased}
.bg{position:absolute;inset:0;background-size:cover;background-position:center}
.layer{position:absolute;inset:0}
.micro{font-family:'Montserrat',sans-serif;font-weight:600;font-size:13px;letter-spacing:.32em;line-height:1.75;text-transform:uppercase}
.micro:after{content:"";display:block;width:34px;height:2px;margin-top:10px;border-radius:2px}
.cta{display:inline-flex;align-items:center;gap:22px;border-radius:999px;font-weight:700;font-size:29px;padding:0 14px 0 46px;height:86px;white-space:nowrap}
.cta .dot{width:58px;height:58px;border-radius:50%;display:flex;align-items:center;justify-content:center}
.foot{display:flex;align-items:center;gap:14px;font-size:22px;font-weight:500}
#hl,#sub{text-wrap:balance}
"""

FIT_JS = """
<script>
function fit(id, max, min){var e=document.getElementById(id);if(!e)return;var box=e.parentElement;
 var limit=parseFloat(e.getAttribute('data-maxh'));var s=max;e.style.fontSize=s+'px';
 while(s>min&&(e.scrollHeight>limit||e.scrollWidth>e.clientWidth+2)){s-=2;e.style.fontSize=s+'px';}}
document.fonts.ready.then(function(){fit('hl',%(hmax)d,%(hmin)d);fit('sub',%(smax)d,%(smin)d);fit('ctatext',29,20);document.body.setAttribute('data-ready','1');});
</script>
"""


def page(theme_css, body, fit):
    return ("<!doctype html><html><head><meta charset='utf-8'><style>%s\n%s\n%s</style></head><body>%s%s</body></html>"
            % (font_faces(), BASE_CSS, theme_css, body, FIT_JS % fit))


def footer_items(d, color_icon):
    return ('<div class="foot">%s<span>%s</span></div><div class="foot">%s<span>%s</span></div>'
            % (svg("globe", 26, 1.8, 'style="color:%s"' % color_icon), esc(d.get("website")),
               svg("mail", 26, 1.8, 'style="color:%s"' % color_icon), esc(d.get("email"))))


# ---------------------------------------------------------------- DARK (tech)
def theme_dark(d, bg):
    feats = (d.get("features") or [])[:4]
    half = (len(feats) + 1) // 2
    def col(items):
        return "".join('<div class="card">%s<div class="lbl">%s</div></div>'
                       % (svg(f.get("icon"), 54, 1.7), esc(f.get("label"))) for f in items)
    css = """
body{background:#030b1c;color:#fff}
.bg{background-image:url('%s');background-position:center 70%%;filter:saturate(1.15) contrast(1.05)}
.l1{background:linear-gradient(180deg,#030b1c 0%%,rgba(3,11,28,.96) 24%%,rgba(3,11,28,.55) 42%%,rgba(3,11,28,.15) 58%%,rgba(3,11,28,.35) 74%%,rgba(3,11,28,.97) 88%%,#030b1c 100%%)}
.l2{background:radial-gradient(ellipse 60%% 28%% at 50%% 4%%,rgba(26,180,232,.32),transparent 70%%),radial-gradient(ellipse 70%% 22%% at 50%% 78%%,rgba(34,211,238,.20),transparent 70%%)}
.logo{position:absolute;top:42px;left:50%%;transform:translateX(-50%%);background:rgba(255,255,255,.95);border-radius:22px;padding:16px 34px;box-shadow:0 0 0 1px rgba(255,255,255,.6),0 0 42px rgba(26,180,232,.55)}
.logo img{height:74px;display:block}
.micro{position:absolute;top:44px;color:rgba(170,215,255,.62)} .micro:after{background:#1ab4e8}
.ml{left:46px} .mr{right:46px;text-align:right} .mr:after{margin-left:auto}
.mb{top:auto;bottom:52px}
.head{position:absolute;top:190px;left:60px;right:60px;text-align:center}
#hl{font-weight:800;line-height:1.06;letter-spacing:-.01em;text-shadow:0 4px 30px rgba(0,0,0,.45)}
#hl .hl{background:linear-gradient(90deg,#22d3ee,#1ab4e8 45%%,#2ee6c0);-webkit-background-clip:text;background-clip:text;color:transparent;filter:drop-shadow(0 0 18px rgba(34,211,238,.35))}
#sub{margin-top:22px;font-weight:500;color:rgba(255,255,255,.88);line-height:1.45}
.col{position:absolute;top:610px;display:flex;flex-direction:column;gap:26px}
.cl{left:44px} .cr{right:44px}
.card{width:176px;height:176px;border-radius:24px;background:linear-gradient(160deg,rgba(26,180,232,.20),rgba(5,20,48,.55));border:1.5px solid rgba(34,211,238,.55);box-shadow:0 0 28px rgba(34,211,238,.25),inset 0 0 22px rgba(34,211,238,.10);backdrop-filter:blur(6px);display:flex;flex-direction:column;align-items:center;justify-content:center;gap:14px;color:#7ee8fa;text-align:center;padding:12px}
.card .lbl{font-weight:700;font-size:16px;letter-spacing:.06em;text-transform:uppercase;color:#fff;line-height:1.25}
.tag{position:absolute;top:1028px;left:0;right:0;text-align:center;font-family:'Montserrat';font-weight:600;font-size:14px;letter-spacing:.42em;color:rgba(170,230,255,.75);text-transform:uppercase}
.tag:before{content:"";display:block;margin:0 auto 14px;width:520px;height:2px;background:linear-gradient(90deg,transparent,#22d3ee,transparent);box-shadow:0 0 14px #22d3ee}
.ctaw{position:absolute;top:1088px;left:0;right:0;text-align:center}
.cta{background:linear-gradient(90deg,#2ee6a8,#22d3ee);color:#04121f;box-shadow:0 0 36px rgba(46,230,168,.45),0 10px 30px rgba(0,0,0,.35)}
.cta .dot{background:#04121f;color:#2ee6a8}
.foots{position:absolute;top:1206px;left:0;right:0;display:flex;flex-direction:column;align-items:center;gap:8px;color:#e6f6ff}
""" % bg
    body = """
<div class="bg"></div><div class="layer l1"></div><div class="layer l2"></div>
<div class="micro ml">%s</div><div class="micro mr">%s</div>
<div class="logo"><img src="assets/logo.png"></div>
<div class="head"><div id="hl" data-maxh="250" style="font-size:86px">%s</div><div id="sub" data-maxh="100" style="font-size:30px">%s</div></div>
<div class="col cl">%s</div><div class="col cr">%s</div>
<div class="tag">%s</div>
<div class="ctaw"><div class="cta"><span id="ctatext" data-maxh="60">%s</span><span class="dot">%s</span></div></div>
<div class="foots">%s</div>
<div class="micro ml mb">%s</div><div class="micro mr mb">%s</div>
""" % (stack(d.get("corner_left")), stack(d.get("corner_right")), headline_html(d.get("headline")), esc(d.get("subline")),
       col(feats[:half]), col(feats[half:]), esc(d.get("tagline")), esc(d.get("cta")), svg("arrow", 30, 2.6),
       footer_items(d, "#22d3ee"), lines(d.get("company") or "Digital Automation & IT Solutions"), lines("Technology for a brighter tomorrow"))
    return page(css, body, {"hmax": 86, "hmin": 56, "smax": 30, "smin": 22})


# ------------------------------------------------------------- LIGHT (office)
def theme_light(d, bg):
    feats = (d.get("features") or [])[:3]
    items = "".join('<div class="f">%s<div class="lbl">%s</div></div>' % (svg(f.get("icon"), 46, 1.6), esc(f.get("label"))) for f in feats)
    css = """
body{background:#f6f8fc;color:#0f1f4b}
.bg{background-image:url('%s');background-position:72%% center}
.l1{background:linear-gradient(90deg,#f7f9fd 0%%,rgba(247,249,253,.97) 40%%,rgba(247,249,253,.80) 52%%,rgba(247,249,253,.25) 66%%,rgba(247,249,253,0) 78%%)}
.l2{background:linear-gradient(180deg,rgba(247,249,253,.55) 0%%,transparent 18%%,transparent 82%%,rgba(247,249,253,.75) 100%%)}
.logo{position:absolute;top:58px;left:62px} .logo img{height:84px;display:block}
.flow{position:absolute;top:196px;left:62px;width:620px;display:flex;flex-direction:column;align-items:flex-start}
#hl{font-weight:800;line-height:1.06;letter-spacing:-.015em;color:#0f1f4b;width:100%%}
#hl .hl{color:#1a73e8}
#sub{margin-top:20px;font-weight:400;color:#24345e;line-height:1.35;width:100%%}
.feats{margin-top:54px;width:600px;display:flex}
.f{flex:1;display:flex;flex-direction:column;align-items:center;gap:12px;color:#1f3f8a;padding:0 10px;border-right:1.5px solid rgba(31,63,138,.18);text-align:center}
.f:last-child{border-right:0}
.f .lbl{font-weight:700;font-size:15px;letter-spacing:.08em;text-transform:uppercase;color:#0f1f4b;line-height:1.3}
.ctaw{margin-top:60px}
.cta{background:linear-gradient(90deg,#a87a35,#d6a75a 55%%,#b98a3e);color:#fff;box-shadow:0 14px 30px rgba(168,122,53,.35)}
.cta .dot{background:rgba(255,255,255,.18);color:#fff}
.steps{margin-top:30px;width:560px;font-family:'Montserrat';font-weight:600;font-size:13px;letter-spacing:.42em;color:#46557e;text-transform:uppercase;display:flex;align-items:center;gap:18px}
.steps:before,.steps:after{content:"";flex:0 0 46px;height:1.5px;background:#b98a3e}
.foots{position:absolute;bottom:56px;left:52px;padding:18px 26px;border-radius:18px;background:rgba(255,255,255,.88);box-shadow:0 10px 30px rgba(15,31,75,.10);display:flex;flex-direction:column;gap:6px;color:#0f1f4b}
.micro{position:absolute;bottom:62px;right:56px;text-align:right;color:#24345e} .micro:after{background:#b98a3e;margin-left:auto}
""" % bg
    body = """
<div class="bg"></div><div class="layer l1"></div><div class="layer l2"></div>
<div class="logo"><img src="assets/logo.png"></div>
<div class="flow"><div id="hl" data-maxh="350" style="font-size:84px">%s</div><div id="sub" data-maxh="110" style="font-size:34px">%s</div>
<div class="feats">%s</div>
<div class="ctaw"><div class="cta"><span id="ctatext">%s</span><span class="dot">%s</span></div></div>
<div class="steps">%s</div></div>
<div class="foots">%s</div>
<div class="micro">%s</div>
""" % (headline_html(d.get("headline")), esc(d.get("subline")), items, esc(d.get("cta")), svg("arrow", 30, 2.6),
       " ".join(esc(w) for w in (d.get("corner_left") or [])[:4]), footer_items(d, "#1a73e8"),
       lines(d.get("tagline") or "Technology for a brighter tomorrow"))
    return page(css, body, {"hmax": 84, "hmin": 54, "smax": 34, "smin": 24})


# --------------------------------------------------------------- WARM (desk)
def theme_warm(d, bg):
    feats = (d.get("features") or [])[:4]
    chips = "".join('<div class="chip"><span class="ic">%s</span><span class="t">%s</span><span class="ok">%s</span></div>'
                    % (svg(f.get("icon"), 30, 1.8), esc(f.get("label")), svg("check", 26, 2.2)) for f in feats)
    css = """
body{background:#fbf7f1;color:#0f172a}
.bg{background-image:url('%s');background-position:center 60%%;filter:saturate(1.05)}
.l1{background:linear-gradient(180deg,rgba(252,248,242,.97) 0%%,rgba(252,248,242,.93) 22%%,rgba(252,248,242,.55) 36%%,rgba(252,248,242,0) 50%%)}
.l2{background:linear-gradient(180deg,transparent 62%%,rgba(10,22,52,.25) 80%%,rgba(10,22,52,.55) 100%%)}
.logo{position:absolute;top:52px;left:58px} .logo img{height:80px;display:block}
.head{position:absolute;top:178px;left:58px;right:58px}
#hl{font-weight:800;line-height:1.05;letter-spacing:-.02em;color:#0b1530}
#hl .hl{background:linear-gradient(90deg,#1f3f8a,#1a73e8 50%%,#1ab4e8);-webkit-background-clip:text;background-clip:text;color:transparent}
#sub{margin-top:16px;font-weight:500;color:#1e293b;line-height:1.35}
.chips{position:absolute;top:540px;right:46px;display:flex;flex-direction:column;gap:22px}
.chip{width:330px;height:92px;border-radius:20px;background:linear-gradient(135deg,rgba(10,40,90,.78),rgba(26,115,232,.55));border:1.5px solid rgba(26,180,232,.85);box-shadow:0 0 26px rgba(26,180,232,.45);backdrop-filter:blur(8px);display:flex;align-items:center;gap:16px;padding:0 20px;color:#fff}
.chip .ic{width:52px;height:52px;border-radius:14px;background:rgba(255,255,255,.14);display:flex;align-items:center;justify-content:center;color:#bdeeff;flex:none}
.chip .t{flex:1;font-weight:600;font-size:21px;line-height:1.15}
.chip .ok{color:#5ef0c4;flex:none}
.wave{position:absolute;left:0;right:0;bottom:0;height:330px}
.ctaw{position:absolute;top:1000px;left:0;right:0;text-align:center}
.cta{background:linear-gradient(90deg,#1f3f8a,#1a73e8 60%%,#1ab4e8);color:#fff;box-shadow:0 0 0 2px rgba(255,255,255,.55),0 14px 34px rgba(10,30,80,.45)}
.cta .dot{background:#fff;color:#1f3f8a}
.foots{position:absolute;top:1206px;left:0;right:0;display:flex;justify-content:center;gap:34px;color:#fff}
.foots .foot{font-size:21px}
.micro{position:absolute;bottom:26px;font-size:12px;color:rgba(255,255,255,.72)} .micro:after{background:#1ab4e8}
.ml{left:52px} .mr{right:52px;text-align:right} .mr:after{margin-left:auto}
""" % bg
    wave = ('<svg class="wave" viewBox="0 0 1080 330" preserveAspectRatio="none">'
            '<defs><linearGradient id="g1" x1="0" x2="1"><stop offset="0" stop-color="#0b1a3e"/><stop offset="1" stop-color="#1f3f8a"/></linearGradient>'
            '<linearGradient id="g2" x1="0" x2="1"><stop offset="0" stop-color="#1a73e8"/><stop offset="1" stop-color="#1ab4e8"/></linearGradient></defs>'
            '<path d="M0 95 C 260 45, 440 150, 700 90 S 960 55, 1080 95 L1080 330 L0 330Z" fill="url(#g2)" opacity=".9"/>'
            '<path d="M0 145 C 270 100, 480 190, 730 135 S 985 110, 1080 145 L1080 330 L0 330Z" fill="url(#g1)"/></svg>')
    body = """
<div class="bg"></div><div class="layer l1"></div><div class="layer l2"></div>
<div class="logo"><img src="assets/logo.png"></div>
<div class="head"><div id="hl" data-maxh="230" style="font-size:88px">%s</div><div id="sub" data-maxh="90" style="font-size:36px">%s</div></div>
<div class="chips">%s</div>
%s
<div class="ctaw"><div class="cta"><span id="ctatext">%s</span><span class="dot">%s</span></div></div>
<div class="foots">%s</div>
<div class="micro ml">%s</div><div class="micro mr">%s</div>
""" % (headline_html(d.get("headline")), esc(d.get("subline")), chips, wave, esc(d.get("cta")), svg("arrow", 30, 2.6),
       footer_items(d, "#7fd8ff"), stack(d.get("corner_left")), stack(d.get("corner_right")))
    return page(css, body, {"hmax": 88, "hmin": 56, "smax": 36, "smin": 24})


THEMES = {"dark": theme_dark, "light": theme_light, "warm": theme_warm}


def chrome_bin():
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
        path = shutil.which(name)
        if path:
            return path
    raise RuntimeError("Google Chrome / Chromium is not installed")


def validate(data):
    """Refuse to draw an incomplete poster - a clear error is better than a broken image."""
    problems = []
    head = re.sub(r"[\[\]\s]", "", str(data.get("headline") or ""))
    if len(head) < 6:
        problems.append("headline is missing")
    feats = [f for f in (data.get("features") or []) if isinstance(f, dict) and str(f.get("label") or "").strip()]
    if len(feats) < 3:
        problems.append("fewer than 3 features")
    if not str(data.get("cta") or "").strip():
        problems.append("button text is missing")
    if not str(data.get("website") or "").strip() or not str(data.get("email") or "").strip():
        problems.append("website / email are missing")
    if problems:
        raise RuntimeError("poster data incomplete: " + ", ".join(problems) +
                           " (if this repeats, scripts/axivra_job.py on GitHub is outdated)")


def render(data, bg_path, out_path, scale=2):
    validate(data)
    theme = str(data.get("theme") or "dark").lower()
    if theme not in THEMES:
        theme = "dark"
    work = tempfile.mkdtemp(prefix="poster_")
    for sub in ("fonts", "assets"):
        os.symlink(os.path.join(HERE, sub), os.path.join(work, sub))
    bg_name = "bg" + os.path.splitext(bg_path)[1].lower()
    shutil.copyfile(bg_path, os.path.join(work, bg_name))
    page_path = os.path.join(work, "poster.html")
    with open(page_path, "w", encoding="utf-8") as fh:
        fh.write(THEMES[theme](data, bg_name))
    png = os.path.join(work, "poster.png")
    cmd = [chrome_bin(), "--headless=new", "--no-sandbox", "--disable-gpu", "--hide-scrollbars",
           "--allow-file-access-from-files", "--force-device-scale-factor=%s" % scale,
           "--window-size=%d,%d" % (W, H), "--virtual-time-budget=8000",
           "--screenshot=%s" % png, "file://" + page_path]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)
    if not os.path.exists(png):
        raise RuntimeError("Chrome did not produce a screenshot: " + proc.stderr.decode("utf-8", "replace")[-400:])
    # high-quality JPEG keeps Telegram/Facebook uploads small while text stays crisp
    try:
        from PIL import Image
        Image.open(png).convert("RGB").save(out_path, "JPEG", quality=94, subsampling=0, optimize=True)
    except Exception:  # noqa: BLE001 - Pillow missing: ship the PNG instead
        shutil.copyfile(png, out_path)
    shutil.rmtree(work, ignore_errors=True)
    return {"ok": True, "theme": theme, "output": out_path, "width": W * scale, "height": H * scale}


if __name__ == "__main__":
    if len(sys.argv) != 4:
        sys.exit("usage: render_poster.py data.json background.jpg out.jpg")
    with open(sys.argv[1], encoding="utf-8") as fh:
        payload = json.load(fh)
    print(json.dumps(render(payload, sys.argv[2], sys.argv[3])))
