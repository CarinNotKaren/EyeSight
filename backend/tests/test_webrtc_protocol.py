"""Offline tests for the WebRTC signaling contract and safety limits."""

import pytest
from pydantic import ValidationError

from routers.webrtc import OfferPayload, MAX_SIGNAL_MESSAGE_BYTES


def test_offer_requires_offer_type():
    """Only an SDP offer can start a mobile WebRTC connection."""
    with pytest.raises(ValidationError):
        OfferPayload.model_validate({"type": "answer", "sdp": "v=0"})


def test_offer_requires_non_empty_sdp():
    """An empty SDP must not be passed into aiortc."""
    with pytest.raises(ValidationError):
        OfferPayload.model_validate({"type": "offer", "sdp": ""})


def test_offer_accepts_valid_sdp():
    """A non-empty SDP offer is accepted for WebRTC negotiation."""
    offer = OfferPayload.model_validate({"type": "offer", "sdp": "v=0\r\n"})
    assert offer.type == "offer"
    assert offer.sdp.startswith("v=0")


def test_offer_sdp_is_bounded():
    """Reject oversized SDP before allocating a peer connection."""
    with pytest.raises(ValidationError):
        OfferPayload.model_validate({
            "type": "offer",
            "sdp": "x" * (MAX_SIGNAL_MESSAGE_BYTES + 1),
        })
