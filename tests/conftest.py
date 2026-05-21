"""Windows-compatible conftest — mocks Linux-only modules."""
import sys
import types

# Mock the 'resource' module which is Linux-only
resource = types.ModuleType("resource")
resource.RLIMIT_NOFILE = 7
resource.RLIMIT_AS = 9
resource.RLIMIT_CORE = 4
resource.RLIMIT_DATA = 2
resource.RLIMIT_STACK = 3
resource.getrlimit = lambda x: (1024, 4096)
resource.setrlimit = lambda x, y: None
sys.modules["resource"] = resource
