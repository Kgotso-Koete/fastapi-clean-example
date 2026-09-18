import secrets

# GitHub/Stripe-style prefix: lets automated secret-scanners recognize a
# leaked key by pattern, and doubles as this key's own key_prefix source.
RAW_API_KEY_PREFIX = "ak_"


def generate_raw_api_key() -> str:
    # 256 bits of secrets-sourced entropy -- far beyond what any offline
    # brute-force attack could meaningfully threaten, which is exactly why
    # the hashing decision for this feature doesn't need bcrypt's
    # deliberately-slow KDF (see HmacSha256ApiKeyHasher).
    return f"{RAW_API_KEY_PREFIX}{secrets.token_urlsafe(32)}"
