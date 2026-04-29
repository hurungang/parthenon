"""Print all registered FastAPI routes."""
import sys
sys.path.insert(0, "C:\\Users\\rhu\\source\\personal\\coding-workspace\\Parthenon\\backend")

from app.main import app

print("\n=== Registered Routes ===\n")
for route in app.routes:
    if hasattr(route, "path") and hasattr(route, "methods"):
        print(f"{list(route.methods)[0]:6} {route.path:50} {route.name}")
        
print("\n=== /user-roles endpoints ===\n")        
for route in app.routes:
    if hasattr(route, "path") and "user-roles" in route.path:
        print(f"Path: {route.path}")
        print(f"Methods: {route.methods}")
        print(f"Name: {route.name}")
        print(f"Endpoint: {route.endpoint}")
        if hasattr(route, "dependant"):
            print(f"Dependencies: {route.dependant.dependencies}")
        print()
