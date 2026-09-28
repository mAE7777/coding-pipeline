from fastapi import FastAPI
import httpx

app = FastAPI()


@app.get("/health")
def health():
    return {"ok": True}


def summarize(text):
    return httpx.post("https://api.openai.com/v1/responses", json={"input": text})
