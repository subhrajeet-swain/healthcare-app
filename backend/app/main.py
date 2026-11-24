from fastapi import FastAPI

app = FastAPI(title="healthcare-app")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
