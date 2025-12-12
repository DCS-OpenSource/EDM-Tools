# SPDX-License-Identifier: MIT
# EDM Tools – Image Base Path (modular subpanel)
#
# Lets the user define a "base folder" for textures, and automatically updates
# all Image Texture nodes in Shader Editors when the base path changes.
#
# How it works:
# - When you apply a base path, we "track" each encountered bpy.data.image by
#   storing a relative path (edmtools_relpath) computed from the base.
# - If the base changes later, we rebuild each tracked image.filepath from the
#   new base + stored relpath (and optionally reload).

import os
import bpy
from bpy.props import (
    BoolProperty,
    StringProperty,
    PointerProperty,
)


# ---------------- Helpers ----------------

def _norm_dir(path: str) -> str:
    """Normalize a directory path and ensure it ends with a separator."""
    if not path:
        return ""
    # Make absolute using Blender's path utils (handles //)
    abspath = bpy.path.abspath(path)
    abspath = os.path.normpath(abspath)
    # ensure trailing sep for clean prefix checks
    if not abspath.endswith(os.sep):
        abspath += os.sep
    return abspath


def _safe_relpath(full_path: str, base_dir: str) -> str | None:
    """Try to get a relpath; return None if it can't be made relative."""
    try:
        return os.path.relpath(full_path, base_dir)
    except Exception:
        return None


def _iter_image_nodes_in_materials():
    """Yield (material, node) for all TEX_IMAGE nodes with an image."""
    for mat in bpy.data.materials:
        if not mat or not mat.use_nodes or not mat.node_tree:
            continue
        for node in mat.node_tree.nodes:
            if node and node.type == 'TEX_IMAGE' and getattr(node, "image", None):
                yield mat, node


def _iter_image_nodes_in_worlds():
    """Yield (world, node) for all TEX_IMAGE nodes with an image."""
    for w in bpy.data.worlds:
        if not w or not w.use_nodes or not w.node_tree:
            continue
        for node in w.node_tree.nodes:
            if node and node.type == 'TEX_IMAGE' and getattr(node, "image", None):
                yield w, node


def _update_tracked_images(context, old_base: str, new_base: str, reload_images: bool, create_tracking: bool):
    """
    Update image.filepath for tracked images and/or create tracking for images
    that currently live under old_base/new_base.
    """
    old_base_n = _norm_dir(old_base)
    new_base_n = _norm_dir(new_base)

    if not new_base_n or not os.path.isdir(new_base_n):
        return (0, 0, 0, 0, "New base path is empty or not a directory")

    # Collect images referenced by shader editor nodes (materials + worlds)
    referenced_images = set()
    for _, node in _iter_image_nodes_in_materials():
        referenced_images.add(node.image)
    for _, node in _iter_image_nodes_in_worlds():
        referenced_images.add(node.image)

    tracked = 0
    updated = 0
    skipped_packed = 0
    missing_files = 0

    for img in referenced_images:
        if img is None:
            continue

        # Skip packed images (they don't rely on disk paths)
        if img.packed_file is not None:
            skipped_packed += 1
            continue

        # Determine the "source path" we use to compute tracking / relpath
        img_abs = bpy.path.abspath(img.filepath) if img.filepath else ""
        img_abs = os.path.normpath(img_abs) if img_abs else ""

        # If we already track a relpath, use it.
        rel = img.get("edmtools_relpath", None)

        # If we already track a relpath, use it.
        rel = img.get("edmtools_relpath", None)
        
        # Optionally create tracking data if missing.
        if rel is None and create_tracking:
            # Prefer computing relpath from NEW base (what the user is setting now)
            if img_abs and img_abs.startswith(new_base_n):
                rel = _safe_relpath(img_abs, new_base_n)
        
            # If it isn't inside new base, fall back to old base (if any)
            if (not rel) and old_base_n and img_abs and img_abs.startswith(old_base_n):
                rel = _safe_relpath(img_abs, old_base_n)
        
            # Final fallback: just the filename (no subfolders)
            if not rel:
                rel = os.path.basename(img_abs) if img_abs else img.name
        
            img["edmtools_relpath"] = rel

        # If still untracked, we can't confidently rebuild
        rel = img.get("edmtools_relpath", None)
        if not rel:
            continue

        tracked += 1
        new_full = os.path.normpath(os.path.join(new_base_n, rel))

        # Write as Blender-friendly path (absolute is fine; Blender also supports //)
        img.filepath = new_full

        # Count missing targets (helpful feedback)
        if not os.path.exists(bpy.path.abspath(img.filepath)):
            missing_files += 1
        else:
            updated += 1

        if reload_images:
            try:
                img.reload()
            except Exception:
                pass

    msg = "Updated tracked images"
    return (tracked, updated, skipped_packed, missing_files, msg)


# ---------------- Properties ----------------

