import { connectWebRTCSignaling } from '../../services/signaling';
import { useRouter } from 'expo-router';
import { API_BASE_URL, getAccessToken, logout } from '../../services/auth';
import { useEffect, useRef, useState } from 'react';
import { CameraView, useCameraPermissions } from 'expo-camera';
import {
  useAudioRecorder,
  useAudioRecorderState,
   useAudioPlayer,
  RecordingPresets,
  requestRecordingPermissionsAsync,
  setAudioModeAsync,
} from 'expo-audio';
import { getInstallationId, getDevicePlatform } from '../../services/device';
import * as Speech from 'expo-speech';
import { requestVoiceAnswer } from '../../services/questions';
import { transcribeRecording } from '../../services/speech';
import {
  Alert,
  Platform,
  ScrollView,
  StyleSheet,
  Text,
  TouchableOpacity,
  useWindowDimensions,
  View,
} from 'react-native';
import {
  registerDevice,
  createCaptureSession,
  endCaptureSession,
} from "../../services/session";
import {
  MediaStream,
  RTCPeerConnection,
  RTCView,
} from 'react-native-webrtc';

import {
  startCameraStream,
  createPeerConnection,
  createWebRTCOffer,
  closeWebRTCConnection,
} from '../../services/webrtc';

import { SafeAreaView } from 'react-native-safe-area-context';

