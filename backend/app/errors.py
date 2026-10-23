import logging

from flask import jsonify
from werkzeug.exceptions import HTTPException

log = logging.getLogger(__name__)


class ApiError(Exception):
    status = 400
    code = "bad_request"

    def __init__(self, message: str, code: str | None = None, status: int | None = None, fields: dict | None = None):
        super().__init__(message)
        self.message = message
        if code:
            self.code = code
        if status:
            self.status = status
        self.fields = fields or {}


class ValidationError(ApiError):
    status = 422
    code = "validation_error"


class NotFound(ApiError):
    status = 404
    code = "not_found"

    def __init__(self, message: str = "Not found"):
        super().__init__(message)


class Unauthorized(ApiError):
    status = 401
    code = "unauthorized"

    def __init__(self, message: str = "Sign in required"):
        super().__init__(message)


class Forbidden(ApiError):
    status = 403
    code = "forbidden"

    def __init__(self, message: str = "You do not have permission to do that"):
        super().__init__(message)


class Conflict(ApiError):
    status = 409
    code = "conflict"


def error_body(code: str, message: str, fields: dict | None = None):
    body = {"error": {"code": code, "message": message}}
    if fields:
        body["error"]["fields"] = fields
    return body


def register_error_handlers(app):
    from .extensions import db

    @app.errorhandler(ApiError)
    def handle_api_error(err: ApiError):
        db.session.rollback()  # never let a failed request's partial work be committed later
        return jsonify(error_body(err.code, err.message, err.fields)), err.status

    @app.errorhandler(HTTPException)
    def handle_http(err: HTTPException):
        db.session.rollback()
        code = {429: "rate_limited", 404: "not_found", 405: "method_not_allowed"}.get(err.code, "http_error")
        message = "Too many requests. Please wait and try again." if err.code == 429 else (err.description or err.name)
        return jsonify(error_body(code, message)), err.code

    @app.errorhandler(Exception)
    def handle_unexpected(err: Exception):
        db.session.rollback()
        log.exception("Unhandled error")
        return jsonify(error_body("server_error", "Something went wrong. Please try again.")), 500
