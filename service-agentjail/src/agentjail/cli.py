import typer


def main(
    host: str = typer.Option("0.0.0.0", help="Listen address"),
    port: int = typer.Option(8000, help="Listen port"),
) -> None:
    """Start the agentjail server (MCP + REST API)."""
    from agentjail.server import run_server

    run_server(host=host, port=port)


def cli() -> None:
    typer.run(main)
