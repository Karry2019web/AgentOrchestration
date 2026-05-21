import sys
import types

# Mock the 'resource' module for Windows compatibility
resource = types.ModuleType("resource")
resource.RLIMIT_NOFILE = 7
resource.RLIMIT_AS = 9
def getrlimit(x):
    return (1024, 4096)
resource.getrlimit = getrlimit
sys.modules["resource"] = resource
