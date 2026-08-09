from fastapi import FastAPI

app = FastAPI(title="WPL Backend")


@app.get("/health")
def health_check():
    return {"status": "ok"}