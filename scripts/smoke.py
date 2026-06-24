from dotenv import load_dotenv
from google import genai

load_dotenv()
client = genai.Client()
resp = client.models.generate_content(model="gemini-3.5-flash", contents="只回复:通")
print(resp.text)