"""业务输入校验；正文保留作者的空格与换行。"""

from novel_writer.domain.models import DataValidationError


def text(value, name: str, *, required: bool = False) -> str:
    if type(value) is not str:
        raise DataValidationError(f"{name} 必须是文字")
    if required and not value.strip():
        raise DataValidationError(f"{name} 不能为空")
    return value.strip() if required else value


def check_fields(values: dict, allowed: set[str]) -> None:
    if type(values) is not dict or set(values) - allowed:
        raise DataValidationError("操作含有未知字段")


def update_text(entity, values: dict, names: tuple[str, ...], *, required: tuple[str, ...] = ()) -> None:
    for name in names:
        if name in values:
            setattr(entity, name, text(values[name], name, required=name in required))


def find(items: list, identifier: str, label: str):
    text(identifier, label + "编号", required=True)
    for item in items:
        if item.id == identifier:
            return item
    raise DataValidationError(f"找不到{label}，该内容不属于当前小说")


def structured_list(value, model, label):
    if type(value) is not list or any(type(item) is not dict for item in value):
        raise DataValidationError(f"{label}必须是对象列表")
    try:
        return [model(**item) for item in value]
    except TypeError:
        raise DataValidationError(f"{label}字段缺失或含未知字段") from None


def text_list(value, label):
    if type(value) is not list or any(type(item) is not str for item in value):
        raise DataValidationError(f"{label}必须是文字列表")
    return list(value)
