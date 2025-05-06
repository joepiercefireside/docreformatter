import requests
API_KEY = "sk-67nIiA7-e2rxldl5qaOPRK-BvJ8O2lsJLhdeVtRZ_cT3BlbkFJSqLX3tdehY3tObgIyGgPOuIIAkn7kM4avkiO1vRTwA"
headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
payload = {"model": "gpt-3.5-turbo", "messages": [{"role": "user", "content": "Test"}]}
response = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload)
print(response.status_code, response.text)