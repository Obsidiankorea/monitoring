from app import geocode


def test_address_cleans_wiki_fields():
    a = geocode.address
    assert a({"시군": "창원시", "지구명": "의창구", "읍면동": "북면", "리": "무동리", "지번": "산83"}) == "경상남도 창원시 의창구 북면 무동리 산83"
    assert a({"시군": "하동군", "지구명": "횡천지구", "읍면동": "횡천면", "리": "횡천리", "지번": "1044"}) == "경상남도 하동군 횡천면 횡천리 1044"
    assert a({"시군": "밀양시", "지구명": "", "읍면동": "삼문동", "리": "–", "지번": "7941"}) == "경상남도 밀양시 삼문동 7941"
    assert a({"시군": "고성군", "지구명": "", "읍면동": "삼산면", "리": "미룡리", "지번": "산58번지"}) == "경상남도 고성군 삼산면 미룡리 산58"


def test_parse_vworld_reply():
    p = geocode.parse
    assert p({"response": {"status": "OK", "result": {"point": {"x": "128.6", "y": "35.3"}}}}) == (35.3, 128.6)
    assert p({"response": {"status": "NOT_FOUND"}}) == "NOT_FOUND"
    assert p({"response": {"status": "ERROR", "error": {"text": "등록되지 않은 인증키입니다."}}}) == "등록되지 않은 인증키입니다."
    assert p({"response": {"status": "OK", "result": {"point": {"x": "126.9", "y": "37.5"}}}}).startswith("경남 밖")
    assert geocode._key_error("등록되지 않은 인증키입니다.") and not geocode._key_error("NOT_FOUND")
