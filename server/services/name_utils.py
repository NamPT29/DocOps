import re
import unicodedata

def _normalize_name(name: str | None) -> str:
    if not name:
        return ""
    name = name.replace('đ', 'd').replace('Đ', 'd')
    n = unicodedata.normalize('NFD', name).encode('ascii', 'ignore').decode('utf-8')
    return re.sub(r'[\s_\-]', '', n).lower()
