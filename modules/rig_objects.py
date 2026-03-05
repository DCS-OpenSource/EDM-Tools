# SPDX-License-Identifier: MIT
# EDM Tools – Animation Empty + Auto Animation

import bpy
import math
import mathutils
from bpy.props import (
    FloatProperty,
    PointerProperty,
    IntProperty,
    StringProperty,
    EnumProperty,
)

# ------------------------------------------------------------
# Properties
# ------------------------------------------------------------

class EDMToolsAnimEmptyProps(bpy.types.PropertyGroup):

    arg_number: IntProperty(
        name="Arg",
        default=0,
        min=0,
        max=65535
    ) # type: ignore

    action_name: StringProperty(
        name=" Name",
        default=""
    ) # type: ignore

    empty_size: FloatProperty(
        name="Empty Size",
        default=0.01,
        min=0.001,
        max=1.0,
        unit='LENGTH'
    ) # type: ignore

    axis: EnumProperty(
        name="Axis",
        items=[
            ('X', "X", ""),
            ('Y', "Y", ""),
            ('Z', "Z", ""),
        ],
        default='X'
    ) # type: ignore

    start_frame: IntProperty(
        name="Start",
        default=100
    ) # type: ignore

    end_frame: IntProperty(
        name="End",
        default=200
    ) # type: ignore

    angle: FloatProperty(
        name="Angle (deg)",
        default=360.0
    ) # type: ignore

    keyframes: IntProperty(
        name="Steps",
        default=4,
        min=1,
        max=50
    ) # type: ignore


# ------------------------------------------------------------
# Helpers
# ------------------------------------------------------------

def generate_action_name(props, obj):

    arg = props.arg_number
    name = props.action_name.strip()

    if name:
        label = name
    else:
        label = obj.name

    return f"{arg}_{label}"


# ------------------------------------------------------------
# Operators
# ------------------------------------------------------------

class EDMTOOLS_OT_rig_object(bpy.types.Operator):
    bl_idname = "edmtools.rig_object"
    bl_label = "Rig Object"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):

        props = context.scene.edm_tools_anim_empty
        obj = context.active_object

        if obj is None:
            self.report({'ERROR'}, "No active object.")
            return {'CANCELLED'}

        empty_name = f"{obj.name}_CTRL"

        # create control empty
        empty = bpy.data.objects.new(empty_name, None)
        empty.empty_display_type = 'PLAIN_AXES'
        empty.empty_display_size = props.empty_size
        empty.rotation_mode = 'QUATERNION'

        # match transform
        empty.matrix_world = obj.matrix_world.copy()

        # link to same collection
        if obj.users_collection:
            obj.users_collection[0].objects.link(empty)
        else:
            context.scene.collection.objects.link(empty)

        # create animation action
        action_name = generate_action_name(props, obj)
        action = bpy.data.actions.new(action_name)

        empty.animation_data_create()
        empty.animation_data.action = action

        # preserve object world transform
        obj_matrix = obj.matrix_world.copy()

        obj.parent = empty
        obj.matrix_parent_inverse = empty.matrix_world.inverted()
        obj.matrix_world = obj_matrix

        # select control
        bpy.ops.object.select_all(action='DESELECT')
        empty.select_set(True)
        obj.select_set(True)

        context.view_layer.objects.active = empty

        self.report({'INFO'}, f"Rig created: {empty.name} | Action: {action.name}")

        return {'FINISHED'}
    

