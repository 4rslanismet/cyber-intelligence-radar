"""profile_extraction JSON Schema: TEK KAYNAK, İKİ TÜKETİCİ.

Profile YAML'larındaki (profiles/saci_*.yaml) `extraction_schema`
alanı GERÇEK bir JSON Schema'dır (jsonschema.Draft7Validator ile
doğrulanabilir). Bu modül onu iki farklı amaç için kullanır:

1. to_prompt_text(schema)  -> Gemini'ye gönderilecek okunur, yorum satırlı
   JSON şablonu (bkz. src/llm/paper_analyst.py).
2. validate(data, schema)  -> Gemini yanıtı geldikten SONRA runtime'da
   doğrulama (bkz. paper_analyst.analyze_paper).

Aynı alanları Python'da ikinci kez elle tanımlamıyoruz - schema drift riski
yok: YAML'da bir alan eklenir/değişirse hem prompt hem validator otomatik
güncellenir.
"""
from __future__ import annotations

from typing import Any

import jsonschema


def _type_repr(prop: dict[str, Any]) -> str:
    t = prop.get("type")
    if isinstance(t, list):
        return " | ".join(t)
    return t or "any"


def _render_value(prop: dict[str, Any]) -> str:
    """Bir property'nin DEĞER kısmının prompt metnini üretir (virgül/yorum
    çağıran tarafından eklenir)."""
    ptype = prop.get("type")
    types = ptype if isinstance(ptype, list) else [ptype]

    if "object" in types and prop.get("properties"):
        sub = prop["properties"]
        keys = list(sub.keys())
        sub_lines = []
        for i, k in enumerate(keys):
            v = sub[k]
            comma = "," if i < len(keys) - 1 else ""
            desc = v.get("description", "")
            comment = f"  // {desc.strip()}" if desc else ""
            sub_lines.append(f'    "{k}": {_type_repr(v)}{comma}{comment}')
        return "{\n" + "\n".join(sub_lines) + "\n  }"

    if "array" in types:
        item_type = (prop.get("items") or {}).get("type", "string")
        return f"[{item_type}]"

    if prop.get("enum") is not None:
        return " | ".join("null" if e is None else str(e) for e in prop["enum"])

    return _type_repr(prop)


def to_prompt_text(schema: dict[str, Any]) -> str:
    """JSON Schema'yı Gemini sistem prompt'una eklenecek okunur bir JSON
    şablonuna çevirir. `schema` bir ResearchProfile.extraction_schema'sı
    (profiles.py) - yani her zaman `type: object` + `properties` içerir."""
    props = schema.get("properties", {})
    keys = list(props.keys())
    lines = []
    for i, name in enumerate(keys):
        prop = props[name]
        comma = "," if i < len(keys) - 1 else ""
        desc = prop.get("description", "")
        comment = f"  // {desc.strip()}" if desc and not prop.get("properties") else ""
        lines.append(f'  "{name}": {_render_value(prop)}{comma}{comment}')
    return "{\n" + "\n".join(lines) + "\n}"


def validate(data: Any, schema: dict[str, Any]) -> tuple[bool, list[str]]:
    """Döner: (geçerli_mi, hata_mesajları). Hata mesajları alan yolu +
    açıklama içerir (ör. "mitre_attack_used: 82 is not of type 'boolean',
    'null'") - src/llm/paper_analyst.py bunları
    analysis['profile_extraction_errors']'a yazar, sessizce yutmaz."""
    validator = jsonschema.Draft7Validator(schema)
    errors = sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path))
    if not errors:
        return True, []
    messages = []
    for e in errors:
        path = "/".join(str(p) for p in e.absolute_path) or "<root>"
        messages.append(f"{path}: {e.message}")
    return False, messages
