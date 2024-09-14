from copy import deepcopy


def check_inline_data(inline_data: dict) -> tuple[bool, list[str] | None]:
    mime_type = inline_data.pop('mime_type')
    if not isinstance(mime_type, str):
        return False, ['不正なmime_typeの形式']  # 不正なMIME_TYPEの形式

    data = inline_data.pop('data')
    if not isinstance(data, str):
        return False, ['不正なdataの形式']  # 不正なデータの形式

    if inline_data:
        return False, ['inline_dataに不正な値が存在']  # 不正な値が存在

    return True, None


def check_part(part: dict) -> tuple[bool, list[str] | None]:
    if 'inline_data' in part:
        inline_data = part.pop('inline_data')
        r, msg = check_inline_data(inline_data)
        if not r:
            msg.append('不正なinline_data')
            return False, msg

    if 'text' in part:
        text = part.pop('text')
        if not isinstance(text, str):
            return False, ['不正なtextの形式']

    if part:
        return False, ['partに不正なデータが存在']

    return True, None


def check_history(data: list[dict]) -> tuple[bool, list[str] | None]:
    data = deepcopy(data)
    for m in data:
        parts = m.pop('parts')
        for p in parts:
            r, msg = check_part(p)
            if not r:
                msg.append('不正なpartの形式')
                return False, msg

        role = m.pop('role')
        if not isinstance(role, str):
            return False, ['不正なroleの形式']

        if m:
            return False, ['不正なメッセージの形式']

    return True, None
