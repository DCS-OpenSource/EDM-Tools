bl_info = {
    "name": "EDM Tools",
    "author": "Caffeine Simulations",
    "version": (1, 0, 0),
    "blender": (4, 2, 0),
    "location": "3D Viewport > Sidebar (N) > EDM Tools",
    "description": "EDM Helper Tools for DCS World Blender Export",
    "category": "Animation",
}

import bpy
import importlib
import pkgutil
import sys
import traceback
from pathlib import Path

_loaded_modules = []


# ------------------------------------------------------------
# Root panel
# ------------------------------------------------------------

class EDMTOOLS_PT_root(bpy.types.Panel):
    bl_label = "EDM Tools"
    bl_category = "EDM Tools"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'

    def draw(self, context):
        layout = self.layout


# ------------------------------------------------------------
# Auto Module Loader
# ------------------------------------------------------------

def _discover_modules():
    """Find all Python modules in edm_tools/modules/."""
    package_path = Path(__file__).parent / "modules"
    found = []
    if not package_path.exists():
        print("[EDM Tools]: No 'modules' folder found.")
        return found

    for file in package_path.glob("*.py"):
        if file.name == "__init__.py":
            continue
        modname = f".modules.{file.stem}"
        found.append(modname)
    return found


def _import_modules():
    """Import or reload all discovered modules, with verbose error logging."""
    global _loaded_modules
    _loaded_modules.clear()

    discovered = _discover_modules()
    print(f"[EDM Tools]: Found {len(discovered)} module(s): {discovered}")

    for path in discovered:
        try:
            mod = importlib.import_module(path, __package__)
            mod = importlib.reload(mod)
            _loaded_modules.append(mod)
            print(f"[EDM Tools]: Loaded: {path}")
        except Exception as e:
            print(f"[EDM Tools]: Failed to load module '{path}': {e}")
            traceback.print_exc()


# ------------------------------------------------------------
# Registration
# ------------------------------------------------------------

classes = (
    EDMTOOLS_PT_root,
)


def register():
    print("\n[EDM Tools] Registering root and modules...")
    for c in classes:
        bpy.utils.register_class(c)

    _import_modules()

    for mod in _loaded_modules:
        if hasattr(mod, "register"):
            try:
                mod.register()
                print(f"[EDM Tools]: Registered module: {mod.__name__}")
            except Exception as e:
                print(f"[EDM Tools]: Error registering {mod.__name__}: {e}")
                traceback.print_exc()

    print("[EDM Tools]: Initialization complete.\n")


def unregister():
    print("\n[EDM Tools]: Unregistering EDM Tools modules...\n")
    for mod in reversed(_loaded_modules):
        if hasattr(mod, "unregister"):
            try:
                mod.unregister()
                print(f"[EDM Tools]: Unregistered module: {mod.__name__}")
            except Exception as e:
                print(f"[EDM Tools]: Error unregistering {mod.__name__}: {e}")
                traceback.print_exc()

    for c in reversed(classes):
        bpy.utils.unregister_class(c)

    _loaded_modules.clear()
    print("[EDM Tools]: Unregistration complete.\n")

if __name__ == "__main__":
    register()
