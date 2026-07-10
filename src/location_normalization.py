from __future__ import annotations

from typing import Any


PREFECTURES = (
    "北海道",
    "青森県", "岩手県", "宮城県", "秋田県", "山形県", "福島県",
    "茨城県", "栃木県", "群馬県", "埼玉県", "千葉県", "東京都", "神奈川県",
    "新潟県", "富山県", "石川県", "福井県", "山梨県", "長野県",
    "岐阜県", "静岡県", "愛知県", "三重県",
    "滋賀県", "京都府", "大阪府", "兵庫県", "奈良県", "和歌山県",
    "鳥取県", "島根県", "岡山県", "広島県", "山口県",
    "徳島県", "香川県", "愛媛県", "高知県",
    "福岡県", "佐賀県", "長崎県", "熊本県", "大分県", "宮崎県", "鹿児島県", "沖縄県",
)

# 都道府県名を含まない地域値を救済する。一意に決まる市名だけを登録する。
MUNICIPALITY_PREFECTURES = {
    "金沢市": "石川県",
    "七尾市": "石川県",
    "白山市": "石川県",
    "小松市": "石川県",
    "加賀市": "石川県",
    "野々市市": "石川県",
    "輪島市": "石川県",
    "珠洲市": "石川県",
    "羽咋市": "石川県",
    "富山市": "富山県",
    "高岡市": "富山県",
    "射水市": "富山県",
    "黒部市": "富山県",
    "砺波市": "富山県",
    "魚津市": "富山県",
    "氷見市": "富山県",
    "南砺市": "富山県",
    "福井市": "福井県",
    "鯖江市": "福井県",
    "越前市": "福井県",
    "坂井市": "福井県",
    "敦賀市": "福井県",
    "大野市": "福井県",
    "勝山市": "福井県",
    "小浜市": "福井県",
}


def extract_prefecture(value: Any) -> str:
    """地域・住所文字列から、一意に確定できる都道府県名を返す。"""
    text = str(value or "").strip()
    if not text:
        return ""

    explicit_matches = {prefecture for prefecture in PREFECTURES if prefecture in text}
    if len(explicit_matches) == 1:
        return next(iter(explicit_matches))
    if len(explicit_matches) > 1:
        return ""

    inferred_matches = {
        prefecture
        for municipality, prefecture in MUNICIPALITY_PREFECTURES.items()
        if municipality in text
    }
    if len(inferred_matches) == 1:
        return next(iter(inferred_matches))
    return ""