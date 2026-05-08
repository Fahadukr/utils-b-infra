import io
import unittest
from unittest.mock import Mock, patch

from utils_b_infra.ai import TextGenerator


class FakeAudio:
    def __init__(self, duration_ms=1000):
        self.duration_ms = duration_ms
        self.channels = None
        self.frame_rate = None
        self.export_format = None
        self.export_bitrate = None

    def __len__(self):
        return self.duration_ms

    def set_channels(self, channels):
        self.channels = channels
        return self

    def set_frame_rate(self, frame_rate):
        self.frame_rate = frame_rate
        return self

    def export(self, out_f, format, bitrate):
        self.export_format = format
        self.export_bitrate = bitrate
        out_f.write(b"normalized mp3")


class DummyTranscriptions:
    def __init__(self):
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        return "transcript"


class DummyOpenAIClient:
    def __init__(self):
        self.audio = Mock()
        self.audio.transcriptions = DummyTranscriptions()


class TextGeneratorAudioTest(unittest.TestCase):
    def test_get_file_extension_ignores_url_query(self):
        extension = TextGenerator._get_file_extension("https://example.com/file.mp4?token=abc")

        self.assertEqual(extension, "mp4")

    @patch("utils_b_infra.ai.AudioSegment.from_file")
    @patch("utils_b_infra.ai.requests.get")
    def test_transcribe_audio_file_normalizes_common_sources_to_mp3(self, mock_get, mock_from_file):
        mock_get.return_value.status_code = 200
        mock_get.return_value.content = b"source media"

        cases = {
            "m4a": "m4a",
            "mp3": "mp3",
            "mp4": "mp4",
            "oga": "ogg",
            "ogg": "ogg",
            "wav": "wav",
            "webm": "webm",
        }
        for source_extension, expected_decoder_format in cases.items():
            with self.subTest(source_extension=source_extension):
                fake_audio = FakeAudio()
                mock_from_file.return_value = fake_audio
                openai_client = DummyOpenAIClient()

                transcript = TextGenerator(openai_client).transcribe_audio_file(
                    url=f"https://example.com/message.{source_extension}?token=abc",
                )

                self.assertEqual(transcript, "transcript")
                self.assertEqual(mock_from_file.call_args.kwargs["format"], expected_decoder_format)
                self.assertEqual(fake_audio.channels, 1)
                self.assertEqual(fake_audio.frame_rate, 16000)
                self.assertEqual(fake_audio.export_format, "mp3")
                self.assertEqual(fake_audio.export_bitrate, "64k")

                request_file = openai_client.audio.transcriptions.kwargs["file"]
                self.assertEqual(request_file.name, "audio.mp3")
                self.assertEqual(request_file.read(), b"normalized mp3")

    @patch("utils_b_infra.ai.AudioSegment.from_file")
    def test_normalize_audio_rejects_empty_audio(self, mock_from_file):
        mock_from_file.return_value = FakeAudio(duration_ms=0)

        with self.assertRaisesRegex(ValueError, "no audio samples"):
            TextGenerator._normalize_audio_for_transcription(
                audio_bytes=io.BytesIO(b"source media"),
                audio_format="mp4",
            )


if __name__ == "__main__":
    unittest.main()
