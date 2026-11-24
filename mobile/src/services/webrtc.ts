
import {
  mediaDevices,
  MediaStream,
  RTCPeerConnection,
  RTCIceCandidate,
} from 'react-native-webrtc';

// Get video from the phone's back camera.
export async function startCameraStream(): Promise<MediaStream> {
  try {
    const stream = await mediaDevices.getUserMedia({
      audio: false,
      video: {
        facingMode: 'environment',
        width: 640,
        height: 480,
        frameRate: 15,
      },
    });

    console.log('WebRTC camera stream created');
    return stream;
  } catch (error) {
    console.error('WebRTC camera error:', error);
    throw error;
  }
}

// Release the camera when the session stops.
export function stopCameraStream(stream: MediaStream | null) {
  if (!stream) return;

  stream.getTracks().forEach((track) => track.stop());
  console.log('WebRTC camera stream stopped');
}
// Create the connection that will send video to the backend.
export function createPeerConnection(stream: MediaStream) {
  const peerConnection = new RTCPeerConnection({
    iceServers: [
      {
        urls: 'stun:stun.l.google.com:19302',
      },
    ],
  });

  // Add the camera's video tracks to the connection.
  stream.getTracks().forEach((track) => {
    peerConnection.addTrack(track, stream);
  });

  
  // Monitor the connection between the phone and backend.
  peerConnection.onconnectionstatechange = () => {
    console.log(
      'WebRTC connection state:',
      peerConnection.connectionState
    );

    if (peerConnection.connectionState === 'connected') {
      console.log('WebRTC connected successfully!');
    }

    if (peerConnection.connectionState === 'failed') {
      console.log('WebRTC connection failed');
    }

    if (peerConnection.connectionState === 'disconnected') {
      console.log('WebRTC disconnected');
    }
  };

  console.log('WebRTC peer connection created');

  return peerConnection;

}

export async function createWebRTCOffer(
  peerConnection: RTCPeerConnection
) {
  // Create an SDP offer describing our video stream.
  const offer = await peerConnection.createOffer();

  // Save the offer as the local connection description.
  await peerConnection.setLocalDescription(offer);

  console.log('WebRTC SDP offer created');

  return offer;
}

export async function applyWebRTCAnswer(
  peerConnection: RTCPeerConnection,
  answerSdp: string
) {
  await peerConnection.setRemoteDescription({
    type: 'answer',
    sdp: answerSdp,
  });

  console.log('WebRTC SDP answer applied');
}

export async function addRemoteIceCandidate(
  peerConnection: RTCPeerConnection,
  candidate: {
    candidate: string;
    sdpMid?: string | null;
    sdpMLineIndex?: number | null;
  }
) {
  await peerConnection.addIceCandidate(
    new RTCIceCandidate(candidate)
  );

  console.log('Remote ICE candidate added');
}

export function closeWebRTCConnection(
  peerConnection: RTCPeerConnection | null,
  stream: MediaStream | null
) {
  if (peerConnection) {
    peerConnection.close();
    console.log('WebRTC peer connection closed');
  }

  stopCameraStream(stream);

  console.log('WebRTC resources released');
}

export function observeLocalIceCandidates(
  peerConnection: RTCPeerConnection,
  onCandidate: (candidate: {
    candidate: string;
    sdpMid: string | null;
    sdpMLineIndex: number | null;
  }) => void
) {
peerConnection.onicecandidate = (event: any) => {
    if (event.candidate) {
      const candidate = event.candidate.toJSON();

      onCandidate({
        candidate: candidate.candidate,
        sdpMid: candidate.sdpMid ?? null,
        sdpMLineIndex: candidate.sdpMLineIndex ?? null,
      });

      console.log('Local ICE candidate generated');
    }
  };
}
