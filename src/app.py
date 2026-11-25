"""
YouTube Downloader - GUI cho Windows 10/11
- Nhập link YouTube (video, Shorts, youtu.be; link playlist sẽ lấy video đầu tiên)
- Xem trước: ảnh bìa, tiêu đề, kênh, thời lượng + phát thử 30 giây đầu
- Tải VIDEO: chọn độ phân giải / codec / dung lượng (tự ghép hình + tiếng thành MP4)
- Tải CHỈ ÂM THANH: MP3 / M4A / Opus / WAV, chọn bitrate, gắn ảnh bìa + tên bài
- Tự chọn bản tốt nhất có dung lượng <= N MB
"""
import io
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

try:
    from PIL import Image, ImageTk
except ImportError:
    Image = ImageTk = None

import yt_dlp
from yt_dlp.utils import download_range_func

try:
    import imageio_ffmpeg
except ImportError:
    imageio_ffmpeg = None

APP_TITLE = "YouTube Downloader"
DEFAULT_DIR = os.path.join(os.path.expanduser("~"), "Downloads", "YouTube")
PREVIEW_DIR = os.path.join(tempfile.gettempdir(), "yt_dl_preview")
PREVIEW_SECONDS = 30
NO_WINDOW = 0x08000000 if sys.platform.startswith("win") else 0  # CREATE_NO_WINDOW

AUDIO_FORMATS = {               # nhãn hiển thị -> preferredcodec của yt-dlp
    "MP3": "mp3",
    "M4A (AAC)": "m4a",
    "Opus": "opus",
    "WAV (không nén)": "wav",
    "Giữ nguyên (không chuyển đổi)": "best",
}
AUDIO_QUALITIES = ["128", "192", "256", "320"]
COOKIE_SOURCES = ["Không dùng", "Firefox", "Edge", "Chrome", "Brave", "File cookies.txt..."]


# ---------------------------------------------------------------- helpers
def human_size(n):
    if not n:
        return "?"
    n = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1024
    return f"{n:.1f} TB"


def human_time(sec):
    if not sec:
        return "?"
    sec = int(sec)
    h, m, s = sec // 3600, sec % 3600 // 60, sec % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def fmt_size(f, duration):
    size = f.get("filesize") or f.get("filesize_approx")
    if not size and f.get("tbr") and duration:
        size = f["tbr"] * 1000 / 8 * duration
    return size or 0


def codec_family(f):
    v = (f.get("vcodec") or "").lower()
    if v.startswith(("avc", "h264")):
        return "H.264"
    if v.startswith(("vp09", "vp9")):
        return "VP9"
    if v.startswith("av01"):
        return "AV1"
    if v.startswith(("hev", "hvc", "h265")):
        return "H.265"
    return v.split(".")[0].upper() or "?"


def audio_codec_label(f):
    a = (f.get("acodec") or "").lower()
    if a.startswith("mp4a"):
        return "AAC"
    if a.startswith("opus"):
        return "Opus"
    return a.split(".")[0] or "?"


def is_drc(f):
    return "drc" in (f.get("format_id") or "").lower() or "drc" in (f.get("format_note") or "").lower()


def open_file(path):
    if sys.platform.startswith("win"):
        os.startfile(path)  # noqa
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


def find_ffmpeg():
    if imageio_ffmpeg:
        try:
            return imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            pass
    return shutil.which("ffmpeg")


def find_deno():
    """YouTube cần JS runtime (Deno) để giải mã chữ ký link video."""
    try:
        import deno
        return deno.find_deno_bin()
    except Exception:
        return shutil.which("deno")


_H264_ENCODER = None


def pick_h264_encoder(ffmpeg):
    """Ưu tiên encoder phần cứng (NVIDIA / Intel / AMD), không có thì dùng libx264."""
    global _H264_ENCODER
    if _H264_ENCODER:
        return _H264_ENCODER
    for enc in ("h264_nvenc", "h264_qsv", "h264_amf"):
        try:
            r = subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-f", "lavfi",
                                "-i", "color=s=640x360:d=0.2", "-c:v", enc, "-f", "null", "-"],
                               capture_output=True, timeout=20, creationflags=NO_WINDOW)
            if r.returncode == 0:
                _H264_ENCODER = enc
                return enc
        except Exception:
            pass
    _H264_ENCODER = "libx264"
    return _H264_ENCODER


ENCODER_ARGS = {
    "libx264": ["-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p"],
    "h264_nvenc": ["-preset", "p4", "-rc", "vbr", "-cq", "21", "-b:v", "0"],
    "h264_qsv": ["-global_quality", "21"],
    "h264_amf": ["-quality", "balanced", "-rc", "cqp", "-qp_i", "21", "-qp_p", "21"],
}


class Cancelled(Exception):
    pass


