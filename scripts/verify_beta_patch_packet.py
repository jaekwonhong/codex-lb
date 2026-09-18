#!/usr/bin/env python3
"""Verify the local Beta patch packet keeps source-scoped provider boundaries correct.

This is intentionally stdlib-only so it can run on a freshly rebased candidate
before project dependencies are installed. It validates semantics that were
historically split across the DGX donor packet and the later Responses
integration: registry absence alone is never source ownership, while real
assigned-source ownership and dangling source scope remain fail-closed.
"""

from __future__ import annotations

import argparse
import ast
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

CONTRACT = "beta_patch_packet_source_scope_v2"


class VerificationError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class VerificationResult:
    root: str
    contract: str = CONTRACT
    responses_guard_call_count: int = 0
    websocket_source_guard_call_count: int = 0
    dgx_responses_payload_call_count: int = 0

    def as_dict(self) -> dict[str, object]:
        return {
            "status": "ok",
            "contract": self.contract,
            "root": self.root,
            "responses_guard_call_count": self.responses_guard_call_count,
            "websocket_source_guard_call_count": self.websocket_source_guard_call_count,
            "dgx_responses_payload_call_count": self.dgx_responses_payload_call_count,
        }


def _parse(root: Path, relative: str) -> ast.Module:
    path = root / relative
    if not path.is_file():
        raise VerificationError(f"required packet file is missing: {relative}")
    try:
        return ast.parse(path.read_text(encoding="utf-8"), filename=relative)
    except (OSError, SyntaxError, UnicodeError) as exc:
        raise VerificationError(f"cannot parse required packet file: {relative}") from exc


def _find_top_level_function(module: ast.Module, name: str) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    for node in module.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    return None


def _find_async_method(module: ast.Module, class_name: str, method_name: str) -> ast.AsyncFunctionDef | None:
    for node in module.body:
        if not isinstance(node, ast.ClassDef) or node.name != class_name:
            continue
        for member in node.body:
            if isinstance(member, ast.AsyncFunctionDef) and member.name == method_name:
                return member
    return None


def _call_name(node: ast.Call) -> str | None:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


def _calls(node: ast.AST, name: str) -> list[ast.Call]:
    return [child for child in ast.walk(node) if isinstance(child, ast.Call) and _call_name(child) == name]


def _awaits_call(node: ast.AST, name: str) -> bool:
    return any(
        isinstance(child, ast.Await) and isinstance(child.value, ast.Call) and _call_name(child.value) == name
        for child in ast.walk(node)
    )


def _returns_literal_true(node: ast.AST) -> bool:
    return any(
        isinstance(child, ast.Return) and isinstance(child.value, ast.Constant) and child.value.value is True
        for child in ast.walk(node)
    )


def _has_empty_assignment_fail_closed(function: ast.AsyncFunctionDef) -> bool:
    for node in ast.walk(function):
        if not isinstance(node, ast.If):
            continue
        if not (
            isinstance(node.test, ast.UnaryOp)
            and isinstance(node.test.op, ast.Not)
            and isinstance(node.test.operand, ast.Name)
            and node.test.operand.id == "assigned_source_ids"
        ):
            continue
        if _returns_literal_true(node):
            return True
    return False


def _parent_map(module: ast.Module) -> dict[ast.AST, ast.AST]:
    parents: dict[ast.AST, ast.AST] = {}
    for parent in ast.walk(module):
        for child in ast.iter_child_nodes(parent):
            parents[child] = parent
    return parents


