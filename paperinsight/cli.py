from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from paperinsight import __version__
from paperinsight.agentflow import AgentPreparePipeline
from paperinsight.utils.config import load_config
from paperinsight.utils.terminal import create_console

app = typer.Typer(
    name="paperinsight",
    help="Agent-first PDF paper analysis workflow.",
    add_completion=False,
)
agent_app = typer.Typer(help="Run the staged agent workflow.")
app.add_typer(agent_app, name="agent")

console = create_console()


def _collect_pdf_files(pdf_dir: Path, recursive: bool) -> list[Path]:
    iterator = pdf_dir.rglob("*.pdf") if recursive else pdf_dir.glob("*.pdf")
    return [path for path in iterator if path.is_file()]


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        console.print(f"PaperInsight AgentFlow v{__version__}")
        console.print(ctx.get_help())


@app.command()
def version() -> None:
    console.print(f"PaperInsight AgentFlow v{__version__}")


@agent_app.command("prepare")
def agent_prepare(
    pdf_dir: Path = typer.Argument(..., help="Directory containing PDF files."),
    output_dir: Optional[Path] = typer.Option(None, "--output", "-o", help="Agent run root directory."),
    recursive: bool = typer.Option(False, "--recursive", "-r", help="Recursively scan subdirectories."),
    run_name: Optional[str] = typer.Option(None, "--run-name", help="Optional run directory name."),
    no_cache: bool = typer.Option(False, "--no-cache", help="Disable markdown cache reuse."),
) -> None:
    config = load_config()
    pdf_dir = pdf_dir.resolve()
    if not pdf_dir.exists():
        raise typer.BadParameter(f"Input directory does not exist: {pdf_dir}")
    if not pdf_dir.is_dir():
        raise typer.BadParameter(f"Input path is not a directory: {pdf_dir}")

    pdf_files = _collect_pdf_files(pdf_dir, recursive)
    if not pdf_files:
        console.print("[red]No PDF files found[/red]")
        raise typer.Exit(1)

    if output_dir is None:
        output_dir = pdf_dir / "agent_runs"

    cache_config = config.get("cache", {})
    pipeline = AgentPreparePipeline(
        output_dir=output_dir,
        config={
            "mineru": config.get("mineru", {}),
            "cache": cache_config,
        },
        cache_dir=cache_config.get("directory", ".cache"),
    )
    stats = pipeline.prepare(
        pdf_dir=pdf_dir,
        recursive=recursive,
        pdf_files=pdf_files,
        use_cache=cache_config.get("enabled", True) and not no_cache,
        run_name=run_name,
    )

    console.print()
    console.print("[bold cyan]Agent Prepare Complete[/bold cyan]")
    console.print(f"  PDFs:              {stats['pdf_count']}")
    console.print(f"  Prepared:          {stats['success_count']}")
    console.print(f"  Parse failed:      {stats['error_count']}")
    console.print(f"  Run dir:           {stats['run_dir']}")
    console.print(f"  Manifest:          {stats['manifest_path']}")
    console.print(f"  Identity jobs:     {stats['identity_jobs_path']}")
    console.print(f"  Identity results:  {stats['identity_results_path']}")
    console.print(f"  Prompt file:       {stats['identity_prompt_path']}")


@agent_app.command("import-identity")
def agent_import_identity(
    run_dir: Path = typer.Argument(..., help="Agent run directory."),
    results_path: Optional[Path] = typer.Option(None, "--results", help="Identity results JSONL path."),
) -> None:
    run_dir = run_dir.resolve()
    if not run_dir.exists():
        raise typer.BadParameter(f"Run directory does not exist: {run_dir}")
    if not run_dir.is_dir():
        raise typer.BadParameter(f"Run path is not a directory: {run_dir}")

    config = load_config()
    cache_config = config.get("cache", {})
    pipeline = AgentPreparePipeline(
        output_dir=run_dir.parent,
        config={"mineru": {"enabled": False}, "cache": cache_config},
        cache_dir=cache_config.get("directory", ".cache"),
    )
    stats = pipeline.import_identity_results(run_dir=run_dir, results_path=results_path)

    console.print()
    console.print("[bold cyan]Identity Import Complete[/bold cyan]")
    console.print(f"  Imported:          {stats['imported_count']}")
    console.print(f"  Invalid:           {stats['invalid_count']}")
    console.print(f"  Unmatched:         {stats['unmatched_count']}")
    console.print(f"  Manifest:          {stats['manifest_path']}")
    console.print(f"  Summary:           {stats['summary_path']}")


@agent_app.command("extract-metrics")
def agent_extract_metrics(
    run_dir: Path = typer.Argument(..., help="Agent run directory."),
    force: bool = typer.Option(False, "--force", help="Re-run metrics extraction even if outputs already exist."),
) -> None:
    run_dir = run_dir.resolve()
    if not run_dir.exists():
        raise typer.BadParameter(f"Run directory does not exist: {run_dir}")
    if not run_dir.is_dir():
        raise typer.BadParameter(f"Run path is not a directory: {run_dir}")

    config = load_config()
    cache_config = config.get("cache", {})
    pipeline = AgentPreparePipeline(
        output_dir=run_dir.parent,
        config={
            "mineru": {"enabled": False},
            "cache": cache_config,
            "llm": config.get("llm", {}),
            "cleaner": config.get("cleaner", {}),
            "output": config.get("output", {}),
        },
        cache_dir=cache_config.get("directory", ".cache"),
    )
    stats = pipeline.extract_metrics(run_dir=run_dir, force=force)

    console.print()
    console.print("[bold cyan]Metrics Extraction Complete[/bold cyan]")
    console.print(f"  Processed:         {stats['processed_count']}")
    console.print(f"  Failed:            {stats['failed_count']}")
    console.print(f"  Skipped:           {stats['skipped_count']}")
    console.print(f"  Manifest:          {stats['manifest_path']}")
    console.print(f"  Summary:           {stats['summary_path']}")


@agent_app.command("finalize")
def agent_finalize(
    run_dir: Path = typer.Argument(..., help="Agent run directory."),
    output_dir: Optional[Path] = typer.Option(None, "--output", "-o", help="Report output directory."),
    export_json: bool = typer.Option(False, "--json", help="Also export JSON report."),
) -> None:
    run_dir = run_dir.resolve()
    if not run_dir.exists():
        raise typer.BadParameter(f"Run directory does not exist: {run_dir}")
    if not run_dir.is_dir():
        raise typer.BadParameter(f"Run path is not a directory: {run_dir}")

    config = load_config()
    cache_config = config.get("cache", {})
    output_config = config.get("output", {})
    pipeline = AgentPreparePipeline(
        output_dir=run_dir.parent,
        config={"cache": cache_config, "output": output_config},
        cache_dir=cache_config.get("directory", ".cache"),
    )
    stats = pipeline.finalize(
        run_dir=run_dir,
        output_dir=output_dir,
        sort_by_if=output_config.get("sort_by_if", True),
        export_json=export_json,
    )

    console.print()
    console.print("[bold cyan]Agent Finalize Complete[/bold cyan]")
    console.print(f"  Finalized:         {stats['finalized_count']}")
    console.print(f"  Incomplete:        {stats['incomplete_count']}")
    console.print(f"  Manifest:          {stats['manifest_path']}")
    for report_type, path in stats["report_files"].items():
        console.print(f"  {report_type.title()} report:     {path}")
    console.print(f"  Summary:           {stats['summary_path']}")


if __name__ == "__main__":
    app()
