"""CLI command for voice input: aw listen."""

from __future__ import annotations

from pathlib import Path

import click

from anticlaw.core.config import load_config, resolve_home


def _get_voice_config(home: Path) -> dict:
    """Load voice config section from config.yaml."""
    config = load_config(home / ".acl" / "config.yaml")
    return config.get("voice", {})


def _create_provider(voice_config: dict):
    """Create WhisperInputProvider with graceful import error."""
    try:
        from anticlaw.input.whisper_input import WhisperInputProvider
    except ImportError as err:
        click.echo(
            "Error: voice dependencies not installed.\n"
            "Install with: pip install anticlaw[voice]"
        )
        raise SystemExit(1) from err

    return WhisperInputProvider(voice_config)


def _do_search(query: str, home: Path) -> None:
    """Run search and display results."""
    from anticlaw.core.meta_db import MetaDB
    from anticlaw.core.search import search

    db_path = home / ".acl" / "meta.db"
    if not db_path.exists():
        click.echo("No search index found. Run 'aw reindex' first.")
        return

    db = MetaDB(db_path)
    try:
        results = search(db, query, max_results=10)
        if not results:
            click.echo("No results found.")
            return

        click.echo(f"\nFound {len(results)} result(s):\n")
        for r in results:
            proj = r.project_id or "_inbox"
            click.echo(f"  [{proj}] {r.title}")
            click.echo(f"    ID: {r.chat_id[:8]}")
            if r.snippet:
                click.echo(f"    {r.snippet}")
            click.echo()
    finally:
        db.close()


def _do_ask(query: str, home: Path) -> None:
    """Run Q&A and display answer."""
    try:
        from anticlaw.llm.ollama_client import OllamaClient
        from anticlaw.llm.qa import ask as qa_ask
    except ImportError:
        click.echo("Error: LLM dependencies not installed. Install with: pip install anticlaw[llm]")
        return

    config = load_config(home / ".acl" / "config.yaml")
    llm_config = config.get("llm", {})
    client = OllamaClient(llm_config)

    if not client.is_available():
        click.echo("Ollama is not running. Falling back to search.")
        _do_search(query, home)
        return

    click.echo(f"Asking: {query}\n")
    result = qa_ask(query, home, client=client)

    if result.error:
        click.echo(f"Error: {result.error}")
        return

    if result.answer:
        click.echo(result.answer)

    if result.sources:
        click.echo("\n--- Sources ---")
        for src in result.sources:
            project = f" ({src.project_id})" if src.project_id else ""
            click.echo(f"  {src.chat_id[:8]}: {src.title}{project}")


@click.command("listen")
@click.option(
    "--continuous", "-c",
    is_flag=True,
    help="Loop mode: keep listening after each query.",
)
@click.option(
    "--mode", "-m",
    type=click.Choice(["search", "ask"]),
    default="search",
    show_default=True,
    help="Action mode: 'search' for KB search, 'ask' for LLM Q&A.",
)
@click.option(
    "--model",
    type=click.Choice(["tiny", "base", "small", "medium"]),
    default=None,
    help="Whisper model size (overrides config).",
)
@click.option(
    "--language", "-l",
    default=None,
    help="Language code (e.g. 'ru', 'en') or 'auto' for detection.",
)
@click.option(
    "--push-to-talk",
    is_flag=True,
    help="Record while Enter held, stop on release.",
)
@click.option(
    "--home",
    type=click.Path(path_type=Path),
    default=None,
    help="Override ACL_HOME path.",
)
def listen_cmd(
    continuous: bool,
    mode: str,
    model: str | None,
    language: str | None,
    push_to_talk: bool,
    home: Path | None,
) -> None:
    """Voice input: speak a query, get results from the knowledge base.

    Records audio from microphone, transcribes with Whisper (offline),
    then searches the knowledge base or asks the LLM.

    \b
    Examples:
      aw listen                      # Single voice query → search
      aw listen --continuous         # Keep listening for queries
      aw listen --mode ask           # Voice question → LLM answer
      aw listen --model small        # Use larger Whisper model
      aw listen --language ru        # Force Russian
      aw listen --push-to-talk       # Hold Enter to record
    """
    home_path = home or resolve_home()
    voice_config = _get_voice_config(home_path)

    # CLI flags override config
    if model:
        voice_config["model"] = model
    if language:
        voice_config["language"] = language
    if push_to_talk:
        voice_config["push_to_talk"] = True

    provider = _create_provider(voice_config)

    if not provider.is_available():
        click.echo(
            "Error: voice dependencies not available.\n"
            "Install with: pip install anticlaw[voice]"
        )
        return

    action = _do_ask if mode == "ask" else _do_search

    if continuous:
        click.echo("Listening (continuous mode). Press Ctrl+C to stop.\n")
        _listen_loop(provider, action, home_path)
    else:
        _listen_once(provider, action, home_path)


def _listen_once(provider, action, home: Path) -> None:
    """Single listen → transcribe → action cycle."""
    if provider._push_to_talk:
        click.echo("Press Enter to start recording, Enter again to stop...")
    else:
        click.echo("Listening... (speak now, silence stops recording)")

    query = provider.listen()
    if not query:
        click.echo("No speech detected.")
        return

    click.echo(f"Heard: {query}")
    action(query, home)


def _listen_loop(provider, action, home: Path) -> None:
    """Continuous listen loop until Ctrl+C."""
    try:
        while True:
            if provider._push_to_talk:
                click.echo("\nPress Enter to start recording, Enter again to stop...")
            else:
                click.echo("\nListening... (speak now)")

            query = provider.listen()
            if not query:
                click.echo("(no speech detected)")
                continue

            click.echo(f"Heard: {query}")
            action(query, home)
    except KeyboardInterrupt:
        click.echo("\nStopped.")
