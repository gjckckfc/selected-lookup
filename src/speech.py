# -*- coding: utf-8 -*-
"""本地朗读: 用 Windows 自带的语音合成, 不联网、不要密钥。

做法:
  - 启动后在后台查一遍系统装了哪些语音, 挑一个英语的、一个中文的
  - 常驻一个 PowerShell 进程(System.Speech)当合成器: stdin 发任务, stdout 收结果
  - 合成结果写进 data/voice_cache/, 同一个词/句只合成一次, 之后零延迟
  - 播放走系统 MCI 接口(open/play/stop/close): 收到新请求先显式停掉上一句,
    所以"正在念原文时点了单词"会立刻断掉原文改念单词

为什么用 PowerShell 而不是纯 ctypes: 系统语音是一套 COM 接口, 纯 ctypes
要手写两百行指针操作, 出错就是整个进程崩溃。让系统自带的 PowerShell 承载,
零第三方依赖, 真出问题也只挂在子进程里。
"""
from __future__ import annotations

import hashlib
import subprocess
import threading
import time
import ctypes
from pathlib import Path

winmm = ctypes.WinDLL("winmm", use_last_error=True)
winmm.mciSendStringW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p,
                                 ctypes.c_uint, ctypes.c_void_p]

PLAY_ALIAS = "lookupvoice"


def _mci(command, want_value=False):
    """调一次 MCI。返回错误码, want_value=True 时还返回输出文本。"""
    buf = ctypes.create_unicode_buffer(512)
    err = winmm.mciSendStringW(command, buf, 512, None)
    if want_value:
        return err, buf.value
    return err

# 别让 PowerShell 弹黑框
CREATE_NO_WINDOW = 0x08000000

# 合成进程是按需拉起的: 闲置这么久就关掉, 把内存还回去
# (进程约 75 MB; 用户明确说可以接受, 所以留足 5 分钟, 避免频繁重启的等待)
IDLE_SECONDS = 300
REAP_INTERVAL = 15

LIST_VOICES = (
    "[Console]::OutputEncoding=[Text.Encoding]::UTF8;"
    "Add-Type -AssemblyName System.Speech;"
    "(New-Object System.Speech.Synthesis.SpeechSynthesizer).GetInstalledVoices()"
    "|ForEach-Object{$_.VoiceInfo.Name+'|'+$_.VoiceInfo.Culture.Name+'|'+$_.Enabled}"
)

WORKER = r'''
[Console]::InputEncoding = [Text.Encoding]::UTF8
[Console]::OutputEncoding = [Text.Encoding]::UTF8
Add-Type -AssemblyName System.Speech
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
$synth.SetOutputToNull()
while (($line = [Console]::In.ReadLine()) -ne $null) {
  $parts = $line.Split("`t", 3)
  if ($parts.Length -lt 3) {
    [Console]::Out.WriteLine("ERR bad request")
    [Console]::Out.Flush()
    continue
  }
  try {
    $synth.SelectVoice($parts[0])
    $synth.SetOutputToWaveFile($parts[1])
    $synth.Speak($parts[2])
    $synth.SetOutputToNull()
    [Console]::Out.WriteLine("OK")
  } catch {
    try { $synth.SetOutputToNull() } catch { }
    [Console]::Out.WriteLine("ERR " + $_.Exception.Message)
  }
  [Console]::Out.Flush()
}
'''


# 自动挑声音时的偏好顺序(越靠前越优先), 挑不到就按名字排
EN_PREFERRED = ("ava", "emma", "aria", "jenny", "michelle", "ana",
                "guy", "andrew", "brian", "christopher", "eric",
                "roger", "steffan")
ZH_PREFERRED = ("xiaoxiao", "xiaoyi", "yunxi", "yunjian",
                "yunxia", "yunyang", "xiaobei", "xiaoni")


def _voice_rank(name, culture, lang):
    """给一个语音打分, 越小越优先。"""
    low_name = name.lower()
    low_culture = (culture or "").lower()
    exact = 0 if low_culture == ("en-us" if lang == "en" else "zh-cn") else 1
    # 老一代 SAPI 桌面语音(比如 Zira)"念稿感"重, 排最后
    legacy = 1 if "desktop" in low_name else 0
    # 神经网络语音(名字里带 Online/Natural)优先
    neural = 0 if ("online" in low_name or "natural" in low_name) else 1
    order = EN_PREFERRED if lang == "en" else ZH_PREFERRED
    pref = len(order) + 1
    for index, key in enumerate(order):
        if key in low_name:
            pref = index
            break
    return (legacy, neural, exact, pref, low_name)


def _pick_voice(voices, lang, prefer=""):
    """从语音列表里挑一个。prefer 是用户指定的语音名, 空则自动挑。"""
    usable = [v for v in voices if v[2] and (v[1] or "").lower().startswith(lang)]
    if prefer:
        for name, _culture, enabled in voices:
            if enabled and name == prefer:
                return name
    if not usable:
        return ""
    return min(usable, key=lambda v: _voice_rank(v[0], v[1], lang))[0]


