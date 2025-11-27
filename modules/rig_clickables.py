# SPDX-License-Identifier: MIT
# EDM Tools – Rig Clickables (modular subpanel)

import bpy
from bpy.props import (
    BoolProperty,
    IntProperty,
    StringProperty,
    PointerProperty,
    FloatProperty,
)
from mathutils import Vector

# ---------------- Helpers ----------------

def get_active_object(context):
    obj = context.object
    return obj if obj is not None else None


def get_clickables_collection(context):
    """Ensure there's a top-level 'CLICKABLES' collection under the Scene Collection."""
    scene_coll = context.scene.collection
    coll = bpy.data.collections.get("CLICKABLES")

    if coll is None:
        coll = bpy.data.collections.new("CLICKABLES")
        scene_coll.children.link(coll)
    else:
        # Make sure it's linked under the Scene Collection
        if coll not in scene_coll.children:
            scene_coll.children.link(coll)

    return coll


def generate_action_name(props):
    """Generate action name as '{arg num}_{arg name}'."""
    arg_num = props.arg_number
    arg_name = props.arg_name.strip()
    return f"{arg_num}_{arg_name}" if arg_name else f"{arg_num}"


def generate_box_name(props):
    """Final box empty name: override if given, otherwise PNT-{arg_number}."""
    if props.box_name.strip():
        return props.box_name.strip()
    return f"PNT-{props.arg_number}"


def parent_keep_transform(child, parent, context):
    """Parent child to parent using the real 'Parent > Object (Keep Transform)' operator."""
    if child is None or parent is None:
        return

    view_layer = context.view_layer

    # Save previous selection and active object
    prev_active = view_layer.objects.active
    prev_selection = [o for o in view_layer.objects if o.select_get()]

    # Ensure we're in Object mode (operator requirement)
    if context.mode != 'OBJECT':
        try:
            bpy.ops.object.mode_set(mode='OBJECT')
        except Exception:
            pass

    # Prepare selection for parenting op
    bpy.ops.object.select_all(action='DESELECT')
    parent.select_set(True)
    child.select_set(True)
    view_layer.objects.active = parent

    bpy.ops.object.parent_set(type='OBJECT', keep_transform=True)

    # Restore previous selection (we override selection at the end of the op anyway)
    bpy.ops.object.select_all(action='DESELECT')
    for o in prev_selection:
        if o.name in context.view_layer.objects:
            o.select_set(True)
    view_layer.objects.active = prev_active


# ---------------- Properties ----------------

class EDMToolsRigClickablesProps(bpy.types.PropertyGroup):
    """Properties for Rig Clickables module."""

    arg_number: IntProperty(
        name="Arg",
        description="DCS draw-arg number for this clickable",
        default=0,
        min=0,
        max=65535,
    )

    arg_name: StringProperty(
        name="Name",
        description="Label for this arg (e.g. Canopy, Batt_SW)",
        default="",
    )

    box_name: StringProperty(
        name="Box Name Override",
        description="Optional custom clickable box empty name. "
                    "If blank, defaults to 'PNT-<arg number>'.",
        default="",
    )

    anim_empty_size: FloatProperty(
        name="Anim Empty Size",
        description="Display size for the animation control empty",
        default=0.1,
        min=0.01,
        max=1.0,
        subtype='FACTOR',
    )

    copy_object_rotation: BoolProperty(
        name="Match Object Rotation",
        description="Align the animation empty rotation to the active object",
        default=True,      # checked by default
    )

    match_box_bounds: BoolProperty(
        name="Match Mesh Bounds",
        description="Roughly size the box empty to the active object's bounding box",
        default=True,      # checked by default
    )


# ---------------- Operator ----------------

