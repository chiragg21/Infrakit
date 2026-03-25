"""
CLI commands for infrakit.time
"""

import typer
from pathlib import Path
from typing import Optional

from infrakit.time import profile_script

time_app = typer.Typer(name = "time", help="Profile and time Python scripts", no_args_is_help=True)


@time_app.command(name="run")
def run_profiler(
    script: Path = typer.Argument(
        ...,
        help="Path to Python script to profile",
        exists=True,
        file_okay=True,
        dir_okay=False,
    ),
    max_functions: int = typer.Option(
        30,
        "--max-functions", "-n",
        help="Maximum number of functions to display",
        min=1,
    ),
    min_time: float = typer.Option(
        1.0,
        "--min-time", "-t",
        help="Minimum execution time in milliseconds to include",
        min=0.0,
    ),
    include_stdlib: bool = typer.Option(
        False,
        "--include-stdlib",
        help="Include Python standard library calls in results",
    ),
):
    """
    Profile a Python script using cProfile.
    
    Executes the script under profiling and displays function-level timing statistics
    in a clean, filtered table format.
    
    Examples:
    
        # Basic profiling
        ik time run myscript.py
        
        # Show more functions, include faster calls
        ik time run myscript.py --max-functions 50 --min-time 0.1
        
        # Include stdlib calls
        ik time run myscript.py --include-stdlib
    """
    try:
        # Run profiler (results printed automatically)
        profile_script(
            script_path=str(script),
            max_functions=max_functions,
            min_time_ms=min_time,
            exclude_stdlib=not include_stdlib,
        )
        
    except FileNotFoundError as e:
        typer.secho(f"✗ {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)
    
    except RuntimeError as e:
        typer.secho(f"✗ {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)
    
    except Exception as e:
        typer.secho(f"✗ Unexpected error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)


if __name__ == "__main__":
    time_app()