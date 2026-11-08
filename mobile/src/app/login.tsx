
import { useRouter } from "expo-router";
import React, { useState } from "react";
import { SafeAreaView } from "react-native-safe-area-context";
import {
  View,
  Text,
  TextInput,
  TouchableOpacity,
  StyleSheet,
  Alert,
  KeyboardAvoidingView,
ScrollView,
Platform,
} from "react-native";

import { login } from "../services/auth";

export default function LoginScreen() {
    const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);

  
async function handleLogin() {
  if (loading) return;

  if (!email.trim() || !password) {
    Alert.alert("Missing information", "Please enter your email and password.");
    return;
  }

  setLoading(true);

  try {
    await login(email.trim(), password);
    Alert.alert("Success", "Login successful!");
  } catch (error) {
    Alert.alert(
      "Login failed",
      error instanceof Error ? error.message : "Something went wrong"
    );
  } finally {
    setLoading(false);
  }
}


 return (
  <SafeAreaView style={styles.container}>
    <KeyboardAvoidingView
      style={{ flex: 1 }}
      behavior={Platform.OS === "ios" ? "padding" : undefined}
    >
      <ScrollView
        contentContainerStyle={styles.scrollContent}
        keyboardShouldPersistTaps="handled"
      >
      <Text style={styles.title}>EyeSight</Text>
      <Text style={styles.subtitle}>Welcome back!</Text>

     
<TextInput
  style={styles.input}
  placeholder="Email"
  autoCapitalize="none"
  keyboardType="email-address"
  autoComplete="email"
  textContentType="emailAddress"
  accessibilityLabel="Email address"
  accessibilityHint="Enter your email address to log in"
  value={email}
  onChangeText={setEmail}
/>


     
<TextInput
  style={styles.input}
  placeholder="Password"
  secureTextEntry
  autoComplete="current-password"
  textContentType="password"
  accessibilityLabel="Password"
  accessibilityHint="Enter your account password"
  value={password}
  onChangeText={setPassword}
/>

     
<TouchableOpacity
  style={[styles.button, loading && styles.disabledButton]}
  onPress={handleLogin}
  disabled={loading}
  accessibilityRole="button"
  accessibilityLabel={loading ? "Logging in" : "Log in"}
  accessibilityState={{ disabled: loading, busy: loading }}
>
  <Text style={styles.buttonText}>
    {loading ? "Logging in..." : "Login"}
  </Text>

      </TouchableOpacity>

      {/* Sign Up link */}
      <TouchableOpacity
        style={styles.signupLink}
        onPress={() => router.push("/signup")}
        accessibilityRole="link"
        accessibilityLabel="Don't have an account? Sign up"
      >
        <Text style={styles.linkText}>
          Don't have an account? Sign Up
        </Text>
      </TouchableOpacity>

    </ScrollView>
  </KeyboardAvoidingView>
</SafeAreaView>
);
}



  


const styles = StyleSheet.create({
    
signupLink: {
  marginTop: 24,
  padding: 12,
  alignItems: "center",
},
linkText: {
  color: "#2563EB",
  fontSize: 16,
  fontWeight: "600",
},

    disabledButton: {
  opacity: 0.6,
},
    scrollContent: {
  flexGrow: 1,
  justifyContent: "center",
  paddingVertical: 24,
  width: "100%",
  maxWidth: 420,
  alignSelf: "center",
},
  container: {
    flex: 1,
    justifyContent: "center",
    padding: 24,
    backgroundColor: "#FFFFFF",
  },
  title: {
    fontSize: 36,
    fontWeight: "bold",
    textAlign: "center",
    marginBottom: 10,
  },
  subtitle: {
    fontSize: 18,
    textAlign: "center",
    marginBottom: 30,
  },
  input: {
    borderWidth: 1,
    borderColor: "#CCCCCC",
    borderRadius: 10,
    padding: 15,
    marginBottom: 15,
    fontSize: 16,
  },
  button: {
    backgroundColor: "#2563EB",
    padding: 16,
    borderRadius: 10,
    alignItems: "center",
  },
  buttonText: {
    color: "#FFFFFF",
    fontSize: 18,
    fontWeight: "bold",
  },
});
