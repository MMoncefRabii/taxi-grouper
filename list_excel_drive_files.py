import requests

print('Fetching token from backend...')
resp = requests.get('http://localhost:8000/api/auth/token')
resp.raise_for_status()
token = resp.json().get('access_token')
if not token:
    raise SystemExit('No access token')
headers = {'Authorization': f'Bearer {token}'}
q = "mimeType='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' or mimeType='application/vnd.ms-excel'"
print('Querying Drive for Office Excel files...')
resp = requests.get('https://www.googleapis.com/drive/v3/files', headers=headers, params={'q': q, 'spaces': 'drive', 'fields': 'files(id,name,mimeType)', 'pageSize': 50}, timeout=20)
print('Status:', resp.status_code)
print(resp.text)
