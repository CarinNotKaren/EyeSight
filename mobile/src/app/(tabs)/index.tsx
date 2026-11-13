import { useRouter } from 'expo-router';
import { logout } from '../../services/auth';
import { useEffect, useState } from 'react';
import { CameraView, useCameraPermissions } from 'expo-camera';
import {
  useAudioRecorder,
  useAudioRecorderState,
   useAudioPlayer,
  RecordingPresets,
  requestRecordingPermissionsAsync,
  setAudioModeAsync,
} from 'expo-audio';
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
import { SafeAreaView } from 'react-native-safe-area-context';

export default function HomeScreen() {
    const router = useRouter();
  const [loggingOut, setLoggingOut] = useState(false);

  async function handleLogout() {
    if (loggingOut || sessionActive) return;

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

  async function startSession() {
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

    setSessionActive(true);
  }

  function stopSession() {
    setSessionActive(false);
    Alert.alert('EyeSight', 'Session stopped!');
  }

  async function askQuestion() {
  try {
    // Stop recording if the user is already recording
    if (recorderState.isRecording) {
      await audioRecorder.stop();

      const uri = audioRecorder.uri;
      setRecordedAudioUri(uri);
      setRecordingFinished(!!uri);

      Alert.alert(
        'EyeSight',
        uri
          ? 'Your question was recorded successfully!'
          : 'Recording stopped, but no audio file was found.'
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
      'Recording Error',
      error instanceof Error
        ? error.message
        : 'Something went wrong while recording.'
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

          {sessionActive && (
            <View
              style={[
                styles.cameraContainer,
                isWideScreen && styles.wideCamera,
              ]}
            >
              <CameraView
                style={styles.camera}
                facing="back"
                active={sessionActive}
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
                sessionActive && styles.disabledButton,
              ]}
              onPress={startSession}
              disabled={sessionActive}
              accessibilityRole="button"
              accessibilityLabel="Start EyeSight session"
              accessibilityState={{ disabled: sessionActive }}
            >
              <Text style={styles.buttonText}>
                Start Session
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
    (loggingOut || sessionActive) && styles.disabledButton,
  ]}
  onPress={handleLogout}
  disabled={loggingOut || sessionActive}
  accessibilityRole="button"
  accessibilityLabel="Log out of EyeSight"
  accessibilityState={{
    disabled: loggingOut || sessionActive,
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
