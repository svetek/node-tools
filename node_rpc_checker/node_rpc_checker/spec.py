"""Fail-closed loader for the constructs in the bundled Lava specifications."""

import copy
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Rule:
    key: str
    mode: str
    directive: dict
    value: dict


def validate_parser(pd: dict[str, Any]) -> None:
    if pd.get("parsers"):
        for p in pd["parsers"]:
            if p.get("parse_type") != "RESULT" or not re.fullmatch(
                r"(\.(?:[A-Za-z_][A-Za-z_0-9]*|\[(?:0|[1-9][0-9]{0,8})\]))+",
                p.get("parse_path", ""),
            ):
                raise ValueError("unsupported alternative parser")
        return
    p = pd.get("result_parsing", {})
    if p.get("parser_func") not in ("PARSE_BY_ARG", "PARSE_CANONICAL"):
        raise ValueError("unsupported result parser")
    args = p.get("parser_arg", [])
    if not args or args[0] != "0" or (p["parser_func"] == "PARSE_BY_ARG" and args != ["0"]):
        raise ValueError("unsupported parser arguments")
    if p.get("encoding") not in (None, "", "hex", "base64"):
        raise ValueError("unsupported encoding")


def validate_template(directive: dict[str, Any]) -> None:
    template = directive.get("function_template")
    if not isinstance(template, str) or not template:
        raise ValueError("missing or invalid function template")
    placeholders = re.findall(r"%[dx]", template)
    if "%" in re.sub(r"%[dx]", "", template):
        raise ValueError("unsupported function template placeholder")
    if directive.get("function_tag") == "GET_BLOCK_BY_NUM":
        if len(placeholders) != 1:
            raise ValueError("GET_BLOCK_BY_NUM requires exactly one %d or %x placeholder")
        # Exercise the same formatting operation as Engine.verify at startup.
        rendered = template % 1
    else:
        if placeholders:
            raise ValueError("placeholders are only supported for GET_BLOCK_BY_NUM")
        rendered = template
    try:
        request = json.loads(rendered)
    except ValueError:
        raise ValueError("invalid JSON in function template") from None
    if (
        not isinstance(request, dict)
        or request.get("jsonrpc") != "2.0"
        or not isinstance(request.get("method"), str)
        or "id" not in request
    ):
        raise ValueError("invalid function request template")


def merge_collection(collections, key, child):
    previous = collections.get(key, {})
    merged = copy.deepcopy(previous)
    for field, value in child.items():
        if field in ("parse_directives", "verifications"):
            identity = "function_tag" if field == "parse_directives" else "name"
            entries = {
                entry[identity]: copy.deepcopy(entry) for entry in previous.get(field, []) or []
            }
            for entry in value or []:
                entries[entry[identity]] = {
                    **entries.get(entry[identity], {}),
                    **copy.deepcopy(entry),
                }
            merged[field] = list(entries.values())
        elif value is not None:
            merged[field] = copy.deepcopy(value)
    collections[key] = merged


def resolve_spec(specs, index, visiting=()):
    if index in visiting:
        raise ValueError("cyclic spec imports")
    if index not in specs:
        raise ValueError("missing imported spec: " + index)
    spec = specs[index]
    if not spec.get("enabled"):
        raise ValueError("disabled spec: " + index)
    collections: dict[tuple[str, ...], dict[str, Any]] = {}
    for parent in spec.get("imports", []) or []:
        for key, collection in resolve_spec(specs, parent, visiting + (index,)).items():
            merge_collection(collections, key, collection)
    for collection in spec["api_collections"]:
        data = collection["collection_data"]
        key = tuple(
            data.get(field, "") for field in ("api_interface", "type", "internal_path", "add_on")
        )
        merge_collection(collections, key, collection)
    return collections


class Spec:
    def __init__(self, chain_id: str, directory: Path | str | None = None):
        directory = directory or Path(__file__).with_name("specs")
        specs, self.hashes = {}, {}
        for path in sorted(Path(directory).glob("*.json")):
            raw = path.read_bytes()
            self.hashes[path.name] = hashlib.sha256(raw).hexdigest()
            for s in json.loads(raw)["proposal"]["specs"]:
                if s["index"] in specs:
                    raise ValueError("duplicate chain ID")
                specs[s["index"]] = s
        self.collections = resolve_spec(specs, chain_id)
        self.base = self.collections[("jsonrpc", "POST", "", "")]
        self.directives = {d["function_tag"]: d for d in self.base.get("parse_directives", [])}
        for tag in ("GET_BLOCKNUM", "GET_BLOCK_BY_NUM"):
            validate_parser(self.directives[tag])
            validate_template(self.directives[tag])
        chain_rule = next((r for r in self.rules(()) if r.key == "chain-id"), None)
        if chain_rule is None:
            raise ValueError("missing required chain-id verification: " + chain_id)
        self.chain_rule = chain_rule

    def rules(self, addons: tuple[str, ...] | list[str]) -> list[Rule]:
        available = {k[3] for k, c in self.collections.items() if c.get("enabled")}
        if set(addons) - available:
            raise ValueError("unknown or disabled addon")
        rules: list[Rule] = []
        for (interface, method, path, addon), c in self.collections.items():
            if addon and addon not in addons:
                continue
            if not c.get("enabled"):
                continue
            if (interface, method, path) != ("jsonrpc", "POST", ""):
                raise ValueError("unsupported selected API collection")
            for v in c.get("verifications", []) or []:
                pd = v.get("parse_directive", {})
                tag = pd.get("function_tag")
                if tag not in ("VERIFICATION", "GET_BLOCK_BY_NUM", "GET_EARLIEST_BLOCK"):
                    raise ValueError("unsupported verification tag")
                directive = {**self.directives.get(tag, {}), **pd}
                validate_template(directive)
                validate_parser(directive)
                for value in v.get("values", []):
                    if set(value) - {"expected_value", "latest_distance", "extension"}:
                        raise ValueError("unsupported verification value")
                    extension = value.get("extension", "")
                    if extension not in ("", "archive"):
                        raise ValueError("unsupported extension")
                    if "latest_distance" in value and (
                        type(value["latest_distance"]) is not int or value["latest_distance"] <= 0
                    ):
                        raise ValueError("invalid latest_distance")
                    if not value.get("latest_distance") and "expected_value" not in value:
                        raise ValueError("verification has no condition")
                    mode = (
                        "archive"
                        if extension
                        else ("pruning" if value.get("latest_distance") else "readyz")
                    )
                    key = (
                        (addon + ":" if addon else "")
                        + v["name"]
                        + ("@archive" if extension else "")
                    )
                    if any(r.key == key for r in rules):
                        raise ValueError("duplicate verification key")
                    rules.append(Rule(key, mode, directive, value))
        return rules
