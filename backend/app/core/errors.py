# -*- coding: utf-8 -*-
"""Единый формат ошибок по docs/08 §1:

    { "error": { "code": "...", "message": "...", "details": {} } }
"""
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

# Соответствие HTTP-статуса машиночитаемому коду ошибки
_CODE_BY_STATUS = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    409: "conflict",
    422: "validation_error",
    500: "internal_error",
}


class AppError(HTTPException):
    """Доменная ошибка с явным кодом и деталями."""

    def __init__(self, status_code: int, code: str, message: str, details: dict | None = None):
        super().__init__(status_code=status_code, detail=message)
        self.code = code
        self.message = message
        self.details = details or {}


def _payload(code: str, message: str, details: dict | None = None) -> dict:
    return {"error": {"code": code, "message": message, "details": details or {}}}


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError):
        return JSONResponse(status_code=exc.status_code,
                            content=_payload(exc.code, exc.message, exc.details))

    @app.exception_handler(HTTPException)
    async def _http_error(_: Request, exc: HTTPException):
        code = _CODE_BY_STATUS.get(exc.status_code, "error")
        return JSONResponse(status_code=exc.status_code,
                            content=_payload(code, str(exc.detail)),
                            headers=getattr(exc, "headers", None))

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError):
        # 422 по docs/08: детали валидации отдаём как есть, но без сырых значений
        details = {"fields": [
            {"loc": list(e.get("loc", [])), "msg": e.get("msg", ""), "type": e.get("type", "")}
            for e in exc.errors()
        ]}
        return JSONResponse(status_code=422,
                            content=_payload("validation_error", "Ошибка валидации запроса", details))
