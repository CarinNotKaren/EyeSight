
import * as SecureStore from 'expo-secure-store';
import * as Crypto from 'expo-crypto';
import { Platform } from 'react-native';

const INSTALLATION_ID_KEY = 'eyesight_installation_id';

export async function getInstallationId(): Promise<string> {
  let installationId = await SecureStore.getItemAsync(
    INSTALLATION_ID_KEY
  );

  if (!installationId) {
    installationId = Crypto.randomUUID();

    await SecureStore.setItemAsync(
      INSTALLATION_ID_KEY,
      installationId
    );
  }

  return installationId;
}

export function getDevicePlatform(): 'ios' | 'android' {
  if (Platform.OS === 'ios') {
    return 'ios';
  }

  if (Platform.OS === 'android') {
    return 'android';
  }

  throw new Error('Unsupported device platform');
}
