import pytest
import io
import wave
import struct
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from backend.main import app

client = TestClient(app)


def create_dummy_wav_bytes(duration_sec: float = 0.5, sample_rate: int = 16000) -> bytes:
    """Generate in-memory mono PCM WAV audio bytes."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        num_samples = int(duration_sec * sample_rate)
        # Write quiet sine wave
        samples = [int(1000 * (i % 16 - 8)) for i in range(num_samples)]
        wf.writeframes(struct.pack(f"<{len(samples)}h", *samples))
    return buf.getvalue()


def test_transcribe_empty_file():
    response = client.post(
        "/api/nexus/transcribe",
        files={"file": ("audio.wav", b"", "audio/wav")},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["text"] == ""
    assert data["wake_detected"] is False
    assert "error" in data


def test_transcribe_wake_word_hey_nexus():
    dummy_wav = create_dummy_wav_bytes()

    mock_transcription = MagicMock()
    mock_transcription.text = "Hey Nexus, what is on my schedule today?"

    with patch("backend.core.config.get_groq_api_key", return_value="gsk_mock_valid_key"):
        with patch("groq.Groq") as mock_groq_class:
            mock_groq = MagicMock()
            mock_groq.audio.transcriptions.create.return_value = mock_transcription
            mock_groq_class.return_value = mock_groq

            response = client.post(
                "/api/nexus/transcribe",
                files={"file": ("audio.wav", dummy_wav, "audio/wav")},
            )
            assert response.status_code == 200
            data = response.json()
            assert data["text"] == "Hey Nexus, what is on my schedule today?"
            assert data["wake_detected"] is True
            assert data["command"] == "what is on my schedule today?"


def test_transcribe_wake_word_standalone():
    dummy_wav = create_dummy_wav_bytes()

    mock_transcription = MagicMock()
    mock_transcription.text = "Hey Nexus"

    with patch("backend.core.config.get_groq_api_key", return_value="gsk_mock_valid_key"):
        with patch("groq.Groq") as mock_groq_class:
            mock_groq = MagicMock()
            mock_groq.audio.transcriptions.create.return_value = mock_transcription
            mock_groq_class.return_value = mock_groq

            response = client.post(
                "/api/nexus/transcribe",
                files={"file": ("audio.wav", dummy_wav, "audio/wav")},
            )
            assert response.status_code == 200
            data = response.json()
            assert data["text"] == "Hey Nexus"
            assert data["wake_detected"] is True
            assert data["command"] == ""


def test_transcribe_non_wake_direct_command():
    dummy_wav = create_dummy_wav_bytes()

    mock_transcription = MagicMock()
    mock_transcription.text = "open my documents folder"

    with patch("backend.core.config.get_groq_api_key", return_value="gsk_mock_valid_key"):
        with patch("groq.Groq") as mock_groq_class:
            mock_groq = MagicMock()
            mock_groq.audio.transcriptions.create.return_value = mock_transcription
            mock_groq_class.return_value = mock_groq

            response = client.post(
                "/api/nexus/transcribe",
                files={"file": ("audio.wav", dummy_wav, "audio/wav")},
            )
            assert response.status_code == 200
            data = response.json()
            assert data["text"] == "open my documents folder"
            assert data["wake_detected"] is False
            assert data["command"] == "open my documents folder"