export default function HomeScreen() {
    const router = useRouter();
  const [loggingOut, setLoggingOut] = useState(false);

  async function handleLogout() {
    if (loggingOut || sessionActive || sessionLoading) return;

    setLoggingOut(true);

    try {
      await logout();
      router.replace('/login');
    } catch (error) {
      Alert.alert(
        'Logout failed',
        error instanceof Error ? error.message : 'Something went wrong'
      );
    } finally {
      setLoggingOut(false);
    }
  }
  const [sessionActive, setSessionActive] = useState(false);
  const [sessionLoading, setSessionLoading] = useState(false);

const [webrtcStream, setWebrtcStream] = useState<MediaStream | null>(null);

const peerConnectionRef = useRef<RTCPeerConnection | null>(null);
const streamRef = useRef<MediaStream | null>(null);
const backendSessionIdRef = useRef<number | null>(null);
const signalingSocketRef = useRef<WebSocket | null>(null);

  // Temporary frame diagnostics for development builds.
  useEffect(() => {
    if (!__DEV__ || !sessionActive) return;

    const sessionId = backendSessionIdRef.current;
    if (sessionId === null) return;

    const controller = new AbortController();
    let inFlight = false;
    const isCurrentSession = () =>
      !controller.signal.aborted && backendSessionIdRef.current === sessionId;

    function stopPolling() {
      clearInterval(interval);
      controller.abort();
    }

    async function pollFrameStatus() {
      if (inFlight || !isCurrentSession()) return;
      inFlight = true;

      try {
        const token = await getAccessToken();
        if (!token || !isCurrentSession()) return;

        const response = await fetch(
          `${API_BASE_URL}/api/webrtc/sessions/${sessionId}/status?token=${encodeURIComponent(token)}`,
          { signal: controller.signal },
        );

        if (response.status === 409 || response.status === 410) {
          stopPolling();
          return;
        }
        if (!response.ok) return;

        const { connection_state, received_frames, saved_frames } = await response.json();
        if (
          isCurrentSession() &&
          typeof connection_state === 'string' &&
          typeof received_frames === 'number' &&
          typeof saved_frames === 'number'
        ) {
          console.log({ connection_state, received_frames, saved_frames });
        }
      } catch {
        // Request errors can contain the authenticated URL.
      } finally {
        inFlight = false;
      }
    }

    const interval = setInterval(() => void pollFrameStatus(), 2000);
    void pollFrameStatus();
    return stopPolling;
  }, [sessionActive]);

  const [permission, requestPermission] = useCameraPermissions();
  // Microphone recording
const audioRecorder = useAudioRecorder(RecordingPresets.HIGH_QUALITY);

const recorderState = useAudioRecorderState(audioRecorder);

const [recordedAudioUri, setRecordedAudioUri] = useState<string | null>(null);
  const [questionTranscript, setQuestionTranscript] = useState('');
  const audioPlayer = useAudioPlayer(null, { keepAudioSessionActive: true });
  const [questionBusy, setQuestionBusy] = useState(false);
  const questionOperationRef = useRef<AbortController | null>(null);
  const questionRecordingRef = useRef<{ stopping?: Promise<void> } | null>(null);
  const { width, height } = useWindowDimensions();

  useEffect(() => () => {
    questionOperationRef.current?.abort();
    void Speech.stop().catch(() => undefined);
  }, []);

const [screenReady, setScreenReady] = useState(false);

useEffect(() => {
  setScreenReady(true);
}, []);

const responsiveWidth = screenReady ? width : 390;
const responsiveHeight = screenReady ? height : 800;

const isWideScreen = responsiveWidth >= 900;
const isTablet = responsiveWidth >= 600 && responsiveWidth < 900;
const isShortScreen = responsiveHeight < 650;
const requestStreamingConsent = (): Promise<boolean> => {
  return new Promise((resolve) => {
    Alert.alert(
      "Start EyeSight Session",
      "EyeSight will access your camera and send video to the backend for AI processing. Do you agree?",
      [
        {
          text: "Cancel",
          style: "cancel",
          onPress: () => resolve(false),
        },
        {
          text: "Agree",
          onPress: () => resolve(true),
        },
      ],
      {
        cancelable: false,
      }
    );
  });
};


async function startSession() {
  if (sessionLoading || sessionActive) return;

  setSessionLoading(true);

  try {
    // 1. Ask for consent
    console.log('CONSENT FUNCTION CALLED');
    const consent = await requestStreamingConsent();

    if (!consent) {
      return;
    }

    // 2. Check camera permission
    let cameraPermission = permission;

    if (!cameraPermission?.granted) {
      cameraPermission = await requestPermission();
    }

    if (!cameraPermission?.granted) {
      Alert.alert(
        'Camera Permission',
        'EyeSight needs camera access to help you understand your surroundings.'
      );
      return;
    }

    // 3. Get device information
    const installationId = await getInstallationId();
    const platform = getDevicePlatform();

    console.log('EyeSight Installation ID:', installationId);
    console.log('Device Platform:', platform);

    // 4. Register the device in the backend
    const deviceId = await registerDevice();
    console.log('Registered Device ID:', deviceId);

    // 5. Create the backend session
    const sessionId = await createCaptureSession(deviceId);

backendSessionIdRef.current = sessionId;

console.log('Backend Session ID:', sessionId);

    // 6. Start the camera
    const stream = await startCameraStream();
    streamRef.current = stream;

    // 7. Create the WebRTC peer connection
    const peerConnection = createPeerConnection(stream);
    peerConnectionRef.current = peerConnection;
    // Connect the iPhone camera to the FastAPI WebRTC backend
const signalingSocket = await connectWebRTCSignaling(
  sessionId,
  peerConnection
);

signalingSocketRef.current = signalingSocket;

console.log('WebRTC signaling completed');
    // 8. Display the camera preview
    setWebrtcStream(stream);
    setSessionActive(true);

    console.log('EyeSight camera started');
    } catch (error) {

    const failedSessionId = backendSessionIdRef.current;
    backendSessionIdRef.current = null;

    // Release the camera and peer before waiting for the backend request.
    signalingSocketRef.current?.close();
    signalingSocketRef.current = null;
    closeWebRTCConnection(
      peerConnectionRef.current,
      streamRef.current
    );

    peerConnectionRef.current = null;
    streamRef.current = null;

    setWebrtcStream(null);
    setSessionActive(false);

    if (failedSessionId !== null) {
      try {
        await endCaptureSession(failedSessionId);
      } catch (cleanupError) {
        console.error('Failed to end backend session:', cleanupError);
      }
    }

    Alert.alert(
      'Session Error',
      error instanceof Error
        ? error.message
        : 'Unable to start EyeSight session.'
    );
     } finally {
    setSessionLoading(false);
  }
}


async function stopSession() {
  // Close signaling when the user stops the session
signalingSocketRef.current?.close();
signalingSocketRef.current = null;
  // Get the current backend session ID
  const sessionId = backendSessionIdRef.current;
  backendSessionIdRef.current = null;
  questionOperationRef.current?.abort();

  // Stop the camera and close the local WebRTC connection
  closeWebRTCConnection(
    peerConnectionRef.current,
    streamRef.current
  );

  peerConnectionRef.current = null;
  streamRef.current = null;

  setWebrtcStream(null);
  setSessionActive(false);

  setRecordedAudioUri(null);
  setQuestionTranscript('');
  try {
    audioPlayer.pause();
    audioPlayer.replace(null);
  } catch {
    console.warn('Could not clear recording playback.');
  }
  const speechStopped = Speech.stop().catch(() => {
    console.warn('Could not stop speech playback.');
  });

  try {
    await stopQuestionRecording();
  } catch {
    console.warn('Could not stop the question recording.');
  }
  await speechStopped;

  // End the session in the backend
  if (sessionId !== null) {
    try {
      await endCaptureSession(sessionId);
      console.log('Backend session ended:', sessionId);
    } catch (error) {
      console.error('Failed to end backend session:', error);

      Alert.alert(
        'Session Warning',
        'The camera stopped, but the backend session could not be ended.'
      );
      return;
    }
  }

  Alert.alert('EyeSight', 'Session stopped!');
}


async function setQuestionAudioMode(signal: AbortSignal, allowsRecording = false) {
  signal.throwIfAborted();
  audioPlayer.pause();
  await Speech.stop();
  signal.throwIfAborted();
  await setAudioModeAsync({ allowsRecording, playsInSilentMode: true });
  signal.throwIfAborted();
}

async function speakAnswer(
  text: string,
  language: string,
  signal: AbortSignal,
  onStart?: () => void,
) {
  await setQuestionAudioMode(signal);
  signal.throwIfAborted();
  Speech.speak(text, {
    language,
    rate: 0.9,
    pitch: 1.0,
    onStart,
    onError: () => console.warn('Could not speak the answer.'),
  });
}


function stopQuestionRecording() {
  const recording = questionRecordingRef.current;
  if (!recording) return;

  // Stop Recording and Stop Session can both reach the same native recorder.
  recording.stopping ??= audioRecorder.stop().then(() => {
    questionRecordingRef.current = null;
  }).finally(() => {
    recording.stopping = undefined;
  });
  return recording.stopping;
}

async function startQuestionRecording(signal: AbortSignal) {
  const permission = await requestRecordingPermissionsAsync();
  signal.throwIfAborted();

  if (!permission.granted) {
    Alert.alert(
      'Microphone Permission',
      'EyeSight needs microphone access to record your questions.'
    );
    return;
  }

  await setQuestionAudioMode(signal, true);
  signal.throwIfAborted();

  await audioRecorder.prepareToRecordAsync();
  if (signal.aborted) {
    await audioRecorder.stop();
    return;
  }
  audioRecorder.record();
  questionRecordingRef.current = {};

  setRecordedAudioUri(null);
  setQuestionTranscript('');
}

async function playRecording(signal: AbortSignal) {
  if (!recordedAudioUri) {
    throw new Error('No recording available.');
  }

  await setQuestionAudioMode(signal);
  signal.throwIfAborted();
  // Replacing the source starts each replay at the beginning of this recording.
  audioPlayer.replace({ uri: recordedAudioUri });

  const loadDeadline = Date.now() + 5000;
  while (!audioPlayer.isLoaded && Date.now() < loadDeadline) {
    signal.throwIfAborted();
    await new Promise<void>((resolve) => setTimeout(resolve, 50));
  }
  signal.throwIfAborted();
  if (!audioPlayer.isLoaded) throw new Error('The recording did not load. Please try again.');
  audioPlayer.play();
}

async function handleQuestionButton(action: 'record' | 'play') {
  const sessionId = backendSessionIdRef.current;
  if (
    !sessionActive || sessionId === null || questionOperationRef.current ||
    questionRecordingRef.current?.stopping
  ) return;

  const operation = new AbortController();
  const { signal } = operation;
  questionOperationRef.current = operation;
  setQuestionBusy(true);

  try {
    if (action === 'play') {
      if (!questionRecordingRef.current) await playRecording(signal);
    } else if (questionRecordingRef.current) {
      const stopStartedAt = __DEV__ ? performance.now() : 0;
      await stopQuestionRecording();
      signal.throwIfAborted();
      if (__DEV__) {
        console.log('[Voice timing]', { recording_stop_ms: Math.round(performance.now() - stopStartedAt) });
      }

      const uri = audioRecorder.uri;
      if (!uri) throw new Error('No audio file was found.');
      setRecordedAudioUri(uri);

      const whisperStartedAt = __DEV__ ? performance.now() : 0;
      const { transcript, language } = await transcribeRecording(uri, signal);
      signal.throwIfAborted();
      if (__DEV__) {
        console.log('[Voice timing]', { whisper_ms: Math.round(performance.now() - whisperStartedAt) });
      }
      setQuestionTranscript(transcript.trim());

      const questionStartedAt = __DEV__ ? performance.now() : 0;
      const answer = await requestVoiceAnswer(sessionId, transcript, language, signal);
      const speechStartedAt = __DEV__ ? performance.now() : 0;
      if (__DEV__) {
        console.log('[Voice timing]', {
          question_api_ms: Math.round(speechStartedAt - questionStartedAt),
          retrieval_ms: answer.timings?.retrieval_ms ?? null,
          gemini_ms: answer.timings?.gemini_ms ?? null,
        });
      }

      await speakAnswer(answer.answer_text, answer.language_code, signal, __DEV__ ? () => {
        if (signal.aborted) return;
        const playbackStartedAt = performance.now();
        console.log('[Voice timing]', {
          tts_start_ms: Math.round(playbackStartedAt - speechStartedAt),
          total_ms: Math.round(playbackStartedAt - stopStartedAt),
        });
      } : undefined);
    } else {
      await startQuestionRecording(signal);
    }
  } catch (error) {
    if (!signal.aborted) {
      Alert.alert(
        action === 'play' ? 'Playback Error' : 'Question Error',
        error instanceof Error ? error.message : 'The audio action could not be completed.',
      );
    }
  } finally {
    questionOperationRef.current = null;
    setQuestionBusy(false);
  }
}
  return (
    <SafeAreaView style={styles.container}>
      <ScrollView
        style={styles.scrollView}
        contentContainerStyle={styles.scrollContent}
        keyboardShouldPersistTaps="handled"
      >
        <View
          style={[
            styles.content,
            isWideScreen && styles.wideContent,
            {
  paddingHorizontal: responsiveWidth < 360 ? 12 : 20,
  paddingVertical: isShortScreen ? 12 : 24,
},
          ]}
        >
          <Text
            style={[
              styles.title,
              { fontSize: responsiveWidth < 360 ? 30 : isWideScreen ? 42 : 36 },
            ]}
          >
            EyeSight
          </Text>

          <Text style={styles.subtitle}>
            Your AI Visual Assistant
          </Text>

          <View style={styles.statusBox}>
            <Text style={styles.statusLabel}>
              Session Status
            </Text>
            <Text
              style={styles.statusText}
              accessibilityLiveRegion="polite"
            >
              {sessionActive ? 'Active' : 'Inactive'}
            </Text>
          </View>
{sessionActive && webrtcStream && (
  <View
    style={[
      styles.cameraContainer,
      isWideScreen && styles.wideCamera,
    ]}
  >
    <RTCView
      style={styles.camera}
      streamURL={webrtcStream.toURL()}
      objectFit="cover"
      mirror={false}
    />
  </View>
)}
          <View
            style={[
              styles.buttonContainer,
              isTablet && styles.tabletButtons,
            ]}
          >
            <TouchableOpacity
              style={[
                styles.button,
                (sessionActive || sessionLoading) && styles.disabledButton,
              ]}
              onPress={startSession}
              disabled={sessionActive || sessionLoading}
              accessibilityRole="button"
              accessibilityLabel="Start EyeSight session"
              accessibilityState={{
  disabled: sessionActive || sessionLoading,
  busy: sessionLoading,
}}
            >
              <Text style={styles.buttonText}>
                {sessionLoading ? 'Connecting...' : 'Start Session'}
              </Text>
            </TouchableOpacity>

            <TouchableOpacity
              style={[
                styles.button,
                sessionActive && styles.stopButton,
                !sessionActive && styles.disabledButton,
              ]}
              onPress={stopSession}
              disabled={!sessionActive}
              accessibilityRole="button"
              accessibilityLabel="Stop EyeSight session"
              accessibilityState={{ disabled: !sessionActive }}
            >
              <Text style={styles.buttonText}>
                Stop Session
              </Text>
            </TouchableOpacity>


            <TouchableOpacity
  style={[
    styles.questionButton,
    recorderState.isRecording && styles.recordingButton,
    (!sessionActive || questionBusy) && styles.disabledButton,
  ]}
  onPress={() => void handleQuestionButton('record')}
  disabled={!sessionActive || questionBusy}
  accessibilityRole="button"
  accessibilityLabel={recorderState.isRecording ? 'Stop recording' : 'Ask EyeSight a question'}
  accessibilityState={{ disabled: !sessionActive || questionBusy, busy: questionBusy }}
>
  <Text style={styles.buttonText}>
    {recorderState.isRecording ? 'Stop Recording' : 'Ask a Question'}
  </Text>
</TouchableOpacity>
{sessionActive && recordedAudioUri && (
  <TouchableOpacity
    style={[styles.playButton, questionBusy && styles.disabledButton]}
    onPress={() => void handleQuestionButton('play')}
    disabled={questionBusy}
    accessibilityRole="button"
    accessibilityState={{ disabled: questionBusy }}
  >
    <Text style={styles.buttonText}>Play Recording</Text>
  </TouchableOpacity>
)}
{sessionActive && questionTranscript !== '' && (
  <Text style={styles.questionTranscript}>You said “{questionTranscript}”</Text>
)}
{/* Logout Button */}
<TouchableOpacity
  style={[
    styles.logoutButton,
    (loggingOut || sessionActive || sessionLoading) && styles.disabledButton,
  ]}
  onPress={handleLogout}
  disabled={loggingOut || sessionActive || sessionLoading}
  accessibilityRole="button"
  accessibilityLabel="Log out of EyeSight"
  accessibilityState={{
   disabled: loggingOut || sessionActive || sessionLoading,
    busy: loggingOut,
  }}
>
  <Text style={styles.logoutButtonText}>
    {loggingOut ? 'Logging out...' : 'Logout'}
  </Text>
</TouchableOpacity>
        </View>
         </View>
      </ScrollView>
    </SafeAreaView>
  );
}


