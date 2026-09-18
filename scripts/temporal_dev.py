"""Start Temporal's official local dev server without Docker (SDK downloads its CLI)."""

import asyncio
from pathlib import Path
from temporalio.testing import WorkflowEnvironment


async def main():
    directory = Path(__file__).resolve().parents[1] / ".local/temporal"
    directory.mkdir(parents=True, exist_ok=True)
    environment = await WorkflowEnvironment.start_local(
        port=7233,
        ui=True,
        ui_port=8233,
        download_dest_dir=str(directory),
        dev_server_database_filename=str(directory / "temporal.db"),
    )
    print("Temporal running at 127.0.0.1:7233; UI http://127.0.0.1:8233", flush=True)
    try:
        await asyncio.Event().wait()
    finally:
        await environment.shutdown()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
