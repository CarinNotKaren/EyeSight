import { randomUUID } from 'expo-crypto';
import { API_BASE_URL, getAccessToken } from './auth';

type VoiceAnswer = {
  answer_text: string;
  language_code: string;
  timings?: {
    retrieval_ms: number | null;
    gemini_ms: number | null;
  };
};

function readLatencyMs(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : null;
}

export async function requestVoiceAnswer(
  sessionId: number,
  transcript: string,
  language: string,
  signal: AbortSignal,
): Promise<VoiceAnswer> {
  signal.throwIfAborted();
  const questionText = transcript.trim();
  if (!questionText) throw new Error('Whisper did not detect a question.');

  const languageCode = language.trim();
  if (languageCode.length < 2 || languageCode.length > 16) {
    throw new Error('Whisper did not provide a valid language code.');
  }

  const token = await getAccessToken();
  if (!token) throw new Error('Please log in first.');

  const headers = {
    Authorization: `Bearer ${token}`,
    'Content-Type': 'application/json',
  };

  async function request(path: string, failureMessage: string, init?: RequestInit) {
    signal.throwIfAborted();
    const response = await fetch(`${API_BASE_URL}/api/questions${path}`, {
      ...init,
      headers,
      signal,
    });
    signal.throwIfAborted();

    if (!response.ok) {
      const error = await response.json().catch(() => null);
      throw new Error(
        typeof error?.detail === 'string'
          ? error.detail
          : `${failureMessage} (${response.status}).`,
      );
    }

    return response;
  }

  const created = await request('/', 'Could not create the question', {
    method: 'POST',
    body: JSON.stringify({
      session_id: sessionId,
      client_request_id: randomUUID(),
      input_type: 'voice',
    }),
  });
  const question = await created.json().catch(() => null);
  if (!Number.isSafeInteger(question?.question_id) || question.question_id <= 0) {
    throw new Error('The server did not return a valid question ID.');
  }
  const questionPath = `/${question.question_id}`;

  await request(`${questionPath}/status?new_status=transcribing`, 'Could not start transcription', {
    method: 'PATCH',
  });
  await request(`${questionPath}/transcription`, 'Could not process the question', {
    method: 'PATCH',
    body: JSON.stringify({ question_text: questionText, language_code: languageCode }),
  });

  const response = await request(`${questionPath}/answer`, 'Could not retrieve an answer');
  const answer = await response.json().catch(() => null);
  signal.throwIfAborted();
  if (
    typeof answer?.answer_text !== 'string' || !answer.answer_text.trim() ||
    typeof answer.language_code !== 'string' || !answer.language_code.trim()
  ) {
    throw new Error('The server did not return an answer to speak.');
  }

  const voiceAnswer: VoiceAnswer = {
    answer_text: answer.answer_text,
    language_code: answer.language_code,
  };
  if (__DEV__) {
    voiceAnswer.timings = {
      retrieval_ms: readLatencyMs(answer.retrieval_latency_ms),
      gemini_ms: answer.answer_type === 'no_evidence'
        ? null
        : readLatencyMs(answer.generation_latency_ms),
    };
  }
  return voiceAnswer;
}