def _wav_duration_ms(path):
    """读 wav 头算时长, 用来决定朗读高亮什么时候收起。"""
    try:
        with open(path, "rb") as handle:
            head = handle.read(4096)
    except OSError:
        return 0
    if len(head) < 12 or head[:4] != b"RIFF":
        return 0
    byte_rate = 0
    data_size = 0
    pos = 12
    while pos + 8 <= len(head):
        chunk = head[pos:pos + 4]
        size = int.from_bytes(head[pos + 4:pos + 8], "little")
        if chunk == b"fmt " and pos + 16 <= len(head):
            byte_rate = int.from_bytes(head[pos + 16:pos + 20], "little")
        elif chunk == b"data":
            data_size = size
            break
        pos += 8 + size + (size & 1)
    if not byte_rate or not data_size:
        return 0
    return int(data_size * 1000 / byte_rate)


class Speech:
    def __init__(self, cache_dir=None, logger=None, enabled=True):
        self.log = logger or (lambda message: None)
        self.enabled = bool(enabled)
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.available = False
        self.voice_en = ""
        self.voice_zh = ""
        self.offline_voices = {}         # 断网时回落的本地语音 {en: 名称, zh: 名称}
        self.voices = []                 # [(名称, 语言, 是否可用)]
        self.preferred = ""              # 用户指定的英语语音, 空 = 自动挑
        self._proc = None
        self._lock = threading.Lock()
        self._play_lock = threading.Lock()
        self._playing = False
        self._inflight_lock = threading.Lock()
        self._inflight = set()           # 正在预热的文本, 避免重复合成
        self._started = False
        self._closed = False
        self._last_used = 0.0
        self._generation = 0
        self.preparing = False

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    def start(self):
        """后台准备: 查语音、拉起合成进程。不阻塞调用方。"""
        if self._started or not self.enabled:
            return
        self._started = True
        self.preparing = True
        threading.Thread(target=self._prepare, name="speech", daemon=True).start()

    def _prepare(self):
        try:
            self._prepare_worker()
        finally:
            self.preparing = False

    def _prepare_worker(self):
        voices = self._list_voices()
        if not voices:
            self.log("朗读不可用: 读不到系统语音列表")
            return
        self.voices = voices
        self.voice_en = _pick_voice(voices, "en", self.preferred)
        self.voice_zh = _pick_voice(voices, "zh")
        local = [v for v in voices if "online" not in v[0].lower()]
        self.offline_voices = {"en": _pick_voice(local, "en"),
                               "zh": _pick_voice(local, "zh")}
        if not self.voice_en:
            self.log("朗读不可用: 系统里没有英语语音 (可用语音 %d 个)" % len(voices))
            return
        self.available = True
        idle = ("%d 分钟" % (IDLE_SECONDS // 60)) if IDLE_SECONDS >= 60 \
            else ("%d 秒" % IDLE_SECONDS)
        self.log("朗读就绪: 英语[%s] 中文[%s] (合成进程按需启动, 闲 %s后自动关)" % (
            self.voice_en, self.voice_zh or "无", idle))
        threading.Thread(target=self._reap_loop, name="speech-reap",
                         daemon=True).start()

    def _ensure_worker(self):
        """按需拉起合成进程, 已经活着就直接用。"""
        proc = self._proc
        if proc is not None and proc.poll() is None:
            return proc
        try:
            self._proc = subprocess.Popen(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                 "-WindowStyle", "Hidden", "-Command", WORKER],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW)
        except OSError as exc:
            self.log("朗读进程启动失败: %s" % exc)
            return None
        return self._proc

    def _reap_loop(self):
        """闲下来就把合成进程关掉, 别让它白占 70 多 MB 内存。"""
        while not self._closed:
            time.sleep(REAP_INTERVAL)
            with self._lock:
                proc = self._proc
                if proc is None or proc.poll() is not None:
                    continue
                if time.monotonic() - self._last_used < IDLE_SECONDS:
                    continue
                self._terminate(proc)

    def _terminate(self, proc):
        if self._proc is proc:
            self._proc = None
        for stream in (proc.stdin, proc.stdout):
            try:
                if stream:
                    stream.close()
            except OSError:
                pass
        try:
            proc.terminate()
        except OSError:
            pass

    def set_enabled(self, enabled):
        self.enabled = bool(enabled)
        if self.enabled:
            self.start()
        else:
            self.stop()

    def set_preferred(self, name):
        """换一个英语语音(设置面板里选的)。"""
        self.preferred = (name or "").strip()
        if self.voices:
            picked = _pick_voice(self.voices, "en", self.preferred)
            if picked and picked != self.voice_en:
                self.voice_en = picked
                self.log("朗读英语语音改为: %s" % picked)

    def english_voices(self):
        """英语语音列表, 按自动挑选的偏好排序: Ava 排第一个, 老的桌面语音排最后。"""
        pairs = [(name, culture) for name, culture, enabled in self.voices
                 if enabled and (culture or "").lower().startswith("en")]
        pairs.sort(key=lambda item: _voice_rank(item[0], item[1], "en"))
        return [name for name, _culture in pairs]

    @staticmethod
    def _list_voices():
        try:
            done = subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                 "-WindowStyle", "Hidden", "-Command", LIST_VOICES],
                capture_output=True, timeout=20, creationflags=CREATE_NO_WINDOW)
        except (OSError, subprocess.SubprocessError):
            return []
        text = done.stdout.decode("utf-8", "replace")
        voices = []
        for line in text.splitlines():
            parts = line.strip().split("|")
            if len(parts) == 3 and parts[0]:
                voices.append((parts[0], parts[1], parts[2].strip().lower() == "true"))
        return voices

    # ------------------------------------------------------------------
    # 朗读
    # ------------------------------------------------------------------

    def speak(self, text, lang="en", notify=None):
        """后台合成并播放。notify(时长毫秒) 在声音开始时回调。"""
        if not self.available or not text:
            return False
        voice = self.voice_zh if lang == "zh" else self.voice_en
        if not voice:
            return False
        self._generation += 1
        generation = self._generation
        # 用户点了新的: 立刻掐掉上一句, 不等它念完
        self._stop_playback()
        threading.Thread(target=self._speak, args=(text, voice, notify, generation),
                         daemon=True).start()
        return True

    def prewarm(self, text, lang="en"):
        """后台先把音频合成好(不播放), 等用户真去右键时就能立刻出声。"""
        if not self.available or not text:
            return False
        text = " ".join(text.split())
        voice = self.voice_zh if lang == "zh" else self.voice_en
        if not voice:
            return False
        path = self._cache_path(text, voice)
        if path is None or path.exists():
            return False
        with self._inflight_lock:
            if text in self._inflight:
                return False
            self._inflight.add(text)
        threading.Thread(target=self._prewarm_worker, args=(text, voice, path),
                         daemon=True).start()
        return True

    def _prewarm_worker(self, text, voice, path):
        try:
            self._synthesize(text, voice, path)
        finally:
            with self._inflight_lock:
                self._inflight.discard(text)

    def _speak(self, text, voice, notify, generation):
        path = self._speak_path(text, voice)
        if path is None:
            # 在线语音要联网; 断了就退回系统自带的本地语音
            lang = "zh" if voice == self.voice_zh else "en"
            fallback = self.offline_voices.get(lang, "")
            if fallback and fallback != voice:
                self.log("在线朗读失败, 回落到本地语音 %s" % fallback)
                path = self._speak_path(text, fallback)
        if path is None:
            return
        if generation != self._generation:
            return                      # 用户已经点了别的, 这条就别播了
        duration = _wav_duration_ms(path)
        self._play(path)
        if notify:
            try:
                notify(duration)
            except Exception:
                pass

    def _speak_path(self, text, voice):
        """拿到这句的音频文件: 有缓存直接用, 没有就合成。"""
        path = self._cache_path(text, voice)
        if path is None:
            return None
        if path.exists():
            return path
        return self._synthesize(text, voice, path)

    def _synthesize(self, text, voice, path):
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self.log("朗读缓存目录建不了: %s" % exc)
            return None
        payload = "%s\t%s\t%s\n" % (voice, str(path), " ".join(text.split()))
        with self._lock:
            proc = self._ensure_worker()
            if proc is None:
                return None
            try:
                proc.stdin.write(payload.encode("utf-8"))
                proc.stdin.flush()
                answer = proc.stdout.readline().decode("utf-8", "replace").strip()
            except (OSError, ValueError) as exc:
                self.log("朗读失败: %s" % exc)
                return None
            self._last_used = time.monotonic()
        if not answer.startswith("OK"):
            self.log("朗读失败: %s" % (answer or "没有回应")[:140])
            return None
        return path if path.exists() else None

    def _cache_path(self, text, voice):
        if self.cache_dir is None:
            return None
        raw = ("%s\x00%s" % (voice, " ".join(text.split()))).encode("utf-8")
        return self.cache_dir / (hashlib.sha1(raw).hexdigest()[:16] + ".wav")

    @staticmethod
    def _stop_locked():
        """掐掉正在播的那句。调用方要持有 _play_lock。"""
        _mci("stop %s" % PLAY_ALIAS)
        _mci("close %s" % PLAY_ALIAS)

    def _play(self, path):
        """播放一个 wav。要换句时先显式停掉上一句——两句同时响是没人想要的。"""
        with self._play_lock:
            self._stop_locked()
            err = _mci('open "%s" type waveaudio alias %s' % (path, PLAY_ALIAS))
            if err == 0:
                err = _mci("play %s" % PLAY_ALIAS)
                if err == 0:
                    self._playing = True
                    return
            self._playing = False
            self.log("播放失败: MCI 错误码 %d" % err)

    def _stop_playback(self):
        with self._play_lock:
            self._stop_locked()
            self._playing = False

    def stop(self):
        self._generation += 1           # 让还没合成完的请求作废
        self._stop_playback()

    def close(self):
        self._closed = True
        self.stop()
        proc, self._proc = self._proc, None
        self.available = False
        if proc is None:
            return
        self._terminate(proc)