const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#F5F8FF',
  },
  scrollView: {
    flex: 1,
  },
  scrollContent: {
  flexGrow: 1,
  alignItems: 'center',
  paddingTop: Platform.OS === 'web' ? 90 : 16,
  paddingBottom: 40,
},
  content: {
    width: '100%',
    maxWidth: 650,
  },
  wideContent: {
    maxWidth: 850,
  },
  title: {
    fontWeight: 'bold',
    textAlign: 'center',
    color: '#164A9C',
  },
  subtitle: {
    fontSize: 19,
    textAlign: 'center',
    marginTop: 10,
    marginBottom: 28,
    color: '#444',
  },
  statusBox: {
    backgroundColor: '#FFFFFF',
    padding: 20,
    borderRadius: 16,
    marginBottom: 24,
    alignItems: 'center',
  },
  statusLabel: {
    fontSize: 20,
    fontWeight: 'bold',
    textAlign: 'center',
  },
  statusText: {
    fontSize: 24,
    marginTop: 10,
    color: '#164A9C',
  },
  cameraContainer: {
    width: '100%',
    aspectRatio: 4 / 3,
    maxHeight: 420,
    borderRadius: 14,
    overflow: 'hidden',
    marginBottom: 20,
    backgroundColor: '#000000',
  },
  wideCamera: {
    aspectRatio: 16 / 9,
  },
  camera: {
    flex: 1,
  },
  buttonContainer: {
    width: '100%',
  },
  tabletButtons: {
    alignSelf: 'center',
    maxWidth: 520,
  },
  button: {
    backgroundColor: '#1769D2',
    paddingVertical: 18,
    paddingHorizontal: 12,
    minHeight: 60,
    borderRadius: 14,
    marginBottom: 14,
    alignItems: 'center',
    justifyContent: 'center',
  },
  stopButton: {
    backgroundColor: '#1769D2',
  },
  questionButton: {
    backgroundColor: '#087F75',
    paddingVertical: 18,
    paddingHorizontal: 12,
    minHeight: 60,
    borderRadius: 14,
    alignItems: 'center',
    justifyContent: 'center',
  },
  recordingButton: {
  backgroundColor: '#B42318',
},
playButton: {
  backgroundColor: '#475569',
  paddingVertical: 18,
  paddingHorizontal: 12,
  minHeight: 60,
  borderRadius: 14,
  marginTop: 12,
  alignItems: 'center',
  justifyContent: 'center',
},
  questionTranscript: {
    marginTop: 12,
    color: '#25354D',
    fontSize: 18,
    lineHeight: 24,
  },
  disabledButton: {
    opacity: 0.4,
  },
   buttonText: {
    color: '#FFFFFF',
    fontSize: 20,
    fontWeight: 'bold',
    textAlign: 'center',
  },

  logoutButton: {
    backgroundColor: '#FFFFFF',
    borderWidth: 2,
    borderColor: '#B42318',
    paddingVertical: 16,
    paddingHorizontal: 12,
    minHeight: 60,
    borderRadius: 14,
    marginTop: 20,
    alignItems: 'center',
    justifyContent: 'center',
  },

  logoutButtonText: {
    color: '#B42318',
    fontSize: 20,
    fontWeight: 'bold',
    textAlign: 'center',
  },
});
