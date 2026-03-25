"""
infrakit.time - Lightweight timing and profiling system

This module provides:
1. CLI-based profiler (ik time run) - Zero-setup profiling using cProfile
2. Decorator-based profiler (@pipeline_profiler + @track) - Fine-grained pipeline timing
"""

import cProfile
import pstats
import io
import time
import functools
from typing import Dict, List, Optional, Callable, Any
from dataclasses import dataclass, field
from contextlib import contextmanager
from pathlib import Path
import sys


# ============================================================================
# DATA STRUCTURES
# ============================================================================

@dataclass
class FunctionStats:
    """Statistics for a single function call"""
    name: str
    total_time: float
    call_count: int
    avg_time: float
    percentage: float


@dataclass
class PipelineStep:
    """Represents a single step in a pipeline"""
    name: str
    execution_times: List[float] = field(default_factory=list)
    call_count: int = 0
    total_time: float = 0.0
    
    def add_execution(self, duration: float):
        """Record a single execution"""
        self.execution_times.append(duration)
        self.call_count += 1
        self.total_time += duration
    
    @property
    def avg_time(self) -> float:
        """Average execution time"""
        return self.total_time / self.call_count if self.call_count > 0 else 0.0
    
    @property
    def min_time(self) -> float:
        """Minimum execution time"""
        return min(self.execution_times) if self.execution_times else 0.0
    
    @property
    def max_time(self) -> float:
        """Maximum execution time"""
        return max(self.execution_times) if self.execution_times else 0.0


@dataclass
class ProfileResult:
    """Result from CLI profiler"""
    script_path: str
    total_time: float
    function_stats: List[FunctionStats]
    raw_stats: Optional[pstats.Stats] = None


@dataclass
class PipelineResult:
    """Result from decorator-based pipeline profiler"""
    pipeline_name: str
    total_time: float
    steps: Dict[str, PipelineStep]
    
    def get_sorted_steps(self) -> List[tuple[str, PipelineStep]]:
        """Return steps sorted by total time (descending)"""
        return sorted(self.steps.items(), key=lambda x: x[1].total_time, reverse=True)


# ============================================================================
# CLI-BASED PROFILER
# ============================================================================

class CLIProfiler:
    """CLI-based profiler using cProfile"""
    
    def __init__(self, 
                 max_functions: int = 30,
                 min_time_ms: float = 1.0,
                 exclude_stdlib: bool = True):
        """
        Initialize CLI profiler
        
        Args:
            max_functions: Maximum number of functions to display
            min_time_ms: Minimum execution time (ms) to include
            exclude_stdlib: Filter out Python standard library calls
        """
        self.max_functions = max_functions
        self.min_time_ms = min_time_ms
        self.exclude_stdlib = exclude_stdlib
    
    def profile_script(self, script_path: str) -> ProfileResult:
        """
        Profile a Python script using cProfile
        
        Args:
            script_path: Path to the Python script to profile
            
        Returns:
            ProfileResult containing timing statistics
        """
        if not Path(script_path).exists():
            raise FileNotFoundError(f"Script not found: {script_path}")
        
        # Create profiler
        profiler = cProfile.Profile()
        
        # Execute script under profiling
        script_globals = {
            '__name__': '__main__',
            '__file__': script_path,
        }
        
        start_time = time.time()
        
        try:
            with open(script_path) as f:
                code = compile(f.read(), script_path, 'exec')
                profiler.runctx(code, script_globals, script_globals)
        except Exception as e:
            raise RuntimeError(f"Error executing script: {e}")
        
        total_time = time.time() - start_time
        
        # Extract statistics
        stats = pstats.Stats(profiler)
        stats.strip_dirs()
        
        # Convert to structured data
        function_stats = self._extract_function_stats(stats, total_time)
        
        return ProfileResult(
            script_path=script_path,
            total_time=total_time,
            function_stats=function_stats,
            raw_stats=stats
        )
    
    def _extract_function_stats(self, stats: pstats.Stats, total_time: float) -> List[FunctionStats]:
        """Extract and filter function statistics"""
        # Get raw stats
        raw_stats = []
        for func, (cc, nc, tt, ct, callers) in stats.stats.items():
            filename, line, func_name = func
            
            # Filter stdlib if requested
            if self.exclude_stdlib and self._is_stdlib(filename):
                continue
            
            # Filter by minimum time
            if tt * 1000 < self.min_time_ms:
                continue
            
            full_name = f"{Path(filename).name}:{func_name}"
            raw_stats.append({
                'name': full_name,
                'total_time': tt,
                'call_count': nc,
                'avg_time': tt / nc if nc > 0 else 0,
            })
        
        # Sort by total time
        raw_stats.sort(key=lambda x: x['total_time'], reverse=True)
        
        # Take top N
        raw_stats = raw_stats[:self.max_functions]
        
        # Calculate percentages
        result = []
        for stat in raw_stats:
            percentage = (stat['total_time'] / total_time * 100) if total_time > 0 else 0
            result.append(FunctionStats(
                name=stat['name'],
                total_time=stat['total_time'],
                call_count=stat['call_count'],
                avg_time=stat['avg_time'],
                percentage=percentage
            ))
        
        return result
    
    @staticmethod
    def _is_stdlib(filename: str) -> bool:
        """Check if a file is from Python standard library"""
        stdlib_markers = [
            '/lib/python',
            '\\lib\\python',
            'site-packages',
            '<frozen',
            '<built-in',
        ]
        return any(marker in filename for marker in stdlib_markers)


