
import { File } from 'expo-file-system';
import { API_BASE_URL } from './auth';

export type SpeechTranscriptionResponse = {
  transcript: string;
  language: string;
  duration_seconds: number | null;
};

export async function transcribeRecording(
  audioUri: string,
  signal?: AbortSignal,
): Promise<SpeechTranscriptionResponse> {
  const formData = new FormData();

  // Expo File implements Blob and supports multipart uploads.
  const audioFile = new File(audioUri);

  formData.append('file', audioFile, 'question.m4a');

  const response = await fetch(
    `${API_BASE_URL}/api/speech/transcribe`,
    {
      method: 'POST',
      body: formData,
      signal,
    }
  );

  if (!response.ok) {
    let message = `Transcription failed (${response.status})`;

    try {
      const errorData = await response.json();

      if (typeof errorData.detail === 'string') {
        message = errorData.detail;
      }
    } catch {
      // Keep the default error message.
    }

    throw new Error(message);
  }

  return (await response.json()) as SpeechTranscriptionResponse;
}
