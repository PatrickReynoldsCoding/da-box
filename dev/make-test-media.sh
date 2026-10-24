#!/usr/bin/env bash
# Makes test films, shows, posters and music with ffmpeg, in the folder layout the box expects.
# The lengths are like real content (20 min films, 7-11 min episodes, 2-4 min songs), so the
# TV guide and the limits look as they do on a real box. It takes a few minutes the first time.
# Usage: dev/make-test-media.sh [target folder]   (default: dev/media)
#   SECONDS_PER_FILM=90 dev/make-test-media.sh   shorter films, for a quick start
set -euo pipefail

target="${1:-$(dirname "$0")/media}"
seconds="${SECONDS_PER_FILM:-1200}"

ffmpeg_quiet() { ffmpeg -hide_banner -loglevel error -y "$@"; }

# Some test sources (mandelbrot, life) are slow to draw, so each video is a short clip,
# looped without encoding again, with a tone for its whole length.
clip_seconds=30

make_video() {
  local file="$1" source="$2" tone="$3" length="$4" quality="$5" filters="${6:-null}"
  local clip="${file%.mp4}.clip.mp4"
  ffmpeg_quiet -f lavfi -i "$source" -t "$(( length < clip_seconds ? length : clip_seconds ))" -vf "$filters" \
    -pix_fmt yuv420p -c:v libx264 -preset veryfast -crf "$quality" "$clip"
  ffmpeg_quiet -stream_loop -1 -i "$clip" -f lavfi -i "sine=frequency=$tone:sample_rate=48000" \
    -t "$length" -map 0:v -map 1:a -c:v copy -c:a aac -b:a 64k "$file"
  rm -f "$clip"
}

make_film() {
  local folder="$target/Films/$1" source="$2" tone="$3"
  [[ -f "$folder/$1.mp4" ]] && return
  mkdir -p "$folder"
  # Films are long, so they are smaller (960 wide, 15 frames a second) to keep dev/media small.
  make_video "$folder/$1.mp4" "$source" "$tone" "$seconds" 30 "fps=15,scale=960:-2"
  # Poster: one frame, cropped to a 2:3 portrait.
  ffmpeg_quiet -ss 2 -i "$folder/$1.mp4" -frames:v 1 -vf "crop=ih*2/3:ih,scale=400:600" "$folder/poster.jpg"
}

make_album() {
  local artist="$1" album="$2" cover_source="$3"
  shift 3
  local folder="$target/Music/$artist/$album" number=1
  [[ -f "$folder/cover.jpg" ]] && return
  mkdir -p "$folder"
  ffmpeg_quiet -f lavfi -i "$cover_source" -frames:v 1 -vf "scale=500:500" "$folder/cover.jpg"
  for frequency in "$@"; do
    # 2 to 4 minutes, like a real song.
    local duration=$((120 + (frequency * 7) % 120))
    ffmpeg_quiet -f lavfi -i "sine=frequency=$frequency:duration=$duration" -b:a 64k \
      -metadata title="Tone $frequency Hz" -metadata artist="$artist" -metadata album="$album" \
      -metadata track="$number" "$folder/$(printf '%02d' "$number") Tone $frequency.mp3"
    number=$((number + 1))
  done
}

make_episode() {
  local show="$1" season="$2" episode="$3" title="$4" source="$5" seconds="$6"
  local folder="$target/TV/$show/Season $(printf '%02d' "$season")"
  local file="$folder/$show S$(printf '%02d' "$season")E$(printf '%02d' "$episode") - $title.mp4"
  [[ -f "$file" ]] && return
  mkdir -p "$folder"
  make_video "$file" "$source" "$((200 + episode * 50))" "$seconds" 32
  [[ -f "$target/TV/$show/poster.jpg" ]] || \
    ffmpeg_quiet -ss 1 -i "$file" -frames:v 1 -vf "crop=ih*2/3:ih,scale=400:600" "$target/TV/$show/poster.jpg"
}

echo "Making test media in $target"
make_film "Rainbow Bars (2024)" "smptehdbars=size=1280x720:rate=30" 440
make_film "Test Card (2025)" "testsrc2=size=1280x720:rate=30" 330
make_film "Game of Life" "life=size=320x180:mold=10:rate=30:ratio=0.1:death_color=#1a0b3d:life_color=#ffcc33,scale=1280:720:flags=neighbor" 262
make_film "Fractal Trip (2023)" "mandelbrot=size=1280x720:rate=30" 523
make_album "Sine Wave Band" "Greatest Tones" "gradients=size=500x500:seed=3" 262 330 392
make_album "The Oscillators" "Low and High" "gradients=size=500x500:seed=11" 196 523 880
make_episode "Shape Friends" 1 1 "Circles" "testsrc2=size=960x540:rate=25" 420
make_episode "Shape Friends" 1 2 "Squares" "smptebars=size=960x540:rate=25" 540
make_episode "Shape Friends" 1 3 "Triangles" "rgbtestsrc=size=960x540:rate=25" 480
make_episode "Shape Friends" 2 1 "Spirals" "mandelbrot=size=960x540:rate=25" 660
# Test games: the 240p Test Suite by Damian Yerrick (zlib licence, free to share).
download_game() {
  local system="$1" name="$2" url="$3"
  local file="$target/Games/$system/$name"
  [[ -f "$file" ]] && return
  mkdir -p "$target/Games/$system"
  curl -sSfL -o "$file" "$url" || { rm -f "$file"; echo "Could not download $name (no internet?)"; }
}
download_game nes "240p Test Suite.nes" "https://github.com/pinobatch/240p-test-mini/releases/download/v0.23/240pee.nes"
download_game gb "240p Test Suite.gb" "https://github.com/pinobatch/240p-test-mini/releases/download/v0.23/gb240p.gb"
download_game gba "240p Test Suite.gba" "https://github.com/pinobatch/240p-test-mini/releases/download/v0.23/240pee_mb.gba"
echo "Done."
