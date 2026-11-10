"""``agentic`` command line interface."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Optional

import typer

from . import __version__

app = typer.Typer(
    name="agentic",
    help="Multi-agent software factory built on A2A, MCP, JSON Schema and OpenAPI.",
    no_args_is_help=True,
    add_completion=False,
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"agentic {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(False, "--version", "-V", callback=_version_callback, is_eager=True),
) -> None:
    """Build software with a team of interoperable agents."""


@app.command()
def build(
    idea: str = typer.Argument(..., help="The software idea, in plain language."),
    out: Optional[Path] = typer.Option(None, "--out", "-o", help="Where to write runs (default ./.agentic/runs)."),
    fix_rounds: Optional[int] = typer.Option(None, "--fix-rounds", min=0, max=10, help="Repair budget."),
    run_id: Optional[str] = typer.Option(None, "--run-id"),
    use_mcp: bool = typer.Option(True, "--mcp/--no-mcp", help="Route tool use through MCP servers."),
    as_json: bool = typer.Option(False, "--json", "-j", help="Emit the RunReport as JSON."),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
) -> None:
    """Run the full pipeline: idea -> requirements -> code -> tests -> review."""
    from .config import get_settings
    from .core.events import EventBus
    from .pipeline.orchestrator import Orchestrator

    settings = get_settings()
    events = EventBus()
    if not quiet and not as_json:
        events.add_listener(_render_event)

    orchestrator = Orchestrator(
        settings=settings, events=events, run_id=run_id, workspace=out, use_mcp=use_mcp
    )
    if not quiet and not as_json:
        typer.echo(f"agentic {__version__} | llm={settings.llm_mode} model={settings.model}")
        typer.echo(f"run dir: {orchestrator.store.run_dir}\n")

    outcome = asyncio.run(orchestrator.build(idea, max_fix_rounds=fix_rounds))

    if as_json:
        typer.echo(json.dumps(outcome.report.model_dump(mode="json"), indent=2, sort_keys=True))
    else:
        _render_summary(outcome.report)
    raise typer.Exit(0 if outcome.ok else 1)


@app.command()
def serve(
    host: Optional[str] = typer.Option(None, "--host", "-h"),
    port: Optional[int] = typer.Option(None, "--port", "-p"),
    mock: bool = typer.Option(False, "--mock", help="Force the offline mock model."),
) -> None:
    """Serve the OpenAPI orchestrator API and one A2A endpoint per agent."""
    from .config import Settings, reset_settings_cache
    from .service.app import serve as _serve

    if mock:
        reset_settings_cache()
        settings = Settings({"AGENTIC_LLM_MODE": "mock"})
    else:
        settings = None  # type: ignore[assignment]

    typer.echo("docs:  http://127.0.0.1:%s/docs" % (port or 8080))
    typer.echo("a2a:   http://127.0.0.1:%s/agents/<stage>/.well-known/agent-card.json" % (port or 8080))
    _serve(host=host, port=port, settings=settings)


@app.command("agents")
def agents_cmd(
    as_json: bool = typer.Option(False, "--json", "-j"),
) -> None:
    """List the agents, their contracts and the tools they use."""
    from .agents.registry import catalogue

    rows = catalogue()
    if as_json:
        typer.echo(json.dumps(rows, indent=2, sort_keys=True))
        return
    for row in rows:
        typer.echo(f"[{row['stage']:<9}] {row['name']:<22} -> {row['output']}")
        typer.echo(f"            {row['description']}")
        requires = ", ".join(row["requires"]) or "-"
        tools = ", ".join(row["tools"]) or "-"
        typer.echo(f"            requires: {requires} | tools: {tools}\n")


@app.command()
def schemas(
    out: Optional[Path] = typer.Option(None, "--out", help="Directory to write schemas into."),
    check: bool = typer.Option(False, "--check", help="Fail if a published schema is out of date."),
) -> None:
    """Generate or verify the JSON Schema 2020-12 artifact contracts."""
    from .core.contracts import generate_schemas, schema_dir

    target = out or schema_dir()
    if check:
        before = {p.name: p.read_text() for p in schema_dir().glob("*.schema.json")}
        written = generate_schemas()
        changed = [p.name for p in written if before.get(p.name) != p.read_text()]
        if changed:
            typer.secho(f"out of date: {', '.join(sorted(changed))}", fg=typer.colors.RED)
            raise typer.Exit(1)
        typer.secho(f"{len(written)} schemas up to date", fg=typer.colors.GREEN)
        return
    written = generate_schemas(target)
    typer.echo(f"wrote {len(written)} schema(s) to {target}")


@app.command()
def validate(
    path: Path = typer.Argument(..., exists=True, help="JSON artifact to validate."),
    as_name: str = typer.Option(..., "--as", help="Artifact name, e.g. Requirements."),
) -> None:
    """Validate a JSON file against a published artifact schema."""
    from .core.contracts import validation_errors

    payload = json.loads(path.read_text())
    errors = validation_errors(as_name, payload)
    if errors:
        typer.secho(f"{path} is NOT a valid {as_name}:", fg=typer.colors.RED)
        for error in errors:
            typer.echo(f"  - {error}")
        raise typer.Exit(1)
    typer.secho(f"{path} is a valid {as_name}", fg=typer.colors.GREEN)


@app.command()
def call(
    url: str = typer.Argument(..., help="Base URL of an A2A agent."),
    text: str = typer.Argument(..., help="Message to send."),
    timeout: float = typer.Option(300.0, "--timeout"),
) -> None:
    """Send a message to any A2A agent and print its artifacts."""
    from .a2a.client import A2AClient
    from .a2a.models import Message as A2AMessage
    from .a2a.models import Task as A2ATask

    async def run() -> None:
        client = A2AClient(url, timeout=timeout)
        card = await client.agent_card()
        typer.echo(f"{card.name} — {card.description}")
        typer.echo(f"skills: {', '.join(s.id for s in card.skills)}\n")
        result = await client.send_text(text)
        if isinstance(result, A2AMessage):
            typer.echo(result.text)
            return
        task: A2ATask = result
        typer.echo(f"task {task.id}: {task.status.state.value}")
        for artifact in task.artifacts:
            typer.echo(f"\n--- {artifact.name} ---")
            for part in artifact.parts:
                typer.echo(part.as_text()[:4000])

    asyncio.run(run())


@app.command()
def doctor() -> None:
    """Check the environment: LLM endpoint, MCP servers, tools, schemas."""
    from .config import get_settings
    from .core.contracts import schema_dir
    from .llm.openai_compat import OpenAICompatLLM

    settings = get_settings()
    ok = True

    typer.echo("agentic doctor")
    typer.echo("=" * 48)
    typer.echo(f"python           {sys.version.split()[0]}")
    typer.echo(f"llm mode         {settings.llm_mode}")
    typer.echo(f"model            {settings.model}")
    typer.echo(f"base url         {settings.base_url or '(none)'}")
    typer.echo(f"home             {settings.home}")

    schemas_present = sorted(p.name for p in schema_dir().glob("*.schema.json"))
    typer.echo(f"schemas          {len(schemas_present)} published")
    if not schemas_present:
        ok = False
        typer.secho("  ! no schemas found — run `agentic schemas`", fg=typer.colors.RED)

    if settings.llm_mode == "openai":
        health = asyncio.run(OpenAICompatLLM(settings.base_url, api_key=settings.api_key, model=settings.model).health())
        if health.get("ok"):
            typer.secho(f"llm endpoint     reachable ({health.get('endpoint')})", fg=typer.colors.GREEN)
        else:
            ok = False
            typer.secho(f"llm endpoint     UNREACHABLE: {health.get('error')}", fg=typer.colors.RED)
            typer.echo("                 set AGENTIC_LLM_BASE_URL or use AGENTIC_LLM_MODE=mock")
    else:
        typer.secho("llm endpoint     mock (offline, deterministic)", fg=typer.colors.YELLOW)

    async def probe() -> dict[str, object]:
        from .mcp.toolbox import MCPToolbox, ServerSpec

        workspace = Path(settings.home) / "doctor-workspace"
        async with MCPToolbox([ServerSpec.workspace(workspace), ServerSpec.sandbox(workspace)]) as toolbox:
            info = await toolbox.call("sandbox", "environment_info", {})
            return {"servers": toolbox.servers, "tools": {k: toolbox.tools_for(k) for k in toolbox.servers}, "env": info}

    try:
        probe_result = asyncio.run(probe())
        typer.secho(f"mcp servers      {', '.join(probe_result['servers'])}", fg=typer.colors.GREEN)
        for server, tools in probe_result["tools"].items():
            typer.echo(f"  {server}: {', '.join(tools)}")
    except Exception as exc:  # noqa: BLE001
        ok = False
        typer.secho(f"mcp servers      FAILED: {exc}", fg=typer.colors.RED)

    typer.echo("=" * 48)
    if ok:
        typer.secho("all checks passed", fg=typer.colors.GREEN)
    else:
        typer.secho("some checks failed", fg=typer.colors.RED)
    raise typer.Exit(0 if ok else 1)


# ---------------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------------


def _render_event(event) -> None:
    stage = (event.stage or event.kind).ljust(9)
    agent = (event.agent or "-").ljust(18)
    colour = {
        "failed": typer.colors.RED,
        "tests": typer.colors.YELLOW,
        "fix": typer.colors.MAGENTA,
        "run": typer.colors.CYAN,
    }.get(event.kind if "fail" in event.message else event.stage, typer.colors.WHITE)
    typer.secho(f"  {stage} {agent} {event.message}", fg=colour)


def _render_summary(report) -> None:
    typer.echo("\n" + "=" * 60)
    colour = typer.colors.GREEN if report.status == "completed" else typer.colors.RED
    typer.secho(f"  status: {report.status}", fg=colour)
    typer.echo(f"  run:    {report.run_id}")
    typer.echo(f"  tests:  {report.tests_passed} passed, {report.tests_failed} failed")
    typer.echo(f"  fixes:  {report.fix_rounds} repair round(s)")
    typer.echo(f"  files:  {len(report.files_written)}")
    for path in report.files_written[:12]:
        typer.echo(f"          {path}")
    if len(report.files_written) > 12:
        typer.echo(f"          ... {len(report.files_written) - 12} more")
    if report.project_dir:
        typer.echo(f"  project: {report.project_dir}")
    if report.how_to_run:
        typer.echo("\n  run it:")
        for command in report.how_to_run:
            typer.echo(f"    $ {command}")
    typer.echo("=" * 60)


if __name__ == "__main__":
    app()
