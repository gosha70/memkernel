import json


def write(record: dict) -> str:
    return json.dumps(record, sort_keys=True)
