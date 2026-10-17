import requests, sys
from api_test_support import api_auth_headers

file_id = '1FAuCPcnKgSKo_45efeeLko9oDE4uV-5H'
try:
    token_resp = requests.get(
        'http://localhost:8000/api/auth/token',
        headers=api_auth_headers(),
        timeout=5,
    )
    token_resp.raise_for_status()
    token = token_resp.json().get('access_token')
    if not token:
        print('NO_TOKEN', token_resp.text)
        sys.exit(2)
    headers = {'Authorization': f'Bearer {token}'}
    r = requests.get(f'https://www.googleapis.com/drive/v3/files/{file_id}', headers=headers, params={'fields':'id,name,mimeType,trashed,webViewLink'}, timeout=10)
    print('STATUS', r.status_code)
    print(r.text)
except Exception as e:
    print('ERROR', e)
    sys.exit(3)