# ============================================================================
# DECORATOR-BASED PIPELINE PROFILER
# ============================================================================

class PipelineProfiler:
    """Context manager and decorator for pipeline profiling"""
    
    def __init__(self, name: str = "Pipeline"):
        """
        Initialize pipeline profiler
        
        Args:
            name: Name of the pipeline
        """
        self.name = name
        self.steps: Dict[str, PipelineStep] = {}
        self._start_time: Optional[float] = None
        self._total_time: float = 0.0
        self._active = False
    
    def track(self, func: Optional[Callable] = None, *, name: Optional[str] = None):
        """
        Decorator to track a function's execution time
        
        Usage:
            @profiler.track
            def my_function():
                pass
            
            @profiler.track(name="Custom Name")
            def my_function():
                pass
        """
        def decorator(f: Callable) -> Callable:
            step_name = name or f.__name__
            
            @functools.wraps(f)
            def wrapper(*args, **kwargs):
                if not self._active:
                    # Profiler not active, just run the function
                    return f(*args, **kwargs)
                
                # Initialize step if needed
                if step_name not in self.steps:
                    self.steps[step_name] = PipelineStep(name=step_name)
                
                # Time the execution
                start = time.perf_counter()
                try:
                    result = f(*args, **kwargs)
                    return result
                finally:
                    duration = time.perf_counter() - start
                    self.steps[step_name].add_execution(duration)
            
            return wrapper
        
        # Handle both @track and @track()
        if func is None:
            return decorator
        else:
            return decorator(func)
    
    @contextmanager
    def profile(self):
        """
        Context manager to activate profiling
        
        Usage:
            with profiler.profile():
                step1()
                step2()
        """
        self._active = True
        self._start_time = time.perf_counter()
        
        try:
            yield self
        finally:
            self._total_time = time.perf_counter() - self._start_time
            self._active = False
    
    def get_results(self) -> PipelineResult:
        """Get profiling results"""
        return PipelineResult(
            pipeline_name=self.name,
            total_time=self._total_time,
            steps=self.steps
        )
    
    def reset(self):
        """Reset all collected statistics"""
        self.steps.clear()
        self._start_time = None
        self._total_time = 0.0
        self._active = False


# Convenience decorator for simple use cases
_global_profiler: Optional[PipelineProfiler] = None


