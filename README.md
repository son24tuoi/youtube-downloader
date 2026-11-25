# YouTube Downloader

Tool tải video **và âm thanh** từ YouTube, có giao diện, chạy trên **Windows 10/11**. Dán link, xem trước, chọn độ phân giải / dung lượng hoặc chỉ lấy tiếng (MP3, M4A, Opus, WAV). Bản portable chạy ngay, **không cần cài Python**.

## Tính năng

**Chung**
- Nhận link `youtube.com/watch`, `youtu.be`, Shorts. Link playlist thì lấy video đầu tiên
- Xem trước: ảnh bìa, tiêu đề, kênh, thời lượng, lượt xem, ngày đăng + **phát thử 30 giây đầu** (chỉ tải đoạn đó, nhẹ)
- **Tự chọn bản tốt nhất có dung lượng ≤ N MB**, hiện dung lượng ước tính trước khi tải
- Thanh tiến trình (hình 1/2, tiếng 2/2), tốc độ, thời gian còn lại, nút huỷ
- Cookies từ Firefox / Edge / Chrome / Brave hoặc file `cookies.txt` (video giới hạn tuổi, "xác nhận không phải bot")

**🎬 Video**
- Bảng chất lượng: độ phân giải (tới 4K/8K, HDR), FPS, codec, dung lượng (đã cộng phần tiếng)
- Tự ghép hình + tiếng thành **MP4 (AAC)**
- Mặc định chỉ hiện **H.264** (≤1080p, phát được ở mọi nơi). Bỏ tick để thấy VP9/AV1 độ phân giải cao
- Tuỳ chọn chuyển VP9/AV1 → H.264 sau khi tải, **tự dùng GPU** (NVIDIA NVENC / Intel QSV / AMD AMF) nếu có

**🎵 Chỉ âm thanh**
- Xuất **MP3 / M4A (AAC) / Opus / WAV** hoặc giữ nguyên bản gốc (không chuyển đổi, không giảm chất lượng)
- Chọn bitrate 128 / 192 / 256 / 320 kbps
- Gắn **ảnh bìa + tên bài + tên kênh** vào file

## Tải về & sử dụng

1. Vào [**Releases**](../../releases) → tải `YouTubeDownloader_Portable.zip`
2. Giải nén cả thư mục → nhấp đúp `YouTubeDownloader.exe`
3. Nếu Windows SmartScreen cảnh báo: **More info → Run anyway** (exe chưa ký số)

YouTube thay đổi thường xuyên; khi tải lỗi, chạy `Cap nhat yt-dlp.bat` trong thư mục portable.

## Chạy từ source

Cần Python 3.10+:

```bat
run_from_source.bat
```

hoặc:

```bash
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python src\app.py
```

`requirements.txt` đã gồm `imageio-ffmpeg` (ffmpeg) và `deno` (JS runtime mà yt-dlp cần để đọc link YouTube), không phải cài riêng.

## Build bản portable

**GitHub Actions:** push tag `v*` → tự build và gắn zip vào Release.

```bash
git tag v1.0.0
git push origin v1.0.0
```

Hoặc **Actions → Build portable → Run workflow** để lấy file ở mục Artifacts.

**Thủ công (Linux / WSL):**

```bash
sudo apt install gcc-mingw-w64-x86-64 zip
./scripts/build_portable.sh      # -> dist/YouTubeDownloader_Portable.zip
```

## Cấu trúc

```
src/app.py                 Giao diện Tkinter + logic tải (yt-dlp)
src/icon.ico               Icon
launcher/launcher.c        Launcher .exe: chạy python\pythonw.exe app\app.py
scripts/build_portable.sh  Đóng gói: Python standalone + thư viện win_amd64 + ffmpeg + deno
.github/workflows/         CI build + release
```

## Công nghệ

[yt-dlp](https://github.com/yt-dlp/yt-dlp) · [Deno](https://deno.com) · [FFmpeg](https://ffmpeg.org) (qua imageio-ffmpeg) · [Pillow](https://python-pillow.org) · [python-build-standalone](https://github.com/astral-sh/python-build-standalone) · Tkinter

## Lưu ý

Chỉ tải nội dung bạn sở hữu hoặc được phép sử dụng, và tuân thủ [Điều khoản dịch vụ của YouTube](https://www.youtube.com/t/terms). Dự án không liên kết với YouTube/Google.

## License

[MIT](LICENSE)
