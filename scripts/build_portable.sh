#!/usr/bin/env bash
# Build bản portable cho Windows x64 (chạy trên Linux/WSL hoặc GitHub Actions ubuntu).
# Cần: curl, tar, zip, python3 + pip, gcc-mingw-w64-x86-64.
# Kết quả: dist/YouTubeDownloader_Portable.zip
set -euo pipefail

PBS_TAG="${PBS_TAG:-20251120}"
PY_VER="${PY_VER:-3.12.12}"
PY_URL="https://github.com/astral-sh/python-build-standalone/releases/download/${PBS_TAG}/cpython-${PY_VER}+${PBS_TAG}-x86_64-pc-windows-msvc-install_only_stripped.tar.gz"
PY_MINOR="$(echo "$PY_VER" | cut -d. -f1,2 | tr -d .)"   # 312

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BUILD="$ROOT/build"
OUT="$BUILD/YouTubeDownloader"
DIST="$ROOT/dist"
rm -rf "$BUILD" "$DIST"
mkdir -p "$OUT/app" "$DIST" "$BUILD/download"

echo ">> Tải Python ${PY_VER} cho Windows (có tkinter)"
curl -fsSL -o "$BUILD/download/python.tar.gz" "$PY_URL"
tar -xzf "$BUILD/download/python.tar.gz" -C "$OUT"
rm -rf "$OUT/python/include" "$OUT/python/libs"

echo ">> Cài thư viện bản Windows vào python/Lib/site-packages"
python3 -m pip install --quiet --upgrade \
  --target "$OUT/python/Lib/site-packages" \
  --platform win_amd64 --python-version "${PY_VER%.*}" \
  --implementation cp --abi "cp${PY_MINOR}" --only-binary=:all: --no-compile \
  -r "$ROOT/requirements.txt"

echo ">> Build launcher YouTubeDownloader.exe"
x86_64-w64-mingw32-windres "$ROOT/launcher/res.rc" -O coff -o "$BUILD/res.o"
x86_64-w64-mingw32-gcc -O2 -municode -mwindows -static \
  "$ROOT/launcher/launcher.c" "$BUILD/res.o" -o "$OUT/YouTubeDownloader.exe"
x86_64-w64-mingw32-strip "$OUT/YouTubeDownloader.exe"

echo ">> Copy app"
cp "$ROOT/src/app.py" "$ROOT/src/icon.ico" "$OUT/app/"

printf '@echo off\r\nchcp 65001 >nul\r\ncd /d "%%~dp0"\r\necho Dang cap nhat yt-dlp (can Internet)...\r\n"python\\python.exe" -m pip install -U --no-warn-script-location "yt-dlp[default,curl-cffi]"\r\necho.\r\necho Xong. Mo lai YouTubeDownloader.exe\r\npause\r\n' > "$OUT/Cap nhat yt-dlp.bat"
printf 'YOUTUBE DOWNLOADER - BAN PORTABLE (Windows 10/11, 64-bit)\r\n\r\nGiai nen ca thu muc roi nhap dup YouTubeDownloader.exe. Khong can cai Python.\r\nGiu nguyen thu muc "python" va "app" ben canh file exe.\r\nTai bi loi (YouTube doi cach chay): chay "Cap nhat yt-dlp.bat".\r\n\r\nChi tai video ban co quyen su dung.\r\n' > "$OUT/README.txt"

echo ">> Nén"
(cd "$BUILD" && zip -qr -9 "$DIST/YouTubeDownloader_Portable.zip" YouTubeDownloader)
ls -lh "$DIST"
