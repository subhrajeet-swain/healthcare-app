from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class ApiError(Exception):
    """Every API error has the body {"error": <code>}."""

    def __init__(self, status: int, error: str):
        self.status, self.error = status, error


def not_found() -> ApiError:
    # "not found" and "not allowed" must look the same to the caller
    return ApiError(404, "not_found")


def unauthenticated() -> ApiError:
    return ApiError(401, "unauthenticated")


def install(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    def _handle(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse({"error": exc.error}, status_code=exc.status)
