from alpha_engine.taxonomy import classify_market, event_key


def test_short_crypto_and_sports_tokens_use_word_boundaries():
    assert classify_market("Will the Netherlands GDP grow in 2026?") == "economy"
    assert classify_market("Will Elizabeth Warren run for president?") == "politics"
    assert classify_market("Will Seth Rogen win an Oscar?") == "entertainment"
    assert classify_market("Will inflation fall below 2%?") == "economy"


def test_election_siblings_share_event_family():
    ohio = event_key("Will Trump win Ohio?")
    arizona = event_key("Will Trump win Arizona?")
    pennsylvania = event_key("Will Trump win Pennsylvania?")

    assert ohio == arizona == pennsylvania
    assert ohio.startswith("politics:trump:election")
