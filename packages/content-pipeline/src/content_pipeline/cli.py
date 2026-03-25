"""
CLI — Interface de linha de comando para o Content Pipeline.

Comandos:
    content-pipeline generate <vdp>     Gera imagem NB2 a partir de um VDP
    content-pipeline calibrate          Executa calibração com todos os VDPs
    content-pipeline batch <dir>        Executa batch de produção
    content-pipeline status             Mostra status dos outputs
    content-pipeline validate <vdp>     Valida VDP sem gerar
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from rich.console import Console
from rich.logging import RichHandler
from rich.panel import Panel
from rich.table import Table

console = Console()


def _setup_logging(level: str = "INFO") -> None:
    """Configura logging com Rich handler."""
    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(console=console, rich_tracebacks=True)],
    )


def cmd_generate(args: argparse.Namespace) -> int:
    """Gera imagem NB2 a partir de um VDP."""
    from content_pipeline.config import load_config
    from content_pipeline.pipeline.orchestrator import PipelineOrchestrator

    config = load_config(env_file=args.env)
    orchestrator = PipelineOrchestrator(config)

    vdp_path = Path(args.vdp).resolve()
    if not vdp_path.exists():
        console.print(f"[red]VDP não encontrado:[/red] {vdp_path}")
        return 1

    console.print(
        Panel(
            f"[bold]Gerando NB2[/bold]\nVDP: {vdp_path.name}",
            title="Content Pipeline",
            border_style="blue",
        )
    )

    result = orchestrator.run_single(
        vdp_path,
        output_subdir=args.output or "",
    )

    if result.success:
        console.print(f"\n[green bold]SUCESSO[/green bold] {result.summary}")
        console.print(f"  Arquivo: {result.output_path}")
    else:
        console.print(f"\n[red bold]FALHA[/red bold] {result.summary}")
        console.print(f"  Erro: {result.error}")
        return 1

    orchestrator.cleanup()
    return 0


def cmd_calibrate(args: argparse.Namespace) -> int:
    """Executa calibração com todos os VDPs de calibração."""
    from content_pipeline.config import load_config
    from content_pipeline.pipeline.orchestrator import PipelineOrchestrator

    config = load_config(env_file=args.env)
    orchestrator = PipelineOrchestrator(config)

    vdp_dir = Path(args.dir).resolve() if args.dir else None

    console.print(
        Panel(
            "[bold]Calibração NB2[/bold]\nGerando hero shots para validação",
            title="Content Pipeline",
            border_style="yellow",
        )
    )

    batch = orchestrator.run_calibration(vdp_dir=vdp_dir)

    _print_batch_report(batch)
    orchestrator.cleanup()

    return 0 if batch.failed == 0 else 1


def cmd_batch(args: argparse.Namespace) -> int:
    """Executa batch de produção."""
    from content_pipeline.config import load_config
    from content_pipeline.pipeline.orchestrator import PipelineOrchestrator

    config = load_config(env_file=args.env)
    orchestrator = PipelineOrchestrator(config)

    vdp_dir = Path(args.dir).resolve()
    if not vdp_dir.is_dir():
        console.print(f"[red]Diretório não encontrado:[/red] {vdp_dir}")
        return 1

    console.print(
        Panel(
            f"[bold]Batch de Produção[/bold]\nDiretório: {vdp_dir}",
            title="Content Pipeline",
            border_style="green",
        )
    )

    batch = orchestrator.run_batch(
        vdp_dir=vdp_dir,
        batch_id=args.batch_id,
    )

    _print_batch_report(batch)
    orchestrator.cleanup()

    return 0 if batch.failed == 0 else 1


def cmd_status(args: argparse.Namespace) -> int:
    """Mostra status dos outputs gerados."""
    from content_pipeline.config import load_config
    from content_pipeline.output.manager import OutputManager

    config = load_config(env_file=args.env)
    output = OutputManager(base_dir=config.output_dir)

    summary = output.get_output_summary()

    table = Table(title="Status de Produção")
    table.add_column("Métrica", style="cyan")
    table.add_column("Valor", style="green", justify="right")

    table.add_row("Imagens NB2", str(summary["nb2_images"]))
    table.add_row("Composições", str(summary["compositions"]))
    table.add_row("Tamanho Total", f"{summary['total_size_mb']:.1f} MB")

    console.print(table)
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    """Valida VDP sem gerar imagem."""
    from content_pipeline.nb2.vdp_loader import VDPLoader

    vdp_path = Path(args.vdp).resolve()
    if not vdp_path.exists():
        console.print(f"[red]VDP não encontrado:[/red] {vdp_path}")
        return 1

    loader = VDPLoader()
    try:
        spec = loader.load(vdp_path)
    except (ValueError, Exception) as e:
        console.print(f"[red]Validação falhou:[/red] {e}")
        return 1

    table = Table(title=f"VDP: {vdp_path.name}")
    table.add_column("Campo", style="cyan")
    table.add_column("Valor", style="white")

    table.add_row("Produto", spec.produto)
    table.add_row("Marca", spec.marca)
    table.add_row("Formato", spec.formato)
    table.add_row("Conceito", spec.conceito)
    table.add_row("PNG Referência", spec.png_referencia)
    table.add_row("Prompt NB2", f"{len(spec.prompt_nb2)} chars")
    table.add_row("Claims", str(len(spec.claims)))
    table.add_row("Critérios", str(len(spec.criterios_aprovacao)))
    table.add_row(
        "Logo",
        "[blue]Salk[/blue]" if spec.is_salk else "[green]Mendel[/green]",
    )

    console.print(table)
    console.print("[green]VDP válido[/green]")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    """Inicia o Content Studio (interface web)."""
    console.print(
        Panel(
            f"[bold]Salk Content Studio[/bold]\n"
            f"http://{args.host}:{args.port}",
            title="Content Studio",
            border_style="cyan",
        )
    )

    if args.open:
        import webbrowser
        webbrowser.open(f"http://{args.host}:{args.port}")

    from content_pipeline.web.app import run_server

    run_server(host=args.host, port=args.port)
    return 0


def _print_batch_report(batch) -> None:
    """Imprime relatório de um batch."""
    table = Table(title=f"Batch: {batch.batch_id}")
    table.add_column("VDP", style="cyan")
    table.add_column("Status", justify="center")
    table.add_column("Tentativas", justify="right")
    table.add_column("Tempo", justify="right")
    table.add_column("Output")

    for job in batch.jobs:
        status_icon = {
            "completed": "[green]OK[/green]",
            "failed": "[red]FALHA[/red]",
            "pending": "[yellow]PENDENTE[/yellow]",
            "running": "[blue]EXECUTANDO[/blue]",
            "skipped": "[dim]PULADO[/dim]",
        }.get(job.status.value, job.status.value)

        attempts = str(job.result.attempts) if job.result else "-"
        elapsed = f"{job.result.elapsed_seconds:.1f}s" if job.result else "-"
        output = str(job.result.output_path.name) if job.result and job.result.output_path else job.error or "-"

        table.add_row(job.vdp_path.name, status_icon, attempts, elapsed, output)

    console.print(table)
    console.print(
        f"\n[bold]Total:[/bold] {batch.total} | "
        f"[green]Sucesso:[/green] {batch.completed} | "
        f"[red]Falha:[/red] {batch.failed} | "
        f"Taxa: {batch.success_rate:.1f}%"
    )


def build_parser() -> argparse.ArgumentParser:
    """Constrói o parser de argumentos."""
    parser = argparse.ArgumentParser(
        prog="content-pipeline",
        description="Sistema de Produção de Conteúdo — Manager Grupo",
    )
    parser.add_argument(
        "--env",
        help="Caminho para arquivo .env",
        default=None,
    )

    subparsers = parser.add_subparsers(dest="command", help="Comando a executar")

    # generate
    gen = subparsers.add_parser("generate", help="Gerar imagem NB2 a partir de VDP")
    gen.add_argument("vdp", help="Caminho para arquivo VDP (.md)")
    gen.add_argument("--output", "-o", help="Subdiretório de output", default="")
    gen.set_defaults(func=cmd_generate)

    # calibrate
    cal = subparsers.add_parser("calibrate", help="Executar calibração NB2")
    cal.add_argument("--dir", "-d", help="Diretório com VDPs de calibração")
    cal.set_defaults(func=cmd_calibrate)

    # batch
    bat = subparsers.add_parser("batch", help="Executar batch de produção")
    bat.add_argument("dir", help="Diretório com VDPs do batch")
    bat.add_argument("--batch-id", "-b", help="ID do batch")
    bat.set_defaults(func=cmd_batch)

    # status
    st = subparsers.add_parser("status", help="Status dos outputs")
    st.set_defaults(func=cmd_status)

    # validate
    val = subparsers.add_parser("validate", help="Validar VDP sem gerar")
    val.add_argument("vdp", help="Caminho para arquivo VDP (.md)")
    val.set_defaults(func=cmd_validate)

    # serve
    srv = subparsers.add_parser("serve", help="Iniciar Content Studio (interface web)")
    srv.add_argument("--port", "-p", type=int, default=8080, help="Porta do servidor")
    srv.add_argument("--host", default="127.0.0.1", help="Host do servidor")
    srv.add_argument("--open", action="store_true", help="Abrir navegador automaticamente")
    srv.set_defaults(func=cmd_serve)

    return parser


def main() -> None:
    """Entry point da CLI."""
    parser = build_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    _setup_logging()

    try:
        exit_code = args.func(args)
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrompido pelo usuário[/yellow]")
        exit_code = 130
    except Exception as e:
        console.print(f"\n[red bold]Erro fatal:[/red bold] {e}")
        logging.exception("Erro fatal no pipeline")
        exit_code = 1

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
