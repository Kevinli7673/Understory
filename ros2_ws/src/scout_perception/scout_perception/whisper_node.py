"""whisper_node: push-to-talk clip on /voice/audio -> text on /voice/text (String).

    ros2 run scout_perception whisper_node --ros-args -p model:=openai/whisper-base.en

/voice/audio is std_msgs/UInt8MultiArray whose data is a complete WAV file (the Quest sends 16 kHz,
mono, 16-bit PCM, at most 8 s). /voice/text is the transcript in lower case without punctuation,
e.g. "start survey". The mission manager picks the command out of it by keyword.

Clips that are too short or too quiet are dropped without running the model: Whisper invents words
for silence, and an invented "go" would start a survey.

The `prompt` parameter is text Whisper is told came just before the clip. Listing the commands there
makes a short clip more likely to come out as one of them (on the Quest "start survey" was heard as
"sorry, survey" without it). Set it to an empty string to turn it off.

The prompt has a cost: with it, a clip of background noise came out as "start survey". Whisper is
unsure when it does that, so a transcript whose score is under `min_logprob` is dropped too.
"""
import time

import rclpy
from rclpy.node import Node
from std_msgs.msg import String, UInt8MultiArray

from scout_perception.voice import WHISPER_RATE, clean_text, decode_wav, resample, rms


class Whisper:
    """Whisper through transformers, which the AI image already has. Loaded once."""

    def __init__(self, model_name, prompt=''):
        import torch
        from transformers import WhisperForConditionalGeneration, WhisperProcessor
        self.torch = torch
        self.device = 'cuda' if torch.cuda.is_available() else 'cpu'
        self.processor = WhisperProcessor.from_pretrained(model_name)
        self.model = WhisperForConditionalGeneration.from_pretrained(model_name).to(self.device).eval()
        self.prompt, self.prompt_ids = prompt, None
        if prompt:
            self.prompt_ids = self.processor.get_prompt_ids(prompt, return_tensors='pt').to(self.device)

    def transcribe(self, samples):
        """Returns (text, score). score is the mean log-probability of the words Whisper chose:
        about -0.2 to -0.7 for clear speech, under -1.2 when it is guessing at noise."""
        features = self.processor(samples, sampling_rate=WHISPER_RATE, return_tensors='pt').input_features
        with self.torch.no_grad():
            out = self.model.generate(features.to(self.device), prompt_ids=self.prompt_ids,
                                      output_scores=True, return_dict_in_generate=True)
        # the last len(scores) tokens are the new ones; anything before them is the prompt
        tokens = out.sequences[0, -len(out.scores):]
        logprobs = [self.torch.log_softmax(s[0].float(), -1)[t].item() for s, t in zip(out.scores, tokens)]
        text = self.processor.decode(tokens, skip_special_tokens=True)
        return text, sum(logprobs) / max(len(logprobs), 1)


class WhisperNode(Node):
    def __init__(self):
        super().__init__('whisper_node')
        model = self.declare_parameter('model', 'openai/whisper-base.en').value
        self.min_seconds = self.declare_parameter('min_seconds', 0.3).value
        self.max_seconds = self.declare_parameter('max_seconds', 15.0).value
        # RMS of the clip on a -1..1 scale; below this it is treated as silence
        self.min_rms = self.declare_parameter('min_rms', 0.005).value
        prompt = self.declare_parameter(
            'prompt', 'Robot commands: start survey, stop, return home, come back, manual, capture, resume.').value
        # mean log-probability under which a transcript is treated as a guess (test clips: speech
        # -0.18 to -0.67, noise and silence -1.27 and -1.69)
        self.min_logprob = self.declare_parameter('min_logprob', -1.0).value
        self.whisper = Whisper(model, prompt)

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
        text, score = self.whisper.transcribe(samples)
        text = clean_text(text)
        took = time.monotonic() - start
        if score < self.min_logprob:
            self.get_logger().info(f'{seconds:.1f} s clip -> "{text}" dropped: score {score:.2f} in {took:.1f} s')
            return
        self.get_logger().info(f'{seconds:.1f} s clip -> "{text}" (score {score:.2f}) in {took:.1f} s')
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