def _nearest_if_test(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> ast.If | None:
    current: ast.AST | None = node
    while current is not None:
        parent = parents.get(current)
        if isinstance(parent, ast.If) and current is parent.test:
            return parent
        current = parent
    return None


def _has_negated_name(node: ast.AST, name: str) -> bool:
    return any(
        isinstance(child, ast.UnaryOp)
        and isinstance(child.op, ast.Not)
        and isinstance(child.operand, ast.Name)
        and child.operand.id == name
        for child in ast.walk(node)
    )


def _iter_guard_calls(module: ast.Module) -> Iterable[ast.Call]:
    for node in ast.walk(module):
        if isinstance(node, ast.Call) and _call_name(node) == "source_scoped_model_requires_source":
            yield node


def _iter_calls(module: ast.Module, name: str) -> Iterable[ast.Call]:
    for node in ast.walk(module):
        if isinstance(node, ast.Call) and _call_name(node) == name:
            yield node


def verify(root: Path) -> VerificationResult:
    root = root.resolve()
    repository = _parse(root, "app/modules/model_sources/repository.py")
    selection = _parse(root, "app/modules/model_sources/selection.py")
    forwarding = _parse(root, "app/modules/model_sources/forwarding.py")
    proxy_api = _parse(root, "app/modules/proxy/api.py")
    websocket_mixin = _parse(root, "app/modules/proxy/_service/websocket/mixin.py")

    ownership_method = _find_async_method(repository, "ModelSourcesRepository", "assigned_source_has_model")
    if ownership_method is None:
        raise VerificationError(
            "model-source repository lacks async assigned_source_has_model(); registry absence cannot prove ownership"
        )

    helper = _find_top_level_function(selection, "source_scoped_model_requires_source")
    if helper is None:
        raise VerificationError("source_scoped_model_requires_source() is missing")
    if not isinstance(helper, ast.AsyncFunctionDef):
        raise VerificationError(
            "source_scoped_model_requires_source() must be async so it can prove assigned-source ownership"
        )
    if not _calls(helper, "allowed_source_ids_for_api_key"):
        raise VerificationError("source-only guard does not bind ownership to the presented API key's assigned sources")
    if not _awaits_call(helper, "assigned_source_has_model"):
        raise VerificationError("source-only guard does not positively query assigned-source model ownership")
    if not _has_empty_assignment_fail_closed(helper):
        raise VerificationError("source-only guard lost the dangling empty-assignment fail-closed boundary")

    websocket_helper = _find_top_level_function(selection, "responses_model_is_source_owned")
    if not isinstance(websocket_helper, ast.AsyncFunctionDef):
        raise VerificationError("responses_model_is_source_owned() must remain an async WebSocket provider guard")
    if not _awaits_call(websocket_helper, "source_scoped_model_requires_source"):
        raise VerificationError(
            "WebSocket provider guard does not preserve the dangling source-scope fail-closed boundary"
        )

    parents = _parent_map(proxy_api)
    guard_calls = list(_iter_guard_calls(proxy_api))
    if len(guard_calls) < 2:
        raise VerificationError("both Responses HTTP surfaces must enforce the source-only provider boundary")

    for call in guard_calls:
        parent = parents.get(call)
        if not isinstance(parent, ast.Await):
            raise VerificationError("Responses source-only guard must await ownership-aware source resolution")
        guard_if = _nearest_if_test(parent, parents)
        if guard_if is None:
            raise VerificationError("Responses source-only guard must be evaluated directly in an if-condition")
        if not _has_negated_name(guard_if.test, "source_route_excluded"):
            raise VerificationError("Responses source-only guard must preserve structural source-route exclusions")
        if not _has_negated_name(guard_if.test, "continuity_suppressed"):
            raise VerificationError(
                "Responses source-only guard must preserve continuity-suppressed subscription ownership"
            )

    websocket_guard_calls = list(_iter_calls(websocket_mixin, "responses_model_is_source_owned"))
    if len(websocket_guard_calls) < 2:
        raise VerificationError(
            "WebSocket source-owned provider boundary must be enforced at both request and connect resolution"
        )
    websocket_parents = _parent_map(websocket_mixin)
    for call in websocket_guard_calls:
        if not isinstance(websocket_parents.get(call), ast.Await):
            raise VerificationError("WebSocket source-owned provider guard must await source resolution")

    dgx_payload_helper = _find_top_level_function(forwarding, "_dgx_responses_payload")
    if dgx_payload_helper is None:
        raise VerificationError("DGX Responses encrypted-reasoning scrub helper is missing")
    helper_literals = {
        child.value
        for child in ast.walk(dgx_payload_helper)
        if isinstance(child, ast.Constant) and isinstance(child.value, str)
    }
    for required_literal in (
        "src_69bc4887d69740979f6a0beaca37eefb",
        "qwen3.8-flash-next",
        "encrypted_content",
    ):
        if required_literal not in helper_literals:
            raise VerificationError(
                f"DGX Responses payload scrub lost required qualified marker: {required_literal}"
            )
    dgx_call_count = 0
    for function_name in ("forward_responses", "stream_responses"):
        forwarder = _find_top_level_function(forwarding, function_name)
        if not isinstance(forwarder, ast.AsyncFunctionDef):
            raise VerificationError(f"DGX Responses qualification requires async {function_name}()")
        calls = _calls(forwarder, "_dgx_responses_payload")
        if not calls:
            raise VerificationError(f"{function_name}() does not apply the qualified DGX Responses payload scrub")
        dgx_call_count += len(calls)

    return VerificationResult(
        root=str(root),
        responses_guard_call_count=len(guard_calls),
        websocket_source_guard_call_count=len(websocket_guard_calls),
        dgx_responses_payload_call_count=dgx_call_count,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".", help="candidate repository root")
    parser.add_argument("--json", action="store_true", help="emit machine-readable success output")
    args = parser.parse_args()

    try:
        result = verify(Path(args.root))
    except VerificationError as exc:
        print(f"beta patch packet verification failed: {exc}")
        return 1

    if args.json:
        print(json.dumps(result.as_dict(), sort_keys=True))
    else:
        print(
            f"beta patch packet verification passed: contract={result.contract} "
            f"responses_guard_call_count={result.responses_guard_call_count} "
            f"websocket_source_guard_call_count={result.websocket_source_guard_call_count} "
            f"dgx_responses_payload_call_count={result.dgx_responses_payload_call_count}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
