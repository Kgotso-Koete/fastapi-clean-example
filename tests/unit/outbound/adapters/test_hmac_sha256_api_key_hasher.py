from app.outbound.adapters.hmac_sha256_api_key_hasher import HmacSha256ApiKeyHasher

# No fixture/thread-pool ceremony here, unlike BcryptPasswordHasher's tests --
# HMAC-SHA256 is a deterministic, microsecond-scale operation (see the
# plan's "key-hashing decision" section), so the hasher is synchronous and
# cheap enough to construct directly in each test.


def test_same_raw_key_and_pepper_hash_identically() -> None:
    # Determinism is the whole point: it's what makes an O(1)
    # `WHERE key_hash = :hash` lookup possible, unlike bcrypt's per-call
    # salt (see the plan's "key-hashing decision" section for why bcrypt
    # would be actively wrong here).
    sut = HmacSha256ApiKeyHasher(pepper=b"Habanero")

    assert sut.hash("ak_same-raw-key") == sut.hash("ak_same-raw-key")


def test_different_raw_keys_hash_differently() -> None:
    sut = HmacSha256ApiKeyHasher(pepper=b"Habanero")

    assert sut.hash("ak_raw-key-one") != sut.hash("ak_raw-key-two")


def test_different_peppers_hash_the_same_raw_key_differently() -> None:
    # Proves the pepper is actually mixed into the hash, not ignored --
    # otherwise a leaked `api_keys` table alone would be enough to
    # brute-force match against a known key format (e.g. the "ak_" prefix),
    # with no need to also compromise the app's own secret config.
    raw_key = "ak_same-raw-key"
    hasher1 = HmacSha256ApiKeyHasher(pepper=b"PepperA")
    hasher2 = HmacSha256ApiKeyHasher(pepper=b"PepperB")

    assert hasher1.hash(raw_key) != hasher2.hash(raw_key)


def test_hash_returns_a_sha256_hex_digest() -> None:
    sut = HmacSha256ApiKeyHasher(pepper=b"Habanero")

    result = sut.hash("ak_some-raw-key")

    # A SHA-256 hex digest is always 64 lowercase hex characters -- this
    # also documents the on-disk shape of the `key_hash` column.
    assert len(result) == 64
    assert all(c in "0123456789abcdef" for c in result)