# ---------------------------------------------------------------- app
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1040x720")
        self.minsize(920, 640)
        icon = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.ico")
        if os.path.exists(icon):
            try:
                self.iconbitmap(icon)
            except Exception:
                pass

        self.ffmpeg = find_ffmpeg()
        self.deno = find_deno()
        self.info = None
        self.video_rows, self.audio_rows, self.rows = [], [], []
        self.thumb_img = None
        self.busy = False
        self.proc = None
        self.cancel_flag = threading.Event()
        self.ui_queue = queue.Queue()
        self.cookie_file = None

        self.url_var = tk.StringVar()
        self.kind_var = tk.StringVar(value="video")        # video | audio
        self.pick_var = tk.StringVar(value="pick")         # pick | maxsize
        self.maxsize_var = tk.StringVar(value="50")
        self.h264_only_var = tk.BooleanVar(value=True)
        self.convert_var = tk.BooleanVar(value=False)
        self.afmt_var = tk.StringVar(value="MP3")
        self.aq_var = tk.StringVar(value="192")
        self.embed_var = tk.BooleanVar(value=True)
        self.cookie_var = tk.StringVar(value=COOKIE_SOURCES[0])
        self.dir_var = tk.StringVar(value=DEFAULT_DIR)
        self.status_var = tk.StringVar(value="Dán link YouTube rồi bấm 'Lấy thông tin'.")

        self._style()
        self._build()
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.after(50, self._drain_queue)
        if not self.ffmpeg:
            self.status_var.set("⚠ Không tìm thấy ffmpeg: không ghép được video > 360p và không chuyển MP3.")

    # ------------------------------------------------------------ UI
    def _style(self):
        style = ttk.Style(self)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure("Title.TLabel", font=("Segoe UI", 11, "bold"))
        style.configure("Accent.TButton", font=("Segoe UI", 10, "bold"))
        style.configure("Treeview", rowheight=26, font=("Segoe UI", 10))
        style.configure("Treeview.Heading", font=("Segoe UI", 10, "bold"))

    def _build(self):
        pad = dict(padx=10, pady=5)

        # --- URL
        top = ttk.Frame(self)
        top.pack(fill="x", **pad)
        ttk.Label(top, text="Link YouTube:").pack(side="left")
        entry = ttk.Entry(top, textvariable=self.url_var, font=("Segoe UI", 10))
        entry.pack(side="left", fill="x", expand=True, padx=6)
        entry.bind("<Return>", lambda e: self.fetch_info())
        ttk.Button(top, text="Dán", width=6, command=self.paste).pack(side="left")
        self.btn_fetch = ttk.Button(top, text="Lấy thông tin", style="Accent.TButton",
                                    command=self.fetch_info)
        self.btn_fetch.pack(side="left", padx=(6, 0))

        # --- middle
        mid = ttk.Frame(self)
        mid.pack(fill="both", expand=True, **pad)

        left = ttk.LabelFrame(mid, text=" Xem trước ")
        left.pack(side="left", fill="y", padx=(0, 8))
        self.thumb_lbl = tk.Label(left, text="(chưa có video)", width=40, height=10,
                                  bg="#1e1e1e", fg="#aaaaaa")
        self.thumb_lbl.pack(padx=8, pady=8)
        self.title_lbl = ttk.Label(left, text="", wraplength=320, justify="left",
                                   style="Title.TLabel")
        self.title_lbl.pack(fill="x", padx=8)
        self.meta_lbl = ttk.Label(left, text="", wraplength=320, justify="left")
        self.meta_lbl.pack(fill="x", padx=8, pady=(4, 8))
        self.btn_preview = ttk.Button(left, text=f"▶ Phát thử {PREVIEW_SECONDS} giây đầu",
                                      command=self.preview, state="disabled")
        self.btn_preview.pack(fill="x", padx=8, pady=(0, 8), side="bottom")

        right = ttk.LabelFrame(mid, text=" Chọn bản tải ")
        right.pack(side="left", fill="both", expand=True)
        kind = ttk.Frame(right)
        kind.pack(fill="x", padx=8, pady=(6, 0))
        ttk.Radiobutton(kind, text="🎬 Video (hình + tiếng)", value="video",
                        variable=self.kind_var, command=self.on_kind).pack(side="left")
        ttk.Radiobutton(kind, text="🎵 Chỉ âm thanh", value="audio",
                        variable=self.kind_var, command=self.on_kind).pack(side="left", padx=20)

        tbl = ttk.Frame(right)
        tbl.pack(fill="both", expand=True)
        cols = ("q", "size", "detail", "codec", "note")
        self.tree = ttk.Treeview(tbl, columns=cols, show="headings", selectmode="browse")
        for c, w in zip(cols, (120, 100, 100, 80, 220)):
            self.tree.column(c, width=w, anchor="w" if c == "note" else "center")
        sb = ttk.Scrollbar(tbl, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=8)
        sb.pack(side="left", fill="y", pady=8, padx=(0, 8))
        self.tree.bind("<Double-1>", lambda e: self.download())
        self.tree.bind("<<TreeviewSelect>>", lambda e: self.update_estimate())
        self._set_headings()

        # --- options
        opt = ttk.LabelFrame(self, text=" Tuỳ chọn ")
        opt.pack(fill="x", **pad)

        r = ttk.Frame(opt)
        r.pack(fill="x", padx=8, pady=3)
        ttk.Radiobutton(r, text="Tải bản đang chọn trong bảng", value="pick",
                        variable=self.pick_var, command=self.update_estimate).pack(side="left")
        ttk.Radiobutton(r, text="Tự chọn bản tốt nhất có dung lượng ≤", value="maxsize",
                        variable=self.pick_var, command=self.update_estimate).pack(side="left", padx=(20, 4))
        sp = ttk.Spinbox(r, from_=1, to=10000, width=7, textvariable=self.maxsize_var,
                         command=self.update_estimate)
        sp.pack(side="left")
        sp.bind("<KeyRelease>", lambda e: self.update_estimate())
        ttk.Label(r, text="MB").pack(side="left", padx=4)

        self.opt_video = ttk.Frame(opt)
        ttk.Checkbutton(self.opt_video, text="Chỉ hiện bản H.264 (≤1080p, Win 11 phát được ngay)",
                        variable=self.h264_only_var, command=self.refresh_table).pack(side="left")
        self.chk_convert = ttk.Checkbutton(self.opt_video,
                                           text="Chuyển VP9/AV1 → H.264 sau khi tải (chậm với 2K/4K)",
                                           variable=self.convert_var)
        self.chk_convert.pack(side="left", padx=(20, 0))

        self.opt_audio = ttk.Frame(opt)
        ttk.Label(self.opt_audio, text="Định dạng:").pack(side="left")
        cb = ttk.Combobox(self.opt_audio, textvariable=self.afmt_var, values=list(AUDIO_FORMATS),
                          state="readonly", width=28)
        cb.pack(side="left", padx=(4, 16))
        cb.bind("<<ComboboxSelected>>", lambda e: self.on_audio_format())
        ttk.Label(self.opt_audio, text="Chất lượng:").pack(side="left")
        self.cb_q = ttk.Combobox(self.opt_audio, textvariable=self.aq_var, values=AUDIO_QUALITIES,
                                 state="readonly", width=6)
        self.cb_q.pack(side="left", padx=4)
        self.cb_q.bind("<<ComboboxSelected>>", lambda e: self.update_estimate())
        ttk.Label(self.opt_audio, text="kbps").pack(side="left")
        self.chk_embed = ttk.Checkbutton(self.opt_audio, text="Gắn ảnh bìa + tên bài/kênh",
                                         variable=self.embed_var)
        self.chk_embed.pack(side="left", padx=(20, 0))

        self.opt_anchor = ttk.Frame(opt)  # mốc để pack opt_video/opt_audio đúng vị trí
        self.opt_anchor.pack(fill="x")

        r2 = ttk.Frame(opt)
        r2.pack(fill="x", padx=8, pady=3)
        ttk.Label(r2, text="Lưu vào:").pack(side="left")
        ttk.Entry(r2, textvariable=self.dir_var).pack(side="left", fill="x", expand=True, padx=6)
        ttk.Button(r2, text="Chọn...", command=self.choose_dir).pack(side="left")
        ttk.Button(r2, text="Mở thư mục", command=self.open_dir).pack(side="left", padx=(6, 16))
        ttk.Label(r2, text="Cookies:").pack(side="left")
        cc = ttk.Combobox(r2, textvariable=self.cookie_var, values=COOKIE_SOURCES,
                          state="readonly", width=18)
        cc.pack(side="left", padx=4)
        cc.bind("<<ComboboxSelected>>", lambda e: self.on_cookie())

        # --- bottom
        bot = ttk.Frame(self)
        bot.pack(fill="x", **pad)
        self.progress = ttk.Progressbar(bot, mode="determinate", maximum=100)
        self.progress.pack(fill="x")
        row = ttk.Frame(bot)
        row.pack(fill="x", pady=(6, 0))
        ttk.Label(row, textvariable=self.status_var).pack(side="left", fill="x", expand=True)
        self.btn_cancel = ttk.Button(row, text="Huỷ", command=self.cancel, state="disabled")
        self.btn_cancel.pack(side="right")
        self.btn_dl = ttk.Button(row, text="⬇ Tải về", style="Accent.TButton",
                                 command=self.download, state="disabled")
        self.btn_dl.pack(side="right", padx=6)

        self.on_kind()

    def _set_headings(self):
        if self.kind_var.get() == "video":
            heads = ("Độ phân giải", "Dung lượng", "FPS", "Codec", "Ghi chú")
        else:
            heads = ("Bitrate gốc", "Dung lượng", "Tần số", "Codec", "Ngôn ngữ / ghi chú")
        for c, t in zip(("q", "size", "detail", "codec", "note"), heads):
            self.tree.heading(c, text=t)

    # ------------------------------------------------------------ thread -> UI
    def ui(self, fn, *args):
        self.ui_queue.put((fn, args))

    def _drain_queue(self):
        try:
            while True:
                fn, args = self.ui_queue.get_nowait()
                fn(*args)
        except queue.Empty:
            pass
        self.after(50, self._drain_queue)

    def set_busy(self, busy, can_cancel=False):
        self.busy = busy
        self.btn_fetch.config(state="disabled" if busy else "normal")
        ready = "normal" if (self.info and not busy) else "disabled"
        self.btn_dl.config(state=ready)
        self.btn_preview.config(state=ready)
        self.btn_cancel.config(state="normal" if (busy and can_cancel) else "disabled")
        self.config(cursor="watch" if busy and not can_cancel else "")

    # ------------------------------------------------------------ small actions
    def paste(self):
        try:
            self.url_var.set(self.clipboard_get().strip())
        except tk.TclError:
            pass

    def choose_dir(self):
        d = filedialog.askdirectory(initialdir=self.dir_var.get() or DEFAULT_DIR)
        if d:
            self.dir_var.set(d)

    def open_dir(self):
        d = self.dir_var.get()
        os.makedirs(d, exist_ok=True)
        open_file(d)

    def on_cookie(self):
        if self.cookie_var.get().startswith("File"):
            p = filedialog.askopenfilename(title="Chọn file cookies.txt (định dạng Netscape)",
                                           filetypes=[("cookies", "*.txt"), ("Tất cả", "*.*")])
            if p:
                self.cookie_file = p
                self.cookie_var.set("File: " + os.path.basename(p))
            else:
                self.cookie_var.set(COOKIE_SOURCES[0])

    def on_kind(self):
        self.opt_video.pack_forget()
        self.opt_audio.pack_forget()
        frame = self.opt_video if self.kind_var.get() == "video" else self.opt_audio
        frame.pack(fill="x", padx=8, pady=3, before=self.opt_anchor)
        self._set_headings()
        self.refresh_table()

    def on_audio_format(self):
        codec = AUDIO_FORMATS[self.afmt_var.get()]
        self.cb_q.config(state="disabled" if codec in ("wav", "best") else "readonly")
        self.chk_embed.config(state="disabled" if codec == "wav" else "normal")
        self.update_estimate()

    def cancel(self):
        self.cancel_flag.set()
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.kill()
            except Exception:
                pass
        self.status_var.set("Đang huỷ...")

    def on_close(self):
        if self.busy and not messagebox.askyesno(APP_TITLE, "Đang tải dở. Thoát luôn?"):
            return
        self.cancel()
        shutil.rmtree(PREVIEW_DIR, ignore_errors=True)   # xoá file xem trước
        self.destroy()

    def base_opts(self):
        opts = {
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "windowsfilenames": True,
            "noprogress": True,
        }
        if self.ffmpeg:
            opts["ffmpeg_location"] = self.ffmpeg
        if self.deno:
            opts["js_runtimes"] = {"deno": {"path": self.deno}}
        c = self.cookie_var.get()
        if c.startswith("File") and self.cookie_file:
            opts["cookiefile"] = self.cookie_file
        elif c in ("Firefox", "Edge", "Chrome", "Brave"):
            opts["cookiesfrombrowser"] = (c.lower(),)
        return opts

    # ------------------------------------------------------------ fetch info
    def fetch_info(self):
        url = self.url_var.get().strip()
        if not url:
            messagebox.showwarning(APP_TITLE, "Bạn chưa nhập link YouTube.")
            return
        self.set_busy(True)
        self.status_var.set("Đang lấy thông tin video...")
        self.progress.config(mode="indeterminate")
        self.progress.start(12)
        threading.Thread(target=self._fetch_worker, args=(url,), daemon=True).start()

    def _fetch_worker(self, url):
        try:
            note = ""
            opts = self.base_opts()
            opts["extract_flat"] = "in_playlist"
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
                if info.get("_type") == "playlist":
                    entries = [e for e in (info.get("entries") or []) if e]
                    if not entries:
                        raise RuntimeError("Playlist trống hoặc không đọc được.")
                    first = entries[0].get("url") or entries[0].get("webpage_url")
                    note = f"Link là playlist ({len(entries)} video) – đang lấy video đầu tiên."
                    info = ydl.extract_info(first, download=False)
                if info.get("is_live"):
                    raise RuntimeError("Video đang livestream – tool chưa hỗ trợ tải trực tiếp.")
                thumb = None
                turl = info.get("thumbnail")
                if turl and Image:
                    try:
                        thumb = ydl.urlopen(turl).read()
                    except Exception:
                        thumb = None
            self.ui(self._on_info, info, thumb, note)
        except Exception as e:
            self.ui(self._on_error, "Không lấy được thông tin video", e)

    def _on_info(self, info, thumb_bytes, note):
        self.progress.stop()
        self.progress.config(mode="determinate", value=0)
        self.info = info
        self._build_rows(info)

        self.title_lbl.config(text=(info.get("title") or "")[:200])
        d = info.get("upload_date") or ""
        meta = [
            f"Kênh: {info.get('channel') or info.get('uploader') or '?'}",
            f"Thời lượng: {human_time(info.get('duration'))}",
            f"Lượt xem: {info['view_count']:,}" if isinstance(info.get("view_count"), int) else "",
            f"Ngày đăng: {d[6:8]}/{d[4:6]}/{d[:4]}" if len(d) == 8 else "",
            f"{len(self.video_rows)} bản video • {len(self.audio_rows)} bản âm thanh",
        ]
        self.meta_lbl.config(text="\n".join(m for m in meta if m))

        if thumb_bytes and Image:
            try:
                img = Image.open(io.BytesIO(thumb_bytes)).convert("RGB")
                img.thumbnail((320, 240))
                self.thumb_img = ImageTk.PhotoImage(img)
                self.thumb_lbl.config(image=self.thumb_img, text="", width=img.width,
                                      height=img.height)
            except Exception:
                self.thumb_lbl.config(image="", text="(không tải được ảnh bìa)")
        else:
            self.thumb_lbl.config(image="", text="(không có ảnh bìa)")

        self.set_busy(False)
        self.refresh_table()
        if note:
            self.status_var.set(note)

    def _build_rows(self, info):
        duration = info.get("duration")
        fmts = info.get("formats") or []      # yt-dlp đã sắp xếp: tệ -> tốt

        def ok_proto(f):
            return (f.get("protocol") or "https").startswith("http") and f.get("ext") != "mhtml"

        audios = [f for f in fmts if ok_proto(f) and f.get("vcodec") == "none"
                  and f.get("acodec") not in (None, "none")]
        clean = [a for a in audios if not is_drc(a)] or audios
        m4a = [a for a in clean if a.get("ext") == "m4a"]
        best_audio = (m4a or clean or [None])[-1]

        # --- video rows
        best = {}
        for f in fmts:
            if not ok_proto(f) or f.get("vcodec") in (None, "none") or not f.get("height"):
                continue
            progressive = f.get("acodec") not in (None, "none")
            fam = codec_family(f)
            fps = int(round(f.get("fps") or 0))
            hdr = (f.get("dynamic_range") or "SDR") != "SDR"
            if progressive:
                fid, size, aud = f["format_id"], fmt_size(f, duration), None
            else:
                if not best_audio:
                    continue
                fid = f"{f['format_id']}+{best_audio['format_id']}"
                size = fmt_size(f, duration) + fmt_size(best_audio, duration)
                aud = best_audio
            key = (f["height"], fps, fam, hdr)
            row = dict(format=fid, v=f, a=aud, height=f["height"], width=f.get("width"),
                       fps=fps, family=fam, hdr=hdr, size=size, progressive=progressive)
            old = best.get(key)
            # cùng loại: ưu tiên bản tách (DASH, nét hơn) và bitrate cao hơn
            if not old or (old["progressive"] and not progressive) or \
                    (old["progressive"] == progressive and (f.get("tbr") or 0) >= (old["v"].get("tbr") or 0)):
                best[key] = row
        order = {"H.264": 0, "VP9": 1, "AV1": 2}
        self.video_rows = sorted(best.values(),
                                 key=lambda r: (-r["height"], -r["fps"], r["hdr"],
                                                order.get(r["family"], 9)))

        # --- audio rows
        arows = []
        for a in audios:
            arows.append(dict(format=a["format_id"], a=a, abr=a.get("abr") or a.get("tbr") or 0,
                              size=fmt_size(a, duration), codec=audio_codec_label(a)))
        arows.sort(key=lambda r: (is_drc(r["a"]), -(r["abr"] or 0)))
        self.audio_rows = arows

    def refresh_table(self):
        self.tree.delete(*self.tree.get_children())
        if not self.info:
            self.rows = []
            return
        if self.kind_var.get() == "video":
            rows = self.video_rows
            if self.h264_only_var.get():
                h = [r for r in rows if r["family"] == "H.264"]
                rows = h or rows
            self.chk_convert.config(state="disabled" if self.h264_only_var.get() or not self.ffmpeg
                                    else "normal")
            if not self.ffmpeg:          # không ghép được -> chỉ bản có sẵn tiếng
                rows = [r for r in rows if r["progressive"]] or rows
            self.rows = rows
            for i, r in enumerate(rows):
                q = f"{r['height']}p" + (" HDR" if r["hdr"] else "")
                note = []
                if r["width"] and r["height"]:
                    note.append(f"{r['width']}x{r['height']}")
                if r["family"] == "AV1":
                    note.append("Win 11 cần 'AV1 Video Extension'")
                if r["progressive"]:
                    note.append("có sẵn tiếng")
                size = human_size(r["size"])
                self.tree.insert("", "end", iid=str(i), values=(
                    q, size, r["fps"] or "?",
                    r["family"] + (" ⚠" if r["family"] == "AV1" else ""), " • ".join(note)))
        else:
            self.rows = self.audio_rows
            for i, r in enumerate(self.rows):
                a = r["a"]
                note = a.get("format_note") or ""
                if a.get("language"):
                    note = f"[{a['language']}] {note}"
                self.tree.insert("", "end", iid=str(i), values=(
                    f"{int(r['abr'])} kbps" if r["abr"] else "?",
                    human_size(r["size"]),
                    f"{a['asr'] // 1000} kHz" if a.get("asr") else "?",
                    r["codec"], note))
        if self.rows:
            self.tree.selection_set("0")
            self.tree.focus("0")
        self.update_estimate()

    # ------------------------------------------------------------ choose
    def chosen_row(self, quiet=False):
        if not self.rows:
            return None
        if self.pick_var.get() == "maxsize":
            try:
                limit = float(self.maxsize_var.get()) * 1024 * 1024
            except ValueError:
                if not quiet:
                    messagebox.showwarning(APP_TITLE, "Dung lượng tối đa không hợp lệ.")
                return None
            ok = [r for r in self.rows if r["size"] and self.output_size(r) <= limit]
            if ok:
                if self.kind_var.get() == "video":
                    return max(ok, key=lambda r: (r["height"], r["fps"], r["size"]))
                return max(ok, key=lambda r: (r["abr"], r["size"]))
            if quiet:
                return None
            smallest = min(self.rows, key=lambda r: self.output_size(r) or float("inf"))
            if messagebox.askyesno(APP_TITLE, f"Không có bản nào ≤ {self.maxsize_var.get()} MB.\n"
                                              f"Tải bản nhỏ nhất (~{human_size(self.output_size(smallest))})?"):
                return smallest
            return None
        sel = self.tree.selection()
        if not sel:
            if not quiet:
                messagebox.showinfo(APP_TITLE, "Hãy chọn một dòng trong bảng.")
            return None
        return self.rows[int(sel[0])]

    def output_size(self, row):
        """Dung lượng file cuối (âm thanh chuyển đổi thì tính theo bitrate đích)."""
        if self.kind_var.get() == "audio" and self.info:
            codec = AUDIO_FORMATS[self.afmt_var.get()]
            dur = self.info.get("duration") or 0
            if codec == "wav":
                return dur * (row["a"].get("asr") or 48000) * 2 * 2
            if codec in ("mp3", "m4a", "opus") and not (
                    (codec == "m4a" and row["codec"] == "AAC") or (codec == "opus" and row["codec"] == "Opus")):
                return int(self.aq_var.get()) * 1000 / 8 * dur
        return row["size"]

    def update_estimate(self):
        if self.busy or not self.info or not self.rows:
            return
        r = self.chosen_row(quiet=True)
        if not r:
            if self.pick_var.get() == "maxsize":
                self.status_var.set(f"Không có bản nào ≤ {self.maxsize_var.get()} MB.")
            return
        if self.kind_var.get() == "video":
            desc = f"{r['height']}p {r['family']}"
        else:
            desc = "âm thanh " + ("gốc " + r["codec"] if AUDIO_FORMATS[self.afmt_var.get()] == "best"
                                  else self.afmt_var.get().split(" ")[0])
        self.status_var.set(f"Sẽ tải: {desc} • khoảng {human_size(self.output_size(r))}. "
                            "Bấm 'Tải về' hoặc nhấp đúp vào dòng.")

    # ------------------------------------------------------------ download
    def download(self):
        if self.busy or not self.info:
            return
        row = self.chosen_row()
        if not row:
            return
        outdir = self.dir_var.get().strip() or DEFAULT_DIR
        os.makedirs(outdir, exist_ok=True)
        opts = self.base_opts()
        if self.kind_var.get() == "video":
            if "+" in row["format"] and not self.ffmpeg:
                messagebox.showerror(APP_TITLE, "Cần ffmpeg để ghép hình + tiếng.")
                return
            opts["format"] = row["format"]
            opts["merge_output_format"] = "mp4"
            tag = f"{row['height']}p" + ("" if row["family"] == "H.264" else f" {row['family']}") + \
                (" HDR" if row["hdr"] else "")
            opts["outtmpl"] = os.path.join(outdir, f"%(title).90s [%(id)s] {tag}.%(ext)s")
            move_to = None
            convert = row["family"] != "H.264" and self.convert_var.get() and \
                not self.h264_only_var.get() and bool(self.ffmpeg)
            label = f"{row['height']}p"
        else:
            codec = AUDIO_FORMATS[self.afmt_var.get()]
            if not self.ffmpeg and codec != "best":
                messagebox.showerror(APP_TITLE, "Cần ffmpeg để chuyển định dạng âm thanh.")
                return
            opts["format"] = row["format"]
            # tải + chuyển đổi trong thư mục tạm riêng, xong mới chuyển sang outdir
            # (tránh file nguồn .m4a/.opus đè lên file đã có cùng tên)
            work = tempfile.mkdtemp(prefix="ytdl_audio_")
            opts["outtmpl"] = os.path.join(work, "%(title).90s [%(id)s].%(ext)s")
            move_to = outdir
            pps = []
            if self.ffmpeg:
                pps.append({"key": "FFmpegExtractAudio", "preferredcodec": codec,
                            "preferredquality": self.aq_var.get(), "nopostoverwrites": False})
                if self.embed_var.get() and codec != "wav":
                    opts["writethumbnail"] = True
                    pps += [
                        {"key": "FFmpegThumbnailsConvertor", "format": "jpg", "when": "before_dl"},
                        {"key": "FFmpegMetadata", "add_metadata": True, "add_chapters": False},
                        {"key": "EmbedThumbnail", "already_have_thumbnail": False},
                    ]
            opts["postprocessors"] = pps
            convert = False
            label = "âm thanh"
        self._start(opts, row, convert, label, open_after=False, move_to=move_to)

    def preview(self):
        if self.busy or not self.info:
            return
        os.makedirs(PREVIEW_DIR, exist_ok=True)
        opts = self.base_opts()
        opts.update({
            "format": "18/best[height<=360][vcodec^=avc1]/"
                      "bv*[height<=360][vcodec^=avc1]+ba[ext=m4a]/worst",
            "merge_output_format": "mp4",
            "outtmpl": os.path.join(PREVIEW_DIR, "%(id)s_preview.%(ext)s"),
            "download_ranges": download_range_func(None, [(0, PREVIEW_SECONDS)]),
            "overwrites": False,
        })
        self._start(opts, None, False, "bản xem trước", open_after=True)

    def _start(self, opts, row, convert, label, open_after, move_to=None):
        self.cancel_flag.clear()
        self.set_busy(True, can_cancel=True)
        self.progress.config(mode="determinate", value=0)
        self.status_var.set(f"Đang tải {label}...")
        url = self.info.get("webpage_url") or self.url_var.get().strip()
        threading.Thread(target=self._dl_worker, args=(url, opts, row, convert, open_after, move_to),
                         daemon=True).start()

    def _dl_worker(self, url, opts, row, convert, open_after, move_to=None):
        parts = row["format"].split("+") if row else []

        def hook(d):
            if self.cancel_flag.is_set():
                raise Cancelled()
            if d["status"] != "downloading":
                return
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            done = d.get("downloaded_bytes") or 0
            pct = done / total * 100 if total else 0
            fid = (d.get("info_dict") or {}).get("format_id")
            part = ""
            if len(parts) == 2:
                part = " hình (1/2)" if fid == parts[0] else " tiếng (2/2)"
            txt = f"Đang tải{part}: {human_size(done)}" + (f" / {human_size(total)}" if total else "")
            if d.get("speed"):
                txt += f"  •  {human_size(d['speed'])}/s"
            if d.get("eta"):
                txt += f"  •  còn {human_time(d['eta'])}"
            self.ui(self._on_progress, pct, txt)

        pp_names = {
            "Merger": "Đang ghép hình + tiếng...",
            "ExtractAudio": "Đang chuyển định dạng âm thanh...",
            "EmbedThumbnail": "Đang gắn ảnh bìa...",
            "Metadata": "Đang ghi thông tin bài...",
        }

        def pp_hook(d):
            if self.cancel_flag.is_set():
                raise Cancelled()
            if d["status"] == "started":
                name = d.get("postprocessor") or ""
                for k, v in pp_names.items():
                    if k in name:
                        self.ui(self._on_progress, 100, v)

        opts["progress_hooks"] = [hook]
        opts["postprocessor_hooks"] = [pp_hook]
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
                path = None
                if info.get("requested_downloads"):
                    path = info["requested_downloads"][-1].get("filepath")
                path = path or info.get("filepath") or ydl.prepare_filename(info)
            if convert:
                path = self._convert_to_h264(path, info.get("duration"))
            if move_to:
                path = self._move_unique(path, move_to)
            self.ui(self._on_done, path, open_after)
        except Exception as e:
            if move_to:
                shutil.rmtree(os.path.dirname(opts["outtmpl"]), ignore_errors=True)
            if self.cancel_flag.is_set() or isinstance(e, Cancelled) or "Cancelled" in repr(e):
                self.ui(self._on_cancelled)
            else:
                self.ui(self._on_error, "Tải thất bại", e)

    def _move_unique(self, src, outdir):
        base, ext = os.path.splitext(os.path.basename(src))
        dst, n = os.path.join(outdir, base + ext), 2
        while os.path.exists(dst):
            dst = os.path.join(outdir, f"{base} ({n}){ext}")
            n += 1
        shutil.move(src, dst)
        shutil.rmtree(os.path.dirname(src), ignore_errors=True)
        return dst

    def _convert_to_h264(self, src, duration):
        enc = pick_h264_encoder(self.ffmpeg)
        for attempt in ([enc, "libx264"] if enc != "libx264" else ["libx264"]):
            dst = os.path.splitext(src)[0] + "_h264.mp4"
            cmd = [self.ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", src,
                   "-map", "0:v:0", "-map", "0:a?", "-c:v", attempt, *ENCODER_ARGS[attempt],
                   "-c:a", "copy", "-movflags", "+faststart", "-progress", "pipe:1", "-nostats", dst]
            hw = "" if attempt == "libx264" else f" (GPU: {attempt})"
            self.ui(self._on_progress, 0, f"Đang chuyển sang H.264{hw}...")
            self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                         text=True, creationflags=NO_WINDOW)
            for line in self.proc.stdout:
                if self.cancel_flag.is_set():
                    self.proc.kill()
                    raise Cancelled()
                if line.startswith("out_time_us=") and duration:
                    try:
                        pct = min(int(line.split("=")[1]) / 1e6 / duration * 100, 100)
                    except ValueError:
                        continue
                    self.ui(self._on_progress, pct, f"Đang chuyển sang H.264{hw}... {pct:.0f}%")
            self.proc.wait()
            err = self.proc.stderr.read()
            code, self.proc = self.proc.returncode, None
            if self.cancel_flag.is_set():
                raise Cancelled()
            if code == 0 and os.path.exists(dst):
                try:
                    os.remove(src)
                except OSError:
                    pass
                return dst
        raise RuntimeError(f"ffmpeg lỗi khi chuyển sang H.264:\n{err[-400:]}")

    # ------------------------------------------------------------ callbacks
    def _on_progress(self, pct, txt):
        self.progress.config(value=pct)
        self.status_var.set(txt)

    def _on_done(self, path, open_after):
        self.progress.config(value=100)
        self.set_busy(False)
        if open_after:
            self.status_var.set("Đang mở bản xem trước...")
            try:
                open_file(path)
            except Exception as e:
                messagebox.showerror(APP_TITLE, f"Không mở được trình phát:\n{e}")
            return
        size = human_size(os.path.getsize(path)) if path and os.path.exists(path) else "?"
        self.status_var.set(f"Xong! {os.path.basename(path or '')} ({size})")
        if messagebox.askyesno(APP_TITLE, f"Đã tải xong ({size}).\nMở file ngay?"):
            open_file(path)

    def _on_cancelled(self):
        self.progress.config(value=0)
        self.set_busy(False)
        self.status_var.set("Đã huỷ.")

    def _on_error(self, title, err):
        self.progress.stop()
        self.progress.config(mode="determinate", value=0)
        self.set_busy(False)
        msg = str(err).replace("\x1b[0;31mERROR:\x1b[0m ", "")
        low = msg.lower()
        hint = "Chạy 'Cap nhat yt-dlp.bat' (bản portable) hoặc 'pip install -U yt-dlp' rồi thử lại."
        if any(k in low for k in ("sign in", "not a bot", "age-restricted", "confirm your age",
                                  "inappropriate", "members-only", "join this channel")):
            hint = ("YouTube yêu cầu đăng nhập. Chọn 'Cookies: Firefox' (đã đăng nhập YouTube trên "
                    "Firefox) rồi thử lại. Chrome/Edge thường phải tắt hẳn trình duyệt mới đọc được cookies.")
        elif "private" in low:
            hint = "Video ở chế độ riêng tư."
        elif "javascript" in low or "js runtime" in low or "deno" in low:
            hint = "Thiếu Deno (JS runtime). Bản portable đã có sẵn; chạy từ source thì 'pip install deno'."
        self.status_var.set(title)
        messagebox.showerror(APP_TITLE, f"{title}:\n\n{msg[:700]}\n\nGợi ý: {hint}")


def enable_dpi_awareness():
    if sys.platform.startswith("win"):
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass


if __name__ == "__main__":
    enable_dpi_awareness()
    App().mainloop()
