from flask import jsonify

"""
[API 표준 응답 생성 함수]

  :param data: 클라이언트에 전달할 본문 데이터. 
    - 단일 값, 리스트, 또는 여러 필드를 포함한 딕셔너리가 가능합니다.
    - 데이터가 여러 개일 경우 {'key1': value1, 'key2': value2} 형태로 구성하세요.
  :param ok: 요청 처리 성공 여부
  :param message: 사용자에게 보여줄 안내 문구 또는 에러 메시지
  :param status: HTTP 상태 코드

  [ 사용 예시 ]
  1. 데이터가 하나일 때: api_res(data="Success")
  2. 데이터가 여러 개일 때: 
    send_res(data={
      'user': user_info,
      'settings': user_settings,
      'token': access_token
    })
"""
def send_res(data=None, ok=True, message='', status=200):
  return jsonify({
    'ok' : ok,
    'message' : message,
    'data' : data
  }), status