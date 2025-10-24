#!/usr/bin/env bash
# Full ClipsAI pipeline (GitHub-friendly)
# 1) quicktest.py  -> download + find clips (prompts for URL here)
# 2) subtitles.py  -> generate SRTs (no burning)
# 3) design.py     -> final 1080x1920 render + single subtitle burn (uses repo template)

set -Eeuo pipefail

# ========= Resolve locations =========
# PROJECT_DIR: folder containing this script (clipsai/)
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
PROJECT_DIR="$SCRIPT_DIR"

# MEDIA_DIR: parent of PROJECT_DIR by default (e.g., /home/<user>/)
# Override by exporting CLIPSAI_MEDIA_DIR=/path/to/media
MEDIA_DIR="${CLIPSAI_MEDIA_DIR:-"$(cd "$PROJECT_DIR/.." && pwd)"}"

VIDEOS_DIR="$MEDIA_DIR/videos"
CLIPS_DIR="$MEDIA_DIR/clips"
SUBS_DIR="$MEDIA_DIR/subtitles"
DESIGNED_DIR="$MEDIA_DIR/designed"

mkdir -p "$VIDEOS_DIR" "$CLIPS_DIR" "$SUBS_DIR" "$DESIGNED_DIR"

# ========= Friendly intro =========
echo " ClipsAI pipeline"
echo "Project:  $PROJECT_DIR"
echo "Media:    $MEDIA_DIR"
echo "Videos:   $VIDEOS_DIR"
echo "Clips:    $CLIPS_DIR"
echo "Subs:     $SUBS_DIR"
echo "Designed: $DESIGNED_DIR"
echo

# ========= Ask for inputs =========
read -rp " Enter YouTube URL: " URL
if [[ -z "$URL" ]]; then
  echo "No URL provided. Exiting." >&2
  exit 1
fi

read -rp " Use a PYANNOTE token for smart cropping? (y/n): " USE_TOKEN
TOKEN=""
if [[ "$USE_TOKEN" =~ ^[Yy]$ ]]; then
  read -rp " Enter your PYANNOTE_AUTH_TOKEN: " TOKEN
  export PYANNOTE_AUTH_TOKEN="$TOKEN"
fi

# Optional: cookies path for yt-dlp (used by quicktest.py automatically if it exists)
# export CLIPSAI_COOKIES="$MEDIA_DIR/cookies.txt"

# ========= Preflight =========
need() { command -v "$1" >/dev/null 2>&1 || { echo "Missing dependency: $1" >&2; exit 1; }; }
need python3
need ffmpeg
need yt-dlp

# ========= 1) Download + clip finding =========
echo "==> Step 1/3: Download + clip finder"
# quicktest.py reads URL from stdin
printf '%s\n' "$URL" | python3 "$PROJECT_DIR/quicktest.py"

# ========= 2) Generate SRTs (no burning) =========
echo "==> Step 2/3: Transcribe to SRT"
python3 "$PROJECT_DIR/subtitles.py"

# ========= 3) Final design + single subtitle burn =========
echo "==> Step 3/3: Design vertical clips & burn captions once"
# Rely on design.py's defaults:
# - template: $PROJECT_DIR/templates/emigr8_vertical.png
# - input/output: $MEDIA_DIR/clips -> $MEDIA_DIR/designed
# - subs auto-detected from $MEDIA_DIR/subtitles
DESIGN_CMD=(python3 "$PROJECT_DIR/design.py"
  --subs_mode auto
  --subs_dir "$SUBS_DIR"
)

# Pass token explicitly only if captured here (design.py also checks env)
if [[ -n "${TOKEN}" ]]; then
  DESIGN_CMD+=(--pyannote_token "$TOKEN")
fi

"${DESIGN_CMD[@]}"

echo
echo " Done!"
echo "• Clips:      $CLIPS_DIR"
echo "• Subtitles:  $SUBS_DIR"
echo "• Designed:   $DESIGNED_DIR"
