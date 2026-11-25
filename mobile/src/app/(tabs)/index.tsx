import { connectWebRTCSignaling } from '../../services/signaling';
import { useRouter } from 'expo-router';
import { logout } from '../../services/auth';
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

  const [permission, requestPermission] = useCameraPermissions();
  // Microphone recording
const audioRecorder = useAudioRecorder(RecordingPresets.HIGH_QUALITY);

const recorderState = useAudioRecorderState(audioRecorder);

const [recordedAudioUri, setRecordedAudioUri] = useState<string | null>(null);
const audioPlayer = useAudioPlayer(recordedAudioUri);
const [recordingFinished, setRecordingFinished] = useState(false);
  const { width, height } = useWindowDimensions();

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

  // Stop the camera and close the local WebRTC connection
  closeWebRTCConnection(
    peerConnectionRef.current,
    streamRef.current
  );

  peerConnectionRef.current = null;
  streamRef.current = null;

  setWebrtcStream(null);
  setSessionActive(false);

  // Stop any ongoing text-to-speech
  Speech.stop();

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


async function speakAnswer(
  text: string,
  language: string = 'en'
) {
  try {
    // Stop any previous speech
    Speech.stop();

    // Speak the AI answer
    Speech.speak(text, {
      language,
      rate: 0.9,
      pitch: 1.0,
      onError: (error) => {
        console.error('Text-to-Speech Error:', error);
      },
    });
  } catch (error) {
    console.error('Speech Error:', error);
  }
}


  async function askQuestion() {
  try {
    // Stop recording if the user is already recording
    if (recorderState.isRecording) {
      await audioRecorder.stop();


const uri = audioRecorder.uri;
setRecordedAudioUri(uri);
setRecordingFinished(!!uri);

if (!uri) {
  Alert.alert('EyeSight', 'No audio file was found.');
  return;
}

// Send the recorded audio to Whisper
const result = await transcribeRecording(uri);

console.log('Whisper Transcript:', result.transcript);
console.log('Detected Language:', result.language);
console.log('Duration:', result.duration_seconds);


Alert.alert(
  'EyeSight - Whisper',
  `Your question: ${result.transcript}`,
  [
    {
      text: 'OK',
    },
    {
      text: 'Test Voice',
      onPress: async () => {
        await setAudioModeAsync({
          allowsRecording: false,
          playsInSilentMode: true,
        });

        speakAnswer(
          'Hello! I am EyeSight, your AI visual assistant.',
          'en'
        );
      },
    },
  ]
);


return;

    }

    // Request microphone permission
    const permission = await requestRecordingPermissionsAsync();

    if (!permission.granted) {
      Alert.alert(
        'Microphone Permission',
        'EyeSight needs microphone access to record your questions.'
      );
      return;
    }

    // Configure audio recording
    await setAudioModeAsync({
      allowsRecording: true,
      playsInSilentMode: true,
    });

    // Prepare and start recording
    await audioRecorder.prepareToRecordAsync();
    audioRecorder.record();

    setRecordedAudioUri(null);
    setRecordingFinished(false);

  } catch (error) {
  Alert.alert(
    'Recording or Transcription Error',
    error instanceof Error
      ? error.message
      : 'Something went wrong while recording or transcribing.'
  );
}
}
async function playRecording() {
  if (!recordedAudioUri) {
    Alert.alert('EyeSight', 'No recording available.');
    return;
  }

  try {
    await setAudioModeAsync({
      allowsRecording: false,
      playsInSilentMode: true,
    });

    await audioPlayer.seekTo(0);
    audioPlayer.play();

  } catch (error) {
    Alert.alert(
      'Playback Error',
      error instanceof Error
        ? error.message
        : 'Unable to play recording.'
    );
  }
}

async function handleQuestionButton() {
  if (recorderState.isRecording) {
    await askQuestion();

  } else if (recordingFinished) {
    await playRecording();
    setRecordingFinished(false);

  } else {
    await askQuestion();
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


{/* Play Recorded Question */}


            <TouchableOpacity
  style={[
    styles.questionButton,
    recorderState.isRecording && styles.recordingButton,
    recordingFinished &&
      !recorderState.isRecording &&
      styles.playButton,
    !sessionActive && styles.disabledButton,
  ]}
  onPress={handleQuestionButton}
  disabled={!sessionActive}
  accessibilityRole="button"
  accessibilityLabel={
    recorderState.isRecording
      ? 'Stop recording'
      : recordingFinished
        ? 'Play recorded question'
        : 'Ask EyeSight a question'
  }
  accessibilityState={{ disabled: !sessionActive }}
>
  <Text style={styles.buttonText}>
    {recorderState.isRecording
      ? 'Stop Recording'
      : recordingFinished
        ? 'Play Recording'
        : 'Ask a Question'}
  </Text>
</TouchableOpacity>
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
