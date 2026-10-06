import hashlib
import hmac

from erp_social.utils.signatures import (
	meta_appsecret_proof,
	parse_tiktok_signature_header,
	verify_meta_signature,
	verify_tiktok_signature,
)

SECRET = "s3cret"
BODY = b'{"object":"page","entry":[]}'


def _hex(key, msg):
	return hmac.new(key.encode(), msg, hashlib.sha256).hexdigest()


def test_meta_signature_valid():
	assert verify_meta_signature(BODY, "sha256=" + _hex(SECRET, BODY), SECRET)


def test_meta_signature_rejects_tampered_body_wrong_secret_and_bad_headers():
	header = "sha256=" + _hex(SECRET, BODY)
	assert not verify_meta_signature(BODY + b" ", header, SECRET)
	assert not verify_meta_signature(BODY, header, "other")
	assert not verify_meta_signature(BODY, "sha1=" + _hex(SECRET, BODY), SECRET)
	assert not verify_meta_signature(BODY, None, SECRET)
	assert not verify_meta_signature(BODY, "sha256=", SECRET)
	assert not verify_meta_signature(BODY, header, "")


def test_appsecret_proof():
	assert meta_appsecret_proof("token", SECRET) == _hex(SECRET, b"token")


def test_parse_tiktok_header():
	assert parse_tiktok_signature_header("t=1700000000,s=abc") == ("1700000000", "abc")
	assert parse_tiktok_signature_header("s=abc,t=1700000000") == ("1700000000", "abc")
	assert parse_tiktok_signature_header("t=notanumber,s=abc") is None
	assert parse_tiktok_signature_header("t=1700000000") is None
	assert parse_tiktok_signature_header(None) is None


def test_tiktok_signature_valid_and_replay_window():
	ts = 1_700_000_000
	header = f"t={ts},s=" + _hex(SECRET, f"{ts}.".encode() + BODY)
	assert verify_tiktok_signature(BODY, header, SECRET, now=ts + 10)
	assert not verify_tiktok_signature(BODY, header, SECRET, now=ts + 301)
	assert not verify_tiktok_signature(BODY + b"x", header, SECRET, now=ts)
	assert not verify_tiktok_signature(BODY, header, "other", now=ts)
