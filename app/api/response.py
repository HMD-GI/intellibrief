from fastapi.responses import JSONResponse


def ok(data=None, message: str = "success", code: int = 0) -> dict:
    """统一成功响应格式。"""

    return {
        "success": True,
        "code": code,
        "message": message,
        "data": data if data is not None else {},
    }


def fail(message: str, code: int = 1, data=None) -> dict:
    """统一失败响应格式。"""

    return {
        "success": False,
        "code": code,
        "message": message,
        "data": data if data is not None else {},
    }


def fail_response(
    message: str,
    *,
    code: int = 1,
    status_code: int = 400,
    data=None,
) -> JSONResponse:
    """统一失败 HTTP 响应，便于路由和异常处理复用。"""

    return JSONResponse(status_code=status_code, content=fail(message=message, code=code, data=data))
