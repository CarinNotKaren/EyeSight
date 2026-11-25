
import { API_BASE_URL, getAccessToken } from "./auth";
import { getInstallationId, getDevicePlatform } from "./device";

export async function registerDevice(): Promise<number> {
  const token = await getAccessToken();

  if (!token) {
    throw new Error("Please log in first.");
  }

  const installationId = await getInstallationId();
  const platform = getDevicePlatform();

  const response = await fetch(
    `${API_BASE_URL}/api/devices/register`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({
        installation_id: installationId,
        platform,
        device_name: "EyeSight Mobile",
      }),
    }
  );

  const data = await response.json();

  if (!response.ok) {
    throw new Error(data.detail || "Device registration failed");
  }

  return data.device_id;
}

export async function createCaptureSession(
  deviceId: number
): Promise<number> {
  const token = await getAccessToken();

  if (!token) {
    throw new Error("Please log in first.");
  }

  const response = await fetch(
    `${API_BASE_URL}/api/sessions`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({
        device_id: deviceId,
        language_code: "en",
        consent: true,
        consent_version: "1.0",
      }),
    }
  );

  const data = await response.json();

  if (!response.ok) {
    throw new Error(data.detail || "Session creation failed");
  }

  return data.session_id;
}

export async function endCaptureSession(
  sessionId: number
): Promise<void> {
  const token = await getAccessToken();

  if (!token) {
    throw new Error("Please log in first.");
  }

  const response = await fetch(
    `${API_BASE_URL}/api/sessions/${sessionId}/end`,
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
      },
    }
  );

  if (!response.ok) {
    const data = await response.json().catch(() => null);

    throw new Error(
      data?.detail || "Failed to end backend session"
    );
  }

  console.log("Backend session ended:", sessionId);
}
