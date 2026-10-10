"""whisper_node: push-to-talk clip on /voice/audio -> text on /voice/text (String).

    ros2 run scout_perception whisper_node --ros-args -p model:=openai/whisper-base.en

/voice/audio is std_msgs/UInt8MultiArray whose data is a complete WAV file (the Quest sends 16 kHz,
mono, 16-bit PCM, at most 8 s). /voice/text is the transcript in lower case without punctuation,
e.g. "start survey". The mission manager picks the command out of it by keyword.

Clips that are too short or too quiet are dropped without running the model: Whisper invents words
for silence, and an invented "go" would start a survey.
"""
import time

import rclpy
from rclpy.node import Node
from std_msgs.msg import String, UInt8MultiArray

from scout_perception.voice import WHISPER_RATE, clean_text, decode_wav, resample, rms


class Whisper:
    """Whisper through transformers, which the AI image already has. Loaded once."""

    def __init__(self, model_name):
        import torch
        from transformers import WhisperForConditionalGeneration, WhisperProcessor
        self.torch = torch
        self.device = 'cuda' if torch.cuda.is_available() else 'cpu'
        self.processor = WhisperProcessor.from_pretrained(model_name)
        self.model = WhisperForConditionalGeneration.from_pretrained(model_name).to(self.device).eval()

    def transcribe(self, samples):
        features = self.processor(samples, sampling_rate=WHISPER_RATE, return_tensors='pt').input_features
        with self.torch.no_grad():
            ids = self.model.generate(features.to(self.device))
        return self.processor.batch_decode(ids, skip_special_tokens=True)[0]


class WhisperNode(Node):
    def __init__(self):
        super().__init__('whisper_node')
        model = self.declare_parameter('model', 'openai/whisper-base.en').value
        self.min_seconds = self.declare_parameter('min_seconds', 0.3).value
        self.max_seconds = self.declare_parameter('max_seconds', 15.0).value
        # RMS of the clip on a -1..1 scale; below this it is treated as silence
        self.min_rms = self.declare_parameter('min_rms', 0.005).value
        self.whisper = Whisper(model)

        self.pub = self.create_publisher(String, '/voice/text', 10)
        # depth 1: if clips arrive faster than they are transcribed, only the newest matters
        self.create_subscription(UInt8MultiArray, '/voice/audio', self.on_audio, 1)
        self.get_logger().info(f'whisper node running, model={model}, device={self.whisper.device}')

    def on_audio(self, msg):
        try:
            samples, rate = decode_wav(msg.data)
        except ValueError as e:
            self.get_logger().warn(f'bad /voice/audio clip: {e}')
            return
        samples = resample(samples, rate)[:int(self.max_seconds * WHISPER_RATE)]
        seconds, level = len(samples) / WHISPER_RATE, rms(samples)
        if seconds < self.min_seconds or level < self.min_rms:
            self.get_logger().info(f'clip ignored: {seconds:.1f} s, rms {level:.4f}')
            return
        start = time.monotonic()
        text = clean_text(self.whisper.transcribe(samples))
        self.get_logger().info(f'{seconds:.1f} s clip -> "{text}" in {time.monotonic() - start:.1f} s')
        if text:
            self.pub.publish(String(data=text))


def main():
    rclpy.init()
    try:
        rclpy.spin(WhisperNode())
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
