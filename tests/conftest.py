"""Global conftest for Windows compatibility."""
import sys
import types

# Mock the 'resource' module (Unix-only) for testing on Windows
resource = types.ModuleType("resource")
resource.RLIMIT_NOFILE = 7
resource.RLIMIT_AS = 9
resource.getrlimit = lambda x: (1024, 4096)
resource.setrlimit = lambda x, y: None
sys.modules["resource"] = resource