def _on_base_path_changed(self, context):
    """Auto-apply when base path changes (if enabled)."""
    props = context.scene.edm_tools_image_base_path

    # Avoid doing work until the user actually enables auto-apply
    if not props.auto_apply:
        props.last_base_path = props.base_path
        return

    old_base = props.last_base_path
    new_base = props.base_path

    # No change (or initial set)
    if (old_base or "") == (new_base or ""):
        return

    tracked, updated, skipped_packed, missing, _ = _update_tracked_images(
        context=context,
        old_base=old_base,
        new_base=new_base,
        reload_images=props.reload_images,
        create_tracking=props.track_untracked_images,
    )

    # Store new as last
    props.last_base_path = props.base_path

    # Show a concise info line in Blender status bar / reports
    # (update callbacks don't have self.report)
    if tracked > 0:
        print(f"[EDM Tools] Image Base Path: tracked={tracked}, updated={updated}, packed_skipped={skipped_packed}, missing={missing}")


class EDMToolsImageBasePathProps(bpy.types.PropertyGroup):
    """Properties for Image Base Path module."""

    base_path: StringProperty(
        name="Images Base Folder",
        description="Base folder for textures (directory). Changing this can rewrite image paths used in shader nodes.",
        default="",
        subtype='DIR_PATH',
        update=_on_base_path_changed,
    )

    last_base_path: StringProperty(
        name="Last Base Folder",
        description="Internal: last applied base path",
        default="",
        subtype='DIR_PATH',
    )

    auto_apply: BoolProperty(
        name="Auto-Apply on Change",
        description="When enabled, changing the base folder immediately updates image paths",
        default=True,
    )

    reload_images: BoolProperty(
        name="Reload Images",
        description="Reload images after updating file paths",
        default=True,
    )

    track_untracked_images: BoolProperty(
        name="Track Untracked Images",
        description="If an image has no stored relpath, attempt to create one so it can be updated on future base changes",
        default=True,
    )


# ---------------- Operator ----------------

class EDMTOOLS_OT_apply_image_base_path(bpy.types.Operator):
    """Apply the base folder now (and create tracking relpaths)."""
    bl_idname = "edmtools.apply_image_base_path"
    bl_label = "Apply Base Path Now"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        props = scene.edm_tools_image_base_path

        new_base = props.base_path
        if not new_base:
            self.report({'ERROR'}, "Base path is empty")
            return {'CANCELLED'}

        new_base_n = _norm_dir(new_base)
        if not os.path.isdir(new_base_n):
            self.report({'ERROR'}, f"Not a directory: {bpy.path.abspath(new_base)}")
            return {'CANCELLED'}

        old_base = props.last_base_path or ""

        tracked, updated, skipped_packed, missing, _ = _update_tracked_images(
            context=context,
            old_base=old_base,
            new_base=new_base,
            reload_images=props.reload_images,
            create_tracking=True,  # operator always creates tracking when missing
        )

        props.last_base_path = props.base_path

        self.report(
            {'INFO'},
            f"Applied base path. Tracked: {tracked}, Updated(existing): {updated}, "
            f"Packed skipped: {skipped_packed}, Missing targets: {missing}"
        )
        return {'FINISHED'}


class EDMTOOLS_OT_clear_image_tracking(bpy.types.Operator):
    """Remove edmtools_relpath tracking from images referenced by shader nodes."""
    bl_idname = "edmtools.clear_image_tracking"
    bl_label = "Clear Tracking"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        referenced_images = set()
        for _, node in _iter_image_nodes_in_materials():
            referenced_images.add(node.image)
        for _, node in _iter_image_nodes_in_worlds():
            referenced_images.add(node.image)

        cleared = 0
        for img in referenced_images:
            if img is None:
                continue
            if "edmtools_relpath" in img:
                try:
                    del img["edmtools_relpath"]
                    cleared += 1
                except Exception:
                    pass

        self.report({'INFO'}, f"Cleared tracking on {cleared} image(s).")
        return {'FINISHED'}


# ---------------- UI (subpanel) ----------------

class EDMTOOLS_PT_image_base_path_subpanel(bpy.types.Panel):
    bl_label = "Image Base Path"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "EDM Tools"
    bl_parent_id = "EDMTOOLS_PT_root"  # attach under your root panel
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        props = context.scene.edm_tools_image_base_path

        col = layout.column(align=True)
        col.label(text="Texture Root Folder:")
        col.prop(props, "base_path", text="")

        # Effective / last applied (helps debugging)
        col.separator()
        col.label(text=f"Last applied: {props.last_base_path or '(none)'}", icon='FILE_FOLDER')

        layout.separator()

        col = layout.column(align=True)
        col.prop(props, "auto_apply")
        col.prop(props, "reload_images")
        col.prop(props, "track_untracked_images")

        layout.separator()

        row = layout.row(align=True)
        row.operator(EDMTOOLS_OT_apply_image_base_path.bl_idname, icon='FILE_REFRESH')
        row.operator(EDMTOOLS_OT_clear_image_tracking.bl_idname, icon='TRASH')


# ---------------- Register ----------------

_classes = (
    EDMToolsImageBasePathProps,
    EDMTOOLS_OT_apply_image_base_path,
    EDMTOOLS_OT_clear_image_tracking,
    EDMTOOLS_PT_image_base_path_subpanel,
)

def register():
    for c in _classes:
        bpy.utils.register_class(c)

    bpy.types.Scene.edm_tools_image_base_path = PointerProperty(
        type=EDMToolsImageBasePathProps
    )

def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)

    if hasattr(bpy.types.Scene, "edm_tools_image_base_path"):
        del bpy.types.Scene.edm_tools_image_base_path
