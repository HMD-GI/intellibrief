def ok(data=None, message: str = "success") -> dict:  # 统一成功响应格式
    return {"code": 0, "message": message, "data": data}


def fail(message: str, code: int = 1, data=None) -> dict:  # 统一失败响应格式
    return {"code": code, "message": message, "data": data}
