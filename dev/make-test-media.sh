#!/usr/bin/env bash
# Makes small test films, posters and music with ffmpeg, in the folder layout the box expects.
# Usage: dev/make-test-media.sh [target folder]   (default: dev/media)
set -euo pipefail

target="${1:-$(dirname "$0")/media}"
seconds="${SECONDS_PER_FILM:-90}"

ffmpeg_quiet() { ffmpeg -hide_banner -loglevel error -y "$@"; }

make_film() {
  local folder="$target/Films/$1" source="$2" tone="$3"
  mkdir -p "$folder"
  ffmpeg_quiet -f lavfi -i "$source" -f lavfi -i "sine=frequency=$tone:sample_rate=48000" \
    -t "$seconds" -pix_fmt yuv420p -c:v libx264 -preset veryfast -c:a aac -shortest "$folder/$1.mp4"
  # Poster: one frame, cropped to a 2:3 portrait.
  ffmpeg_quiet -ss 2 -i "$folder/$1.mp4" -frames:v 1 -vf "crop=ih*2/3:ih,scale=400:600" "$folder/poster.jpg"
}

make_album() {
  local artist="$1" album="$2" cover_source="$3"
  shift 3
  local folder="$target/Music/$artist/$album" number=1
  mkdir -p "$folder"
  ffmpeg_quiet -f lavfi -i "$cover_source" -frames:v 1 -vf "scale=500:500" "$folder/cover.jpg"
  for frequency in "$@"; do
    ffmpeg_quiet -f lavfi -i "sine=frequency=$frequency:duration=30" \
      -metadata title="Tone $frequency Hz" -metadata artist="$artist" -metadata album="$album" \
      -metadata track="$number" "$folder/$(printf '%02d' "$number") Tone $frequency.mp3"
    number=$((number + 1))
  done
}

echo "Making test media in $target"
make_film "Rainbow Bars (2024)" "smptehdbars=size=1280x720:rate=30" 440
make_film "Test Card (2025)" "testsrc2=size=1280x720:rate=30" 330
make_film "Game of Life" "life=size=1280x720:mold=10:rate=30:ratio=0.1:death_color=#1a0b3d:life_color=#ffcc33,scale=1280:720:flags=neighbor" 262
make_film "Fractal Trip (2023)" "mandelbrot=size=1280x720:rate=30" 523
make_album "Sine Wave Band" "Greatest Tones" "gradients=size=500x500:seed=3" 262 330 392
make_album "The Oscillators" "Low and High" "gradients=size=500x500:seed=11" 196 523 880
echo "Done."
