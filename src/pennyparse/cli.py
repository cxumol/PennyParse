import typer
from typing_extensions import Annotated

app = typer.Typer(name="pennyparse", help="PennyParse CLI - Agentic Document Parser")


@app.command()
def init(name: Annotated[str, typer.Argument()] = "World"):
    """Initialize """
    pass


@app.command()
def serve(port: Annotated[int, typer.Option()] = 8000):
    """Start the web server."""
    pass


if __name__ == "__main__":
    app()
