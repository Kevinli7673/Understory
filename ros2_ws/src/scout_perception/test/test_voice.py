import io
import math
import wave

import numpy as np
import pytest

from scout_perception.voice import clean_text, decode_wav, resample, rms


def wav_bytes(samples, rate=16000, channels=1, width=2):
    """samples: floats in -1..1, interleaved if channels > 1."""
    scale, dtype = {1: (127, np.uint8), 2: (32767, '<i2'), 4: (2147483647, '<i4')}[width]
    pcm = np.asarray(samples) * scale + (128 if width == 1 else 0)
    buf = io.BytesIO()
    with wave.open(buf, 'wb') as w:
        w.setnchannels(channels)
        w.setsampwidth(width)
        w.setframerate(rate)
        w.writeframes(pcm.astype(dtype).tobytes())
    return buf.getvalue()


def tone(seconds=0.5, rate=16000, amplitude=0.5):
    return amplitude * np.sin(2 * math.pi * 440 * np.arange(int(seconds * rate)) / rate)


def test_decode_quest_format():
    samples, rate = decode_wav(wav_bytes(tone()))
    assert rate == 16000 and samples.dtype == np.float32 and len(samples) == 8000
    assert np.allclose(samples, tone(), atol=1e-3)


def test_decode_accepts_a_list_of_ints():
    # rclpy hands UInt8MultiArray.data over as an array of ints, not bytes
    samples, _ = decode_wav(list(wav_bytes(tone())))
    assert len(samples) == 8000


def test_decode_stereo_is_averaged():
    left, right = tone(amplitude=0.6), tone(amplitude=0.2)
    samples, _ = decode_wav(wav_bytes(np.column_stack([left, right]).ravel(), channels=2))
    assert len(samples) == 8000 and np.allclose(samples, tone(amplitude=0.4), atol=1e-3)


@pytest.mark.parametrize('width', [1, 4])
def test_decode_other_sample_widths(width):
    samples, _ = decode_wav(wav_bytes(tone(), width=width))
    assert np.allclose(samples, tone(), atol=0.02)


@pytest.mark.parametrize('data', [b'', b'not a wav file at all', wav_bytes(tone())[:20]])
def test_decode_rejects_junk(data):
    with pytest.raises(ValueError):
        decode_wav(data)


def test_resample_48k_to_16k():
    out = resample(tone(rate=48000).astype(np.float32), 48000)
    assert len(out) == 8000 and np.allclose(out, tone(), atol=0.01)


def test_resample_same_rate_and_empty():
    samples = tone().astype(np.float32)
    assert resample(samples, 16000) is samples
    assert len(resample(np.zeros(0, np.float32), 48000)) == 0


def test_rms():
    assert rms(np.zeros(0)) == 0.0 and rms(np.zeros(100)) == 0.0
    assert math.isclose(rms(tone(amplitude=0.5)), 0.5 / math.sqrt(2), rel_tol=1e-3)


def test_clean_text():
    assert clean_text(' Start survey.') == 'start survey'
    assert clean_text("I'll drive!") == "i'll drive"
    assert clean_text('Stop,  STOP!!') == 'stop stop'
    assert clean_text(' ... ') == ''
