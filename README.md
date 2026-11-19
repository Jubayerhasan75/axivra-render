# axivra-render

Free video render worker for the AXIVRA n8n system.

n8n sends a `repository_dispatch` event (`axivra-render`) → this repo's GitHub Action
builds the images (Cloudflare flux-1-schnell) and voice-over (Cloudflare melotts),
renders a 1080x1920 MP4 with FFmpeg (Ken Burns zoom, crossfades, burned captions,
ducked music), uploads it to the `renders` release and calls the n8n
**Render Callback** webhook.

Keep this repository **public** – GitHub Actions minutes are free and unlimited for
public repositories. Your keys stay private in *Settings → Secrets and variables → Actions*.

## Secrets (Settings → Secrets and variables → Actions → New repository secret)

| Name | Value |
|---|---|
| `CF_ACCOUNT_ID` | Cloudflare account id |
| `CF_API_TOKEN` | Cloudflare API token with *Workers AI – Read* |
| `TELEGRAM_BOT_TOKEN` | the same bot token you use in n8n |
| `N8N_CALLBACK_URL` | `https://n8n-8ezj.srv2143770.hstgr.cloud/webhook/axivra-render-callback` |
| `N8N_CALLBACK_SECRET` | the value of your n8n *Axivra Render Callback* credential |

## Music

Drop 3–10 royalty-free / CC0 `.mp3` files into `music/`. One is picked at random per
video and mixed at 12 % volume. With no files the video simply has no music.

## Manual test

Actions → **Axivra render** → *Run workflow*, paste:

```json
{"job_id":"test1","kind":"reel","voice_lang":"EN","scenes":[{"narration":"Hello from Axivra. This is a test video.","caption":"Hello from Axivra","image_prompt":"a friendly robot waving in a bright modern office"}]}
```

The run fails at the last step until `N8N_CALLBACK_URL` is set – that is expected.
