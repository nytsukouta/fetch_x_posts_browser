from build_excluded_tweet_ids import extract_tweet_id_from_url


def test_extract_tweet_id_standard():
    assert extract_tweet_id_from_url("https://x.com/user/status/1234567890") == "1234567890"


def test_extract_tweet_id_with_query_string():
    assert extract_tweet_id_from_url("https://twitter.com/user/status/9876543210?s=20") == "9876543210"


def test_extract_tweet_id_no_match():
    assert extract_tweet_id_from_url("https://x.com/user") == ""
    assert extract_tweet_id_from_url("") == ""
