from location_normalization import extract_prefecture


def test_extracts_prefecture_from_normalized_locations():
    assert extract_prefecture("石川県金沢市 / 石川県") == "石川県"
    assert extract_prefecture("石川県七尾市 / 石川県能登地方 / 石川県") == "石川県"


def test_extracts_prefecture_from_full_address_and_other_regions():
    assert extract_prefecture("〒926-0021 石川県七尾市本府中町") == "石川県"
    assert extract_prefecture("富山県富山市") == "富山県"
    assert extract_prefecture("福井県") == "福井県"
    assert extract_prefecture("東京都新宿区") == "東京都"
    assert extract_prefecture("北海道札幌市") == "北海道"
    assert extract_prefecture("京都府京都市") == "京都府"


def test_infers_hokuriku_prefecture_from_unambiguous_city():
    assert extract_prefecture("金沢市") == "石川県"
    assert extract_prefecture("富山市") == "富山県"
    assert extract_prefecture("福井市") == "福井県"


def test_does_not_guess_ambiguous_or_multiple_regions():
    assert extract_prefecture("北陸地方") == ""
    assert extract_prefecture("石川県 / 富山県") == ""
    assert extract_prefecture("") == ""
    assert extract_prefecture(None) == ""
