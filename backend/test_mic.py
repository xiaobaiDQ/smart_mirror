"""临时脚本：列出所有输入设备并测试哪个能收到音频信号"""
import sounddevice as sd
import numpy as np

print("=== 所有输入设备 ===")
devices = sd.query_devices()
hostapis = sd.query_hostapis()
for i, d in enumerate(devices):
    if d.get("max_input_channels", 0) > 0:
        api = hostapis[d["hostapi"]]["name"] if d["hostapi"] < len(hostapis) else "?"
        print(f"  [{i}] {d['name']}  (api={api}, sr={int(d['default_samplerate'])})")

print()
print("=== 逐个测试录音 0.5s (请对着麦克风说话) ===")
for i, d in enumerate(devices):
    if d.get("max_input_channels", 0) <= 0:
        continue
    sr = int(d.get("default_samplerate", 16000))
    try:
        audio = sd.rec(int(0.5 * sr), samplerate=sr, channels=1, dtype="float32", device=i)
        sd.wait()
        level = float(np.abs(audio).mean())
        peak = float(np.abs(audio).max())
        status = "HAS_SIGNAL" if peak > 0.001 else "NO_SIGNAL"
        print(f"  [{i}] {d['name']}: mean={level:.6f} peak={peak:.6f} {status}")
    except Exception as e:
        err = str(e).split("\n")[0][:80]
        print(f"  [{i}] {d['name']}: FAILED - {err}")