class EDMTOOLS_OT_create_animation(bpy.types.Operator):
    bl_idname = "edmtools.create_animation"
    bl_label = "Create Animation"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):

        props = context.scene.edm_tools_anim_empty
        obj = context.active_object

        # ------------------------------------------------------------
        # Determine control object
        # ------------------------------------------------------------

        if obj.type == 'EMPTY':
            ctrl = obj
        else:
            ctrl = bpy.data.objects.get(f"{obj.name}_CTRL")

            if ctrl is None:
                self.report({'ERROR'}, "Control empty not found.")
                return {'CANCELLED'}

        # ------------------------------------------------------------
        # Ensure animation data
        # ------------------------------------------------------------

        ctrl.rotation_mode = 'QUATERNION'

        if ctrl.animation_data is None:
            ctrl.animation_data_create()

        if ctrl.animation_data.action is None:
            ctrl.animation_data.action = bpy.data.actions.new(f"{ctrl.name}_Action")

        action = ctrl.animation_data.action

        # ------------------------------------------------------------
        # Setup animation parameters
        # ------------------------------------------------------------

        start = props.start_frame
        end = props.end_frame
        steps = props.keyframes

        axis_map = {
            'X': mathutils.Vector((1,0,0)),
            'Y': mathutils.Vector((0,1,0)),
            'Z': mathutils.Vector((0,0,1)),
        }

        axis = axis_map[props.axis]

        base = ctrl.rotation_quaternion.copy()

        prev_q = None

        # ------------------------------------------------------------
        # Insert quaternion keyframes
        # ------------------------------------------------------------

        for i in range(steps + 1):

            t = i / steps
            frame = start + t * (end - start)

            angle = math.radians(props.angle * t)

            q = base @ mathutils.Quaternion(axis, angle)

            # --- quaternion continuity fix ---
            if prev_q is not None and prev_q.dot(q) < 0:
                q = -q

            ctrl.rotation_quaternion = q
            ctrl.keyframe_insert("rotation_quaternion", frame=frame)

            prev_q = q

        # ------------------------------------------------------------
        # Linear interpolation
        # ------------------------------------------------------------

        for fc in action.fcurves:
            for kp in fc.keyframe_points:
                kp.interpolation = 'LINEAR'

        context.scene.frame_set(start)

        self.report({'INFO'}, f"Animation created on {ctrl.name}")

        return {'FINISHED'}


# ------------------------------------------------------------
# UI Panel
# ------------------------------------------------------------

class EDMTOOLS_PT_create_anim_empty(bpy.types.Panel):

    bl_label = "Rig & Animate Objects"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "EDM Tools"
    bl_parent_id = "EDMTOOLS_PT_root"

    def draw(self, context):

        layout = self.layout
        props = context.scene.edm_tools_anim_empty
        obj = context.active_object

        box = layout.box()
        col = box.column(align=True)

        col.label(
            text=f"Active Object: {obj.name if obj else 'None'}",
            icon='OBJECT_DATA'
        )

        # Rig Object

        box = layout.box()
        col = box.column(align=True)

        col.label(text="Rig Object", icon='DRIVER')

        row = col.row(align=True)
        row.prop(props, "arg_number")
        row.prop(props, "action_name")

        col.separator()

        col.prop(props, "empty_size")

        col.separator()

        col.operator(
            EDMTOOLS_OT_rig_object.bl_idname,
            icon='EMPTY_AXIS'
        )

        # Animation

        box = layout.box()
        col = box.column(align=True)

        col.label(text="Auto Animator (Local Axis)", icon='ANIM')

        row = col.row(align=True)
        row.prop(props, "axis", expand=True)

        row = col.row(align=True)
        row.prop(props, "start_frame")
        row.prop(props, "end_frame")

        col.prop(props, "angle")
        col.prop(props, "keyframes")

        col.separator()

        col.operator(
            EDMTOOLS_OT_create_animation.bl_idname,
            icon='KEYFRAME'
        )


# ------------------------------------------------------------
# Register
# ------------------------------------------------------------

_classes = (
    EDMToolsAnimEmptyProps,
    EDMTOOLS_OT_rig_object,
    EDMTOOLS_OT_create_animation,
    EDMTOOLS_PT_create_anim_empty,
)


def register():

    for c in _classes:
        bpy.utils.register_class(c)

    bpy.types.Scene.edm_tools_anim_empty = PointerProperty(
        type=EDMToolsAnimEmptyProps
    )


def unregister():

    for c in reversed(_classes):
        bpy.utils.unregister_class(c)

    if hasattr(bpy.types.Scene, "edm_tools_anim_empty"):
        del bpy.types.Scene.edm_tools_anim_empty