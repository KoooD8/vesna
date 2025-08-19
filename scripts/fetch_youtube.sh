# Download audio from YouTube URLs list into Obsidian Inbox/Audio
# Usage:
#   scripts/fetch_youtube.sh urls.txt
# Requires: yt-dlp

set -euo pipefail

LIST_FILE=${1:-}
if [ -z "$LIST_FILE" ] || [ ! -f "$LIST_FILE" ]; then
  echo "Usage: $0 urls.txt" >&2
  exit 1
fi

# Resolve vault path from config
PYCODE='from config import load_config; c=load_config(); print(c.vault_path)'
VAULT_PATH=$(python3 -c "$PYCODE")
OUT_DIR="$VAULT_PATH/Inbox/Audio"
mkdir -p "$OUT_DIR"

yt-dlp -f bestaudio --extract-audio --audio-format mp3 --audio-quality 0 -o "$OUT_DIR/%(title)s.%(ext)s" -a "$LIST_FILE"

echo "Saved audio files to: $OUT_DIR"
