from __future__ import annotations

import argparse
import asyncio
from collections.abc import Sequence


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the standalone Workspace Member Controller.")
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Validate configuration, persistence schema, Companion and exact OpenCodex bindings, then exit.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    from app.modules.workspace_member_controller.standalone_runtime import ControllerStandaloneRuntime
    from app.modules.workspace_member_controller.standalone_settings import StandaloneSettings

    settings = StandaloneSettings()
    if args.validate:
        async def validate() -> None:
            runtime = ControllerStandaloneRuntime.build(settings)
            try:
                report = await runtime.startup()
                print(
                    "workspace-member-controller validation passed: "
                    f"workspaces={report.workspace_count} bindings={report.binding_count} "
                    f"opencodex_accounts={report.opencodex_account_count}"
                )
            finally:
                await runtime.close()

        asyncio.run(validate())
        return

    import uvicorn

    uvicorn.run(
        "app.modules.workspace_member_controller.standalone_app:create_standalone_app_from_env",
        factory=True,
        host=settings.host,
        port=settings.port,
        workers=1,
        proxy_headers=False,
    )