class EDMTOOLS_OT_rig_clickable(bpy.types.Operator):
    """Create a clickable rig: animation empty + action + box empty."""
    bl_idname = "edmtools.rig_clickable"
    bl_label  = "Rig Clickable"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type in {"MESH", "CURVE", "SURFACE", "FONT", "META"}

    def execute(self, context):
        scene = context.scene
        props = scene.edm_tools_rig_clickables
        obj   = context.active_object

        if obj is None:
            self.report({'ERROR'}, "No active object selected")
            return {'CANCELLED'}

        # ---------------- Collection & names ----------------
        collection    = get_clickables_collection(context)  # always use CLICKABLES
        action_name   = generate_action_name(props)
        box_name      = generate_box_name(props)
        arg_number    = props.arg_number

        # World-space transform of the object
        obj_world     = obj.matrix_world.copy()
        obj_origin_ws = obj_world.translation

        # ---------------- Animation empty ----------------
        # Just mesh name + _CTRL
        anim_empty_name = f"{obj.name}_CTRL"
        anim_empty = bpy.data.objects.new(anim_empty_name, None)
        anim_empty.empty_display_type = 'PLAIN_AXES'
        anim_empty.empty_display_size = props.anim_empty_size

        if props.copy_object_rotation:
            # Match full transform (pos + rot + scale)
            anim_empty.matrix_world = obj_world
        else:
            # Only match origin position
            anim_empty.matrix_world.translation = obj_origin_ws

        collection.objects.link(anim_empty)

        # Store arg metadata for exporters
        anim_empty["arg_number"] = arg_number
        if props.arg_name.strip():
            anim_empty["arg_name"] = props.arg_name.strip()

        # ---------------- Action ----------------
        action = bpy.data.actions.new(action_name)
        anim_empty.animation_data_create()
        anim_empty.animation_data.action = action

        # ---------------- Box empty ----------------
        box_empty = bpy.data.objects.new(box_name, None)
        box_empty.empty_display_type = 'CUBE'
        box_empty.empty_display_size = 1.0  # base "1m" local size
        box_empty.scale = (1.0, 1.0, 1.0)

        # Start with same rotation/scale as the object
        box_empty.matrix_world = obj_world

        # Compute bounding box center in WORLD space
        if obj.bound_box:
            bb_local_pts = [Vector(corner) for corner in obj.bound_box]
            center_local = sum(bb_local_pts, Vector()) / 8.0
            center_world = obj.matrix_world @ center_local
        else:
            center_world = obj_origin_ws

        # Set the box empty's pivot to the geometry center
        box_empty.matrix_world.translation = center_world

        # Only allow rotation in Y axis
        box_empty.lock_rotation[0] = True  # X
        box_empty.lock_rotation[2] = True  # Z

        # Optionally, roughly match the mesh bounds with per-axis scale
        if props.match_box_bounds and obj.type == 'MESH':
            dx, dy, dz = obj.dimensions  # world-space dims
            base_size = box_empty.empty_display_size  # side length = 2 * size * scale
            if base_size <= 0:
                base_size = 1.0

            sx = dx / (2.0 * base_size) if dx > 0 else 1.0
            sy = dy / (2.0 * base_size) if dy > 0 else 1.0
            sz = dz / (2.0 * base_size) if dz > 0 else 1.0
            box_empty.scale = (sx, sy, sz)

        collection.objects.link(box_empty)

        # ---------------- Parenting with KEEP TRANSFORM ----------------
        original_parent = obj.parent

        # 1) If the object already had a parent, parent the CTRL under it (keep transform)
        if original_parent is not None:
            parent_keep_transform(anim_empty, original_parent, context)

        # 2) Parent mesh and box under the CTRL (keep transform)
        parent_keep_transform(obj,       anim_empty, context)
        parent_keep_transform(box_empty, anim_empty, context)

        # ---------------- Selection feedback ----------------
        bpy.ops.object.select_all(action='DESELECT')
        anim_empty.select_set(True)
        box_empty.select_set(True)
        obj.select_set(True)
        context.view_layer.objects.active = anim_empty

        self.report(
            {'INFO'},
            f"Rigged clickable: Empty '{anim_empty.name}', Box '{box_empty.name}', Action '{action.name}'"
        )
        return {'FINISHED'}


# ---------------- UI (subpanel) ----------------

class EDMTOOLS_PT_rig_clickables_subpanel(bpy.types.Panel):
    bl_label = "Rig Clickables"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "EDM Tools"
    bl_parent_id = "EDMTOOLS_PT_root"      # attach under your root panel
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        scene  = context.scene
        props  = scene.edm_tools_rig_clickables
        obj    = context.active_object

        layout.label(
            text=f"Active Object: {obj.name if obj else 'None'}",
            icon='MESH_CUBE' if obj and obj.type == 'MESH' else 'OBJECT_DATA'
        )

        # Arg number + name on one line
        col = layout.column(align=True)
        col.label(text="Arg Settings:")
        row = col.row(align=True)
        row.prop(props, "arg_number", text="Arg")
        row.prop(props, "arg_name", text="Name")

        # Some space above the size slider
        col.separator()
        col.prop(props, "anim_empty_size", text="Anim Empty Size")

        layout.separator()

        # Box naming with default preview
        col = layout.column(align=True)
        col.label(text="Box Empty:")
        col.prop(props, "box_name", text="Name Override")

        default_preview = f"PNT-{props.arg_number}"
        if props.box_name.strip():
            col.label(text=f"Effective name: {props.box_name}")
        else:
            col.label(text=f"Default name: {default_preview}")

        layout.separator()

        col = layout.column(align=True)
        col.prop(props, "copy_object_rotation")
        col.prop(props, "match_box_bounds")

        layout.separator()
        col.operator(EDMTOOLS_OT_rig_clickable.bl_idname, icon='CONSTRAINT')


# ---------------- Register ----------------

_classes = (
    EDMToolsRigClickablesProps,
    EDMTOOLS_OT_rig_clickable,
    EDMTOOLS_PT_rig_clickables_subpanel,
)

def register():
    for c in _classes:
        bpy.utils.register_class(c)
    bpy.types.Scene.edm_tools_rig_clickables = PointerProperty(
        type=EDMToolsRigClickablesProps
    )

def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
    if hasattr(bpy.types.Scene, "edm_tools_rig_clickables"):
        del bpy.types.Scene.edm_tools_rig_clickables