def pipeline_profiler(name: str = "Pipeline"):
    """
    Decorator to create a pipeline profiler context
    
    Usage:
        @pipeline_profiler("My Pipeline")
        def main():
            step1()
            step2()
            # Results printed automatically at end
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            profiler = PipelineProfiler(name=name)
            global _global_profiler
            _global_profiler = profiler
            
            with profiler.profile():
                result = func(*args, **kwargs)
            
            # Print results
            _print_pipeline_results(profiler.get_results())
            
            return result
        
        return wrapper
    
    return decorator


def track(func: Optional[Callable] = None, *, name: Optional[str] = None):
    """
    Standalone decorator to track function execution
    Uses the global profiler instance
    
    Usage:
        @track
        def my_function():
            pass
        
        @track(name="Custom Name")
        def my_function():
            pass
    """
    def decorator(f: Callable) -> Callable:
        step_name = name or f.__name__
        
        @functools.wraps(f)
        def wrapper(*args, **kwargs):
            global _global_profiler
            
            if _global_profiler is None or not _global_profiler._active:
                return f(*args, **kwargs)
            
            # Initialize step if needed
            if step_name not in _global_profiler.steps:
                _global_profiler.steps[step_name] = PipelineStep(name=step_name)
            
            # Time the execution
            start = time.perf_counter()
            try:
                result = f(*args, **kwargs)
                return result
            finally:
                duration = time.perf_counter() - start
                _global_profiler.steps[step_name].add_execution(duration)
        
        return wrapper
    
    # Handle both @track and @track()
    if func is None:
        return decorator
    else:
        return decorator(func)


# ============================================================================
# OUTPUT FORMATTERS
# ============================================================================

def format_time(seconds: float) -> str:
    """Format time in human-readable format"""
    if seconds < 0.001:
        return f"{seconds * 1_000_000:.2f}µs"
    elif seconds < 1:
        return f"{seconds * 1000:.2f}ms"
    else:
        return f"{seconds:.3f}s"


def _print_cli_results(result: ProfileResult):
    """Print CLI profiler results in a clean table"""
    print(f"\n{'=' * 80}")
    print(f"Profile Results: {result.script_path}")
    print(f"Total execution time: {format_time(result.total_time)}")
    print(f"{'=' * 80}\n")
    
    if not result.function_stats:
        print("No functions met the filtering criteria.")
        return
    
    # Table header
    print(f"{'Function':<50} {'Time':<12} {'Calls':<10} {'Avg':<12} {'%':<8}")
    print(f"{'-' * 50} {'-' * 12} {'-' * 10} {'-' * 12} {'-' * 8}")
    
    # Table rows
    for stat in result.function_stats:
        print(f"{stat.name:<50} "
              f"{format_time(stat.total_time):<12} "
              f"{stat.call_count:<10} "
              f"{format_time(stat.avg_time):<12} "
              f"{stat.percentage:>6.2f}%")
    
    print(f"\n{'=' * 80}\n")


def _print_pipeline_results(result: PipelineResult):
    """Print pipeline profiler results in a clean table"""
    print(f"\n{'=' * 80}")
    print(f"Pipeline Profile: {result.pipeline_name}")
    print(f"Total execution time: {format_time(result.total_time)}")
    print(f"{'=' * 80}\n")
    
    if not result.steps:
        print("No tracked steps found.")
        return
    
    # Calculate percentages
    sorted_steps = result.get_sorted_steps()
    
    # Table header
    print(f"{'Step':<40} {'Total':<12} {'Calls':<8} {'Avg':<12} {'Min':<12} {'Max':<12} {'%':<8}")
    print(f"{'-' * 40} {'-' * 12} {'-' * 8} {'-' * 12} {'-' * 12} {'-' * 12} {'-' * 8}")
    
    # Table rows
    for step_name, step in sorted_steps:
        percentage = (step.total_time / result.total_time * 100) if result.total_time > 0 else 0
        print(f"{step_name:<40} "
              f"{format_time(step.total_time):<12} "
              f"{step.call_count:<8} "
              f"{format_time(step.avg_time):<12} "
              f"{format_time(step.min_time):<12} "
              f"{format_time(step.max_time):<12} "
              f"{percentage:>6.2f}%")
    
    print(f"\n{'=' * 80}\n")


# ============================================================================
# PUBLIC API
# ============================================================================

def profile_script(script_path: str,
                  max_functions: int = 30,
                  min_time_ms: float = 1.0,
                  exclude_stdlib: bool = True) -> ProfileResult:
    """
    Profile a Python script using cProfile
    
    Args:
        script_path: Path to the Python script to profile
        max_functions: Maximum number of functions to display
        min_time_ms: Minimum execution time (ms) to include
        exclude_stdlib: Filter out Python standard library calls
        
    Returns:
        ProfileResult containing timing statistics
    """
    profiler = CLIProfiler(
        max_functions=max_functions,
        min_time_ms=min_time_ms,
        exclude_stdlib=exclude_stdlib
    )
    result = profiler.profile_script(script_path)
    _print_cli_results(result)
    return result


__all__ = [
    # Main functions
    'profile_script',
    'pipeline_profiler',
    'track',
    
    # Classes
    'CLIProfiler',
    'PipelineProfiler',
    
    # Data structures
    'ProfileResult',
    'PipelineResult',
    'FunctionStats',
    'PipelineStep',
    
    # Utilities
    'format_time',
]