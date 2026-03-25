"""
infrakit.time - Lightweight timing and profiling system

Provides both CLI-based and decorator-based profiling for Python projects.

CLI Usage:
    ik time run script.py [--max-functions 30] [--min-time 1.0] [--include-stdlib]

Decorator Usage:
    from infrakit.time import pipeline_profiler, track
    
    @pipeline_profiler("Data Processing Pipeline")
    def main():
        load_data()
        transform_data()
        save_results()
    
    @track
    def load_data():
        # Your code here
        pass
    
    @track(name="Transform Step")
    def transform_data():
        # Your code here
        pass
"""

from .profiler import (
    # Main functions
    profile_script,
    pipeline_profiler,
    track,
    
    # Classes
    CLIProfiler,
    PipelineProfiler,
    
    # Data structures
    ProfileResult,
    PipelineResult,
    FunctionStats,
    PipelineStep,
    
    # Utilities
    format_time,
)

__all__ = [
    'profile_script',
    'pipeline_profiler',
    'track',
    'CLIProfiler',
    'PipelineProfiler',
    'ProfileResult',
    'PipelineResult',
    'FunctionStats',
    'PipelineStep',
    'format_time',
]