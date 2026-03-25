"""
Tests for infrakit.time module
"""

import pytest
import time
from pathlib import Path
import tempfile
import os

from infrakit.time import (
    profile_script,
    pipeline_profiler,
    track,
    CLIProfiler,
    PipelineProfiler,
    ProfileResult,
    PipelineResult,
    FunctionStats,
    PipelineStep,
    format_time,
)


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def sample_script(tmp_path):
    """Create a sample Python script for profiling"""
    script = tmp_path / "sample.py"
    script.write_text("""
import time

def fast_function():
    '''Runs quickly'''
    pass

def slow_function():
    '''Takes some time'''
    time.sleep(0.01)

def recursive_function(n):
    '''Recursive function'''
    if n <= 0:
        return 1
    return n * recursive_function(n - 1)

def main():
    for _ in range(5):
        fast_function()
    
    for _ in range(3):
        slow_function()
    
    recursive_function(10)

if __name__ == '__main__':
    main()
""")
    return script


@pytest.fixture
def complex_script(tmp_path):
    """Create a more complex script with data processing"""
    script = tmp_path / "complex.py"
    script.write_text("""
import time

def load_data():
    '''Simulate data loading'''
    time.sleep(0.005)
    return list(range(100))

def transform_data(data):
    '''Transform the data'''
    time.sleep(0.003)
    return [x * 2 for x in data]

def validate_data(data):
    '''Validate the data'''
    time.sleep(0.002)
    return len(data) > 0

def save_data(data):
    '''Save the data'''
    time.sleep(0.004)
    return True

def main():
    data = load_data()
    transformed = transform_data(data)
    is_valid = validate_data(transformed)
    if is_valid:
        save_data(transformed)

if __name__ == '__main__':
    main()
""")
    return script


# ============================================================================
# UTILITY TESTS
# ============================================================================

class TestFormatTime:
    """Test time formatting utility"""
    
    def test_format_microseconds(self):
        assert "500.00µs" == format_time(0.0005)
        assert "10.00µs" == format_time(0.00001)
    
    def test_format_milliseconds(self):
        assert "5.00ms" == format_time(0.005)
        assert "100.00ms" == format_time(0.1)
    
    def test_format_seconds(self):
        assert "1.500s" == format_time(1.5)
        assert "10.000s" == format_time(10.0)
    
    def test_edge_cases(self):
        assert format_time(0.0).endswith("µs")
        assert format_time(0.0009).endswith("µs")
        assert format_time(0.001).endswith("ms")
        assert format_time(0.999).endswith("ms")
        assert format_time(1.0).endswith("s")


# ============================================================================
# DATA STRUCTURE TESTS
# ============================================================================

class TestPipelineStep:
    """Test PipelineStep data structure"""
    
    def test_initialization(self):
        step = PipelineStep(name="test_step")
        assert step.name == "test_step"
        assert step.call_count == 0
        assert step.total_time == 0.0
        assert step.execution_times == []
    
    def test_add_execution(self):
        step = PipelineStep(name="test_step")
        step.add_execution(0.1)
        step.add_execution(0.2)
        step.add_execution(0.15)
        
        assert step.call_count == 3
        assert round(step.total_time,2) == 0.45
        assert len(step.execution_times) == 3
    
    def test_avg_time(self):
        step = PipelineStep(name="test_step")
        step.add_execution(0.1)
        step.add_execution(0.2)
        step.add_execution(0.3)
        
        assert step.avg_time == pytest.approx(0.2, rel=1e-6)
    
    def test_min_max_time(self):
        step = PipelineStep(name="test_step")
        step.add_execution(0.1)
        step.add_execution(0.3)
        step.add_execution(0.2)
        
        assert step.min_time == 0.1
        assert step.max_time == 0.3
    
    def test_empty_step(self):
        step = PipelineStep(name="test_step")
        assert step.avg_time == 0.0
        assert step.min_time == 0.0
        assert step.max_time == 0.0


class TestPipelineResult:
    """Test PipelineResult data structure"""
    
    def test_initialization(self):
        steps = {
            "step1": PipelineStep(name="step1"),
            "step2": PipelineStep(name="step2"),
        }
        result = PipelineResult(
            pipeline_name="test",
            total_time=1.0,
            steps=steps
        )
        
        assert result.pipeline_name == "test"
        assert result.total_time == 1.0
        assert len(result.steps) == 2
    
    def test_get_sorted_steps(self):
        step1 = PipelineStep(name="step1")
        step1.add_execution(0.1)
        
        step2 = PipelineStep(name="step2")
        step2.add_execution(0.3)
        
        step3 = PipelineStep(name="step3")
        step3.add_execution(0.2)
        
        result = PipelineResult(
            pipeline_name="test",
            total_time=0.6,
            steps={"step1": step1, "step2": step2, "step3": step3}
        )
        
        sorted_steps = result.get_sorted_steps()
        assert sorted_steps[0][0] == "step2"  # Highest time
        assert sorted_steps[1][0] == "step3"
        assert sorted_steps[2][0] == "step1"  # Lowest time


# ============================================================================
# CLI PROFILER TESTS
# ============================================================================

class TestCLIProfiler:
    """Test CLI-based profiler"""
    
    def test_initialization(self):
        profiler = CLIProfiler(
            max_functions=20,
            min_time_ms=2.0,
            exclude_stdlib=False
        )
        
        assert profiler.max_functions == 20
        assert profiler.min_time_ms == 2.0
        assert profiler.exclude_stdlib is False
    
    def test_profile_script(self, sample_script):
        profiler = CLIProfiler(
            max_functions=10,
            min_time_ms=0.1,
            exclude_stdlib=True
        )
        
        result = profiler.profile_script(str(sample_script))
        
        assert isinstance(result, ProfileResult)
        assert result.script_path == str(sample_script)
        assert result.total_time > 0
        assert len(result.function_stats) > 0
    
    def test_profile_nonexistent_script(self):
        profiler = CLIProfiler()
        
        with pytest.raises(FileNotFoundError):
            profiler.profile_script("nonexistent.py")
    
    def test_profile_invalid_script(self, tmp_path):
        script = tmp_path / "invalid.py"
        script.write_text("this is not valid python syntax !!!")
        
        profiler = CLIProfiler()
        
        with pytest.raises(RuntimeError):
            profiler.profile_script(str(script))
    
    def test_filter_by_min_time(self, sample_script):
        # High threshold - should filter out most functions
        profiler = CLIProfiler(
            max_functions=100,
            min_time_ms=50.0,  # 50ms threshold
            exclude_stdlib=True
        )
        
        result = profiler.profile_script(str(sample_script))
        
        # Should have very few or no functions
        assert len(result.function_stats) < 5
    
    def test_max_functions_limit(self, complex_script):
        profiler = CLIProfiler(
            max_functions=2,
            min_time_ms=0.1,
            exclude_stdlib=True
        )
        
        result = profiler.profile_script(str(complex_script))
        
        # Should be limited to 2 functions
        assert len(result.function_stats) <= 2


class TestProfileScriptFunction:
    """Test the profile_script convenience function"""
    
    def test_profile_script(self, sample_script, capsys):
        result = profile_script(
            script_path=str(sample_script),
            max_functions=10,
            min_time_ms=0.1,
            exclude_stdlib=True
        )
        
        # Check result
        assert isinstance(result, ProfileResult)
        assert result.total_time > 0
        
        # Check that output was printed
        captured = capsys.readouterr()
        assert "Profile Results" in captured.out
        assert "Total execution time" in captured.out


# ============================================================================
# PIPELINE PROFILER TESTS
# ============================================================================

class TestPipelineProfiler:
    """Test decorator-based pipeline profiler"""
    
    def test_initialization(self):
        profiler = PipelineProfiler(name="Test Pipeline")
        assert profiler.name == "Test Pipeline"
        assert len(profiler.steps) == 0
        assert profiler._active is False
    
    def test_track_decorator(self):
        profiler = PipelineProfiler(name="Test")
        
        @profiler.track
        def test_func():
            time.sleep(0.01)
            return "result"
        
        # Without context manager, should not track
        result = test_func()
        assert result == "result"
        assert len(profiler.steps) == 0
        
        # With context manager, should track
        with profiler.profile():
            result = test_func()
        
        assert result == "result"
        assert "test_func" in profiler.steps
        assert profiler.steps["test_func"].call_count == 1
    
    def test_track_with_custom_name(self):
        profiler = PipelineProfiler(name="Test")
        
        @profiler.track(name="Custom Step")
        def test_func():
            time.sleep(0.01)
        
        with profiler.profile():
            test_func()
        
        assert "Custom Step" in profiler.steps
        assert profiler.steps["Custom Step"].call_count == 1
    
    def test_multiple_calls(self):
        profiler = PipelineProfiler(name="Test")
        
        @profiler.track
        def test_func():
            time.sleep(0.005)
        
        with profiler.profile():
            test_func()
            test_func()
            test_func()
        
        step = profiler.steps["test_func"]
        assert step.call_count == 3
        assert step.total_time > 0.01  # At least 3 * 0.005
    
    def test_context_manager(self):
        profiler = PipelineProfiler(name="Test")
        
        @profiler.track
        def step1():
            time.sleep(0.005)
        
        @profiler.track
        def step2():
            time.sleep(0.010)
        
        with profiler.profile():
            step1()
            step2()
        
        assert len(profiler.steps) == 2
        assert profiler._total_time > 0.015
    
    def test_get_results(self):
        profiler = PipelineProfiler(name="Test Pipeline")
        
        @profiler.track
        def step1():
            time.sleep(0.005)
        
        with profiler.profile():
            step1()
        
        result = profiler.get_results()
        
        assert isinstance(result, PipelineResult)
        assert result.pipeline_name == "Test Pipeline"
        assert result.total_time > 0
        assert "step1" in result.steps
    
    def test_reset(self):
        profiler = PipelineProfiler(name="Test")
        
        @profiler.track
        def step1():
            pass
        
        with profiler.profile():
            step1()
        
        assert len(profiler.steps) > 0
        
        profiler.reset()
        
        assert len(profiler.steps) == 0
        assert profiler._total_time == 0.0
        assert profiler._active is False


class TestPipelineProfilerDecorator:
    """Test the @pipeline_profiler decorator"""
    
    def test_basic_usage(self, capsys):
        @pipeline_profiler("Test Pipeline")
        def main():
            step1()
            step2()
        
        @track
        def step1():
            time.sleep(0.005)
        
        @track
        def step2():
            time.sleep(0.010)
        
        main()
        
        # Check that output was printed
        captured = capsys.readouterr()
        assert "Pipeline Profile: Test Pipeline" in captured.out
        assert "step1" in captured.out
        assert "step2" in captured.out
    
    def test_custom_step_names(self, capsys):
        @pipeline_profiler("Custom Pipeline")
        def main():
            load()
            process()
        
        @track(name="Data Loading")
        def load():
            time.sleep(0.005)
        
        @track(name="Data Processing")
        def process():
            time.sleep(0.008)
        
        main()
        
        captured = capsys.readouterr()
        assert "Data Loading" in captured.out
        assert "Data Processing" in captured.out


class TestStandaloneTrackDecorator:
    """Test the standalone @track decorator"""
    
    def test_track_without_profiler(self):
        # Should work fine, just won't track
        @track
        def test_func():
            return "result"
        
        result = test_func()
        assert result == "result"
    
    def test_track_with_pipeline_profiler(self, capsys):
        @pipeline_profiler("Test")
        def main():
            func1()
            func2()
        
        @track
        def func1():
            time.sleep(0.005)
        
        @track(name="Custom Func")
        def func2():
            time.sleep(0.010)
        
        main()
        
        captured = capsys.readouterr()
        assert "func1" in captured.out
        assert "Custom Func" in captured.out


# ============================================================================
# INTEGRATION TESTS
# ============================================================================

class TestIntegration:
    """Integration tests combining multiple features"""
    
    def test_full_pipeline_workflow(self, capsys):
        """Test a complete data processing pipeline"""
        
        @pipeline_profiler("Data Processing")
        def process_data():
            data = load_data()
            transformed = transform(data)
            validated = validate(transformed)
            save(validated)
            return validated
        
        @track(name="Load Data")
        def load_data():
            time.sleep(0.005)
            return list(range(100))
        
        @track(name="Transform")
        def transform(data):
            time.sleep(0.008)
            return [x * 2 for x in data]
        
        @track(name="Validate")
        def validate(data):
            time.sleep(0.003)
            return data if len(data) > 0 else []
        
        @track(name="Save")
        def save(data):
            time.sleep(0.004)
            return True
        
        result = process_data()
        
        assert len(result) == 100
        
        captured = capsys.readouterr()
        assert "Data Processing" in captured.out
        assert "Load Data" in captured.out
        assert "Transform" in captured.out
        assert "Validate" in captured.out
        assert "Save" in captured.out
    
    def test_nested_pipeline_calls(self, capsys):
        """Test pipelines with nested function calls"""
        
        @pipeline_profiler("Main Pipeline")
        def main():
            process_batch()
            process_batch()
        
        @track(name="Process Batch")
        def process_batch():
            step1()
            step2()
        
        @track
        def step1():
            time.sleep(0.002)
        
        @track
        def step2():
            time.sleep(0.003)
        
        main()
        
        captured = capsys.readouterr()
        
        # Process Batch should be called 2 times
        # step1 and step2 should each be called 2 times
        assert "Process Batch" in captured.out
        assert "step1" in captured.out
        assert "step2" in captured.out