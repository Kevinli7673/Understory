"""Push-to-talk audio helpers. Plain Python (no ROS imports) so it can be unit-tested.

A clip is a complete WAV file (the Quest sends 16 kHz, mono, 16-bit PCM). Whisper wants float
samples in -1..1 at 16 kHz, mono.
"""
import io
import re
import wave

import numpy as np

WHISPER_RATE = 16000


def decode_wav(data):
    """WAV file bytes -> (float32 mono samples in -1..1, sample rate). Raises ValueError if unreadable."""
    try:
        with wave.open(io.BytesIO(bytes(data)), 'rb') as w:
            channels, width, rate = w.getnchannels(), w.getsampwidth(), w.getframerate()
            raw = w.readframes(w.getnframes())
    except (wave.Error, EOFError) as e:
        raise ValueError(f'not a WAV file: {e}')
    if width == 2:
        samples = np.frombuffer(raw, '<i2').astype(np.float32) / 32768.0
    elif width == 1:                                    # 8-bit WAV is unsigned
        samples = (np.frombuffer(raw, np.uint8).astype(np.float32) - 128.0) / 128.0
    elif width == 4:
        samples = np.frombuffer(raw, '<i4').astype(np.float32) / 2147483648.0
    else:
        raise ValueError(f'unsupported sample width: {width} bytes')
    if channels > 1:
        samples = samples[:len(samples) // channels * channels].reshape(-1, channels).mean(axis=1)
    return samples, rate


def resample(samples, rate, target=WHISPER_RATE):
    """Linear resampling. Good enough for speech; the Quest already sends 16 kHz."""
    if rate == target or len(samples) == 0:
        return samples
    n = int(len(samples) * target / rate)
    return np.interp(np.arange(n) * (rate / target), np.arange(len(samples)), samples).astype(np.float32)


def rms(samples):
    return float(np.sqrt(np.mean(np.square(samples)))) if len(samples) else 0.0


def clean_text(text):
    """Whisper transcript -> lower case, no punctuation, single spaces. "Start survey." -> "start survey"."""
    return ' '.join(re.sub(r"[^a-z0-9' ]+", ' ', text.lower()).split())
