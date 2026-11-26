
import * as SecureStore from "expo-secure-store";
// Connect the physical phone to the backend running on your computer.
export const API_BASE_URL = "http://192.168.0.7:8000";



export async function login(
  email: string,
  password: string
) {
  const response = await fetch(`${API_BASE_URL}/auth/login`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      email,
      password,
    }),
  });

  const data = await response.json();

  
if (!response.ok) {
  throw new Error(data.detail || "Login failed");
}

// Save both tokens securely on the phone
await SecureStore.setItemAsync(
  "access_token",
  data.access_token
);

await SecureStore.setItemAsync(
  "refresh_token",
  data.refresh_token
);

return data;

}

export async function getAccessToken() {
  return await SecureStore.getItemAsync("access_token");
}

export async function getRefreshToken() {
  return await SecureStore.getItemAsync("refresh_token");
}

export async function clearTokens() {
  await SecureStore.deleteItemAsync("access_token");
  await SecureStore.deleteItemAsync("refresh_token");
}

export async function logout() {
  const refreshToken = await getRefreshToken();

  try {
    if (refreshToken) {
      const response = await fetch(`${API_BASE_URL}/auth/logout`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          refresh_token: refreshToken,
        }),
      });

      if (!response.ok) {
        throw new Error("Logout request failed");
      }
    }
  } finally {
    // Remove saved tokens from the phone
    await clearTokens();
  }
}

export async function refreshAccessToken() {
  const refreshToken = await getRefreshToken();

  if (!refreshToken) {
    throw new Error("No refresh token found");
  }

  const response = await fetch(`${API_BASE_URL}/auth/refresh`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      refresh_token: refreshToken,
    }),
  });

  const data = await response.json();

  if (!response.ok) {
    throw new Error(data.detail || "Token refresh failed");
  }

  // Save the new access token
  await SecureStore.setItemAsync(
    "access_token",
    data.access_token
  );

  // Save the new refresh token
  await SecureStore.setItemAsync(
    "refresh_token",
    data.refresh_token
  );

  return data.access_token;
}

export async function signup(
  email: string,
  password: string,
  displayName: string
) {
  const response = await fetch(`${API_BASE_URL}/auth/signup`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      email: email,
      password: password,
      display_name: displayName,
    }),
  });

  const data = await response.json();

  if (!response.ok) {
    throw new Error(data.detail || "Sign up failed");
  }

  return data;
}
