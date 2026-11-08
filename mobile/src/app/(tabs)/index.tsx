
import { useEffect, useState } from 'react';
import { CameraView, useCameraPermissions } from 'expo-camera';
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
  const [sessionActive, setSessionActive] = useState(false);
  const [permission, requestPermission] = useCameraPermissions();
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

  function askQuestion() {
    Alert.alert(
      'EyeSight',
      'Microphone and AI will be connected in the next steps.'
    );
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

            <TouchableOpacity
              style={[
                styles.questionButton,
                !sessionActive && styles.disabledButton,
              ]}
              onPress={askQuestion}
              disabled={!sessionActive}
              accessibilityRole="button"
              accessibilityLabel="Ask EyeSight a question"
              accessibilityState={{ disabled: !sessionActive }}
            >
              <Text style={styles.buttonText}>
                Ask a Question
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
  disabledButton: {
    opacity: 0.4,
  },
  buttonText: {
    color: '#FFFFFF',
    fontSize: 20,
    fontWeight: 'bold',
    textAlign: 'center',
  },
});
