"""Writer Agent: premise + story bible + cast -> validated episode script."""

from __future__ import annotations

import json

from pydantic import ValidationError

from novelos.libs.models.adapters import ProviderError
from novelos.libs.models.schemas import Script

SYSTEM = (
    "You are the Writer Agent of a narrated video studio. Return ONLY JSON: "
    '{"title": str, "aspect_ratio": "16:9"|"9:16", "scenes": [{"summary": str, "shots": [{"characters": [code], "location": code, '
    '"camera": str, "emotion": str, "description": str, "lines": [{"speaker": str, "text": str, '
    '"kind": "narration"|"dialogue"|"sfx", "emotion_tone": str}]}]}]}. '
    "Write 10 to 15 shots in total. Each shot is one visual beat with spoken narration or dialogue meant to be "
    "read aloud by text-to-speech: write lines with a natural spoken rhythm and clear pauses, not comic-book "
    "balloon text. Use ONLY the character and location codes you are given. "
    "Keep each narration line under 400 characters. Respect injuries and story state of each character."
)


def check_semantics(script: Script, char_codes: set[str], loc_codes: set[str], names: set[str]) -> list[str]:
    problems = []
    n = 0
    for scene in script.scenes:
        for p in scene.shots:
            n += 1
            problems += [f"shot {n}: unknown character {c}" for c in p.characters if c not in char_codes]
            if p.location not in loc_codes:
                problems.append(f"shot {n}: unknown location {p.location}")
    return problems


def write_script(text, premise: str, bible: dict, characters: list[dict], locations: list[dict], retries: int = 2) -> Script:
    payload = {"premise": premise, "bible": bible, "characters": characters, "locations": locations}
    user = "Write the episode.\n" + json.dumps(payload, ensure_ascii=False)
    char_codes, loc_codes = {c["code"] for c in characters}, {x["code"] for x in locations}
    names = {c["name"] for c in characters}
    last = ""
    for _ in range(retries + 1):
        raw = text.complete_json("script", SYSTEM, user + (f"\nFix these problems from your last attempt: {last}" if last else ""), payload)
        try:
            script = Script.model_validate(raw)
        except ValidationError as e:
            last = str(e)[:400]
            continue
        problems = check_semantics(script, char_codes, loc_codes, names)
        if not problems:
            return script
        last = "; ".join(problems[:6])
    raise ProviderError(f"Writer could not produce a valid script: {last}")
