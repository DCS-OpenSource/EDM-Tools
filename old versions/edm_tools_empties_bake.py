# SPDX-License-Identifier: MIT
# EDM Tools – Armature Empties & Bake
# Blender 4.2+
#
# Workflow:
# 1. Pick bones (dropdown).
# 2. Set frame range + naming prefix.
# 3. Click "Bake Empties from Armature + (Reparent + Retarget)".
#    - Makes/updates one Empty per bone.
#    - Puts those empties ONLY in EDM_ArmatureCtrls.
#    - Parents each empty to the SAME parent as the armature (including bone parenting),
#      and preserves world transform.  <<< NEW
#    - Samples bone world transform each frame and keys loc/rot/scale on the empty.
#    - Renames each empty's Action to "<number>_<name>_<bone>".
#    - Reparents any mesh/props that were bone-parented to now follow those empties,
#      preserving world transforms, and retargets constraints like Damped Track.
#
# 4. "Revert Bake":
#    - Puts children back on the original armature bones (and re-aims constraints),
#    - Deletes those empties and their actions,
#    - Only affects the active armature.
#
# Panel is trimmed to what you asked for.
# ------------------------------------------------------------------------------

import bpy
from bpy.props import (
    BoolProperty,
    IntProperty,
    StringProperty,
    EnumProperty,
    PointerProperty,
)
from mathutils import Vector

bl_info = {
    "name": "EDM Tools – Armature Empties & Bake",
    "author": "Caffeine Simulations / ChatGPT",
    "version": (1, 0, 5),
    "blender": (4, 2, 0),
    "location": "3D Viewport > Sidebar (N) > EDM Tools",
    "description": "Bake bone motion into empties, reparent children, revert cleanly.",
    "category": "Animation",
}

# ---------------------------------------------------------------------------
# Helpers / utilities
# ---------------------------------------------------------------------------

def get_active_armature(context):
    """Return the active object if it's an armature, else None."""
    obj = context.object
    if obj and obj.type == 'ARMATURE':
        return obj
    return None


def empty_name_for(arm_obj, bone_name: str) -> str:
    return f"CTRL_{arm_obj.name}_{bone_name}"


def ensure_only_in_collection(obj: bpy.types.Object, target_coll: bpy.types.Collection):
    """
    Make sure `obj` is ONLY in `target_coll`:
    - unlink it from all other collections
    - link to target_coll if not already there
    """
    for coll in list(obj.users_collection):
        if coll != target_coll:
            coll.objects.unlink(obj)

    if obj.name not in target_coll.objects:
        target_coll.objects.link(obj)


def get_or_create_empty_for_bone(context, arm_obj, pbone, target_coll=None) -> bpy.types.Object:
    """
    Create (or fetch existing) Empty for this pose bone.
    - Places it initially at the bone head (armature space -> world).
    - If target_coll is provided, the empty will be forced to live ONLY in that collection.
    NOTE: parenting to armature's parent is handled later in bake op, so we don't do it here.
    """
    name = empty_name_for(arm_obj, pbone.name)

    existing = context.scene.objects.get(name)
    if existing:
        if target_coll is not None:
            ensure_only_in_collection(existing, target_coll)
        return existing

    # Create new empty
    empty = bpy.data.objects.new(name, None)
    empty.empty_display_type = 'PLAIN_AXES'
    empty.empty_display_size = 0.1

    # Place at bone head (pbone.head is armature space -> multiply for world)
    head_world = arm_obj.matrix_world @ pbone.head
    empty.matrix_world.translation = head_world

    # Link it
    if target_coll is not None:
        target_coll.objects.link(empty)
    else:
        context.scene.collection.objects.link(empty)

    return empty


def bone_is_visible(arm_obj, pbone):
    """
    "Visible" = any overlapping layer bit between armature layers and this bone's layers.
    Matches old-school armature layer visibility.
    """
    return any(a and b for a, b in zip(arm_obj.data.layers, pbone.bone.layers))


def filter_pose_bones(context, arm_obj, props):
    """
    Returns a list of pose bones filtered by:
      - which_bones (ALL / VISIBLE / SELECTED)
      - only_selected_bones toggle
      - only_deform toggle
    (Note: only_selected_bones & only_deform are hidden in the UI but still active.)
    """
    pose_bones = list(arm_obj.pose.bones)

    if props.which_bones == 'SELECTED' or props.only_selected_bones:
        bones = [pb for pb in pose_bones if pb.bone.select]
    elif props.which_bones == 'VISIBLE':
        bones = [pb for pb in pose_bones if bone_is_visible(arm_obj, pb)]
    else:
        bones = pose_bones

    if props.only_deform:
        bones = [pb for pb in bones if pb.bone.use_deform]

    return bones


def make_controls_collection(context, coll_name="EDM_ArmatureCtrls"):
    """
    Ensure there is a collection for all generated empties (controller collection),
    and return it. We'll keep empties ONLY here.
    """
    coll = bpy.data.collections.get(coll_name)
    if coll is None:
        coll = bpy.data.collections.new(coll_name)
        context.scene.collection.children.link(coll)
    return coll


def bone_name_from_empty_name(arm_obj, empty_obj):
    """
    Given an armature and one of its baked empties (CTRL_<ArmatureName>_<BoneName>),
    extract "<BoneName>" so we know which bone to reparent back to.
    """
    prefix = f"CTRL_{arm_obj.name}_"
    if empty_obj.name.startswith(prefix):
        return empty_obj.name[len(prefix):]
    return None


# ---------------------------------------------------------------------------
# Scene Properties
# ---------------------------------------------------------------------------

class EDMToolsProps(bpy.types.PropertyGroup):
    ui_expand: BoolProperty(
        name="Rig Helpers",
        description="Show/Hide rig helpers UI",
        default=True,
    )

    which_bones: EnumProperty(
        name="Bones",
        description="Choose which bones to operate on",
        items=[
            ('ALL', "All Bones", "All bones (subject to internal defaults)"),
            ('VISIBLE', "Visible Bones", "Bones on visible armature layers"),
            ('SELECTED', "Selected Bones", "Only currently selected bones"),
        ],
        default='ALL',
    )

    # Hidden in UI, but still used
    only_deform: BoolProperty(
        name="Only Deform Bones",
        description="Limit to bones with Deform enabled",
        default=True,
    )

    only_selected_bones: BoolProperty(
        name="Only Selected Bones",
        description="Force using only selected pose bones (Pose Mode)",
        default=False,
    )

    frame_start: IntProperty(
        name="Start",
        description="Bake start frame",
        default=0,
        min=-1048574,
    )

    frame_end: IntProperty(
        name="End",
        description="Bake end frame",
        default=200,
        min=-1048574,
    )

    action_number: IntProperty(
        name="Number",
        description="Prefix number for new Actions (e.g. 10)",
        default=10,
        min=0,
    )

    action_name: StringProperty(
        name="Name",
        description="Suffix for new Actions (e.g. 'test' makes '10_test')",
        default="test",
    )

    clear_constraints_after_bake: BoolProperty(
        name="Clear Bone Constraints After Armature Bake",
        description="(Legacy / hidden)",
        default=False,
    )

    create_parent_collection: BoolProperty(
        name="Group Empties in Collection",
        description="Put all controller empties ONLY in 'EDM_ArmatureCtrls'",
        default=True,
    )

    do_reparent: BoolProperty(
        name="Reparent Bone Children to Empties",
        description=(
            "Objects bone-parented to the armature get moved under the baked empties "
            "(world transform preserved, constraints retargeted)."
        ),
        default=True,
    )


# ---------------------------------------------------------------------------
# Hidden/legacy operators kept for completeness
# ---------------------------------------------------------------------------

class EDMTOOLS_OT_bake_pose_to_action(bpy.types.Operator):
    bl_idname = "edmtools.bake_pose_to_action"
    bl_label = "Bake Armature Pose → Action"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        arm = get_active_armature(context)
        if not arm:
            self.report({'ERROR'}, "Active object must be an Armature")
            return {'CANCELLED'}

        props = context.scene.edm_tools
        fs = props.frame_start
        fe = props.frame_end

        if context.mode != 'POSE':
            bpy.ops.object.mode_set(mode='POSE')

        bpy.ops.nla.bake(
            frame_start=fs,
            frame_end=fe,
            only_selected=False,
            visual_keying=True,
            clear_constraints=props.clear_constraints_after_bake,
            use_current_action=False,
            bake_types={'POSE'},
        )

        desired_prefix = str(props.action_number)
        if props.action_name.strip():
            desired_name = desired_prefix + "_" + props.action_name.strip()
        else:
            desired_name = desired_prefix

        act = arm.animation_data.action if arm.animation_data else None
        if act:
            act.name = desired_name
            self.report({'INFO'}, f"Baked armature to Action '{act.name}'")
        else:
            self.report({'WARNING'}, "Bake finished, but no Action found on armature")

        return {'FINISHED'}


class EDMTOOLS_OT_bake_bones_to_empties(bpy.types.Operator):
    """Legacy debug: Bake empty.location from bone head only."""
    bl_idname = "edmtools.bake_bones_to_empties"
    bl_label = "Bake Bones → Empties (Loc Only)"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        arm = get_active_armature(context)
        if not arm:
            self.report({'ERROR'}, "Active object must be an Armature")
            return {'CANCELLED'}

        props = context.scene.edm_tools
        fs = props.frame_start
        fe = props.frame_end

        bones_to_process = filter_pose_bones(context, arm, props)
        if not bones_to_process:
            self.report({'WARNING'}, "No bones to process with current filters")
            return {'CANCELLED'}

        coll = make_controls_collection(context, "EDM_ArmatureCtrls") if props.create_parent_collection else None

        mapping = {}
        for pbone in bones_to_process:
            empty = get_or_create_empty_for_bone(context, arm, pbone, coll)
            mapping[pbone] = empty

        scene = context.scene
        current_frame = scene.frame_current
        deps = context.evaluated_depsgraph_get()

        try:
            for f in range(fs, fe + 1):
                scene.frame_set(f)
                deps.update()

                for pbone, empty in mapping.items():
                    head_world = arm.matrix_world @ pbone.head
                    empty.location = head_world
                    empty.keyframe_insert(data_path="location", frame=f)
        finally:
            scene.frame_set(current_frame)

        self.report({'INFO'}, f"Baked {len(mapping)} empties (location only) {fs}..{fe}")
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# MAIN BAKE OPERATOR
# ---------------------------------------------------------------------------

class EDMTOOLS_OT_bake_empties_from_armature(bpy.types.Operator):
    bl_idname = "edmtools.bake_empties_from_armature"
    bl_label = "Bake Empties from Armature + (Reparent + Retarget)"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        arm = get_active_armature(context)
        if not arm:
            self.report({'ERROR'}, "Active object must be an Armature")
            return {'CANCELLED'}

        props = context.scene.edm_tools
        fs = props.frame_start
        fe = props.frame_end

        # 1) Bones we're baking
        bones_to_process = filter_pose_bones(context, arm, props)
        if not bones_to_process:
            self.report({'WARNING'}, "No bones to process with current filters")
            return {'CANCELLED'}

        # 2) Make sure empties exist and live ONLY in EDM_ArmatureCtrls
        coll = make_controls_collection(context, "EDM_ArmatureCtrls") if props.create_parent_collection else None

        empties_info = []  # (pbone, empty)
        for pbone in bones_to_process:
            empty = get_or_create_empty_for_bone(context, arm, pbone, coll)

            # Force exclusive membership in the collection
            if coll is not None:
                ensure_only_in_collection(empty, coll)

            # >>> new parent-sync logic <<<
            # Match the armature's parent relationship (if any) so empties live under the same rig root.
            if arm.parent is not None:
                saved_world = empty.matrix_world.copy()
                empty.parent = arm.parent
                empty.parent_type = arm.parent_type
                if arm.parent_type == 'BONE':
                    empty.parent_bone = arm.parent_bone
                empty.matrix_world = saved_world
            else:
                # If arm has no parent, clear parent on the empty too (so reruns keep it consistent)
                if empty.parent is not None:
                    saved_world = empty.matrix_world.copy()
                    empty.parent = None
                    empty.parent_type = 'OBJECT'
                    empty.parent_bone = ""
                    empty.matrix_world = saved_world
            # <<< end parent-sync logic >>>

            # Use quaternion so we key stable rotation
            if empty.rotation_mode != 'QUATERNION':
                empty.rotation_mode = 'QUATERNION'

            empties_info.append((pbone, empty))

        # 3) Manual bake: copy each bone's world matrix to its empty for every frame
        scene = context.scene
        current_frame = scene.frame_current
        deps = context.evaluated_depsgraph_get()

        try:
            for f in range(fs, fe + 1):
                scene.frame_set(f)
                deps.update()

                for pbone, empty in empties_info:
                    mw = (arm.matrix_world @ pbone.matrix).copy()
                    empty.matrix_world = mw

                    empty.keyframe_insert(data_path="location", frame=f)
                    empty.keyframe_insert(data_path="rotation_quaternion", frame=f)
                    empty.keyframe_insert(data_path="scale", frame=f)
        finally:
            scene.frame_set(current_frame)

        # 4) Rename each empty's action to "<number>_<name>_<bone>"
        prefix_number = str(props.action_number)
        suffix_name = props.action_name.strip()
        if suffix_name:
            common_prefix = prefix_number + "_" + suffix_name
        else:
            common_prefix = prefix_number

        for pbone, empty in empties_info:
            if empty.animation_data and empty.animation_data.action:
                empty.animation_data.action.name = f"{common_prefix}_{pbone.name}"

        # 5) Optional: reparent/retarget objects that were bone-parented
        if props.do_reparent:
            bone_to_empty = {pb.name: e for pb, e in empties_info}

            bone_children = []
            for obj in context.scene.objects:
                if (
                    obj.parent == arm and
                    obj.parent_type == 'BONE' and
                    obj.parent_bone in bone_to_empty
                ):
                    bone_children.append(obj)

            for child in bone_children:
                old_bone = child.parent_bone
                new_parent = bone_to_empty[old_bone]

                world_mx = child.matrix_world.copy()

                # Retarget constraints that pointed at this armature+bone to aim at new_parent instead
                for con in list(child.constraints):
                    if hasattr(con, "target") and hasattr(con, "subtarget"):
                        if con.target == arm and con.subtarget == old_bone:
                            con.target = new_parent
                            con.subtarget = ""

                child.parent = new_parent
                child.parent_type = 'OBJECT'
                child.matrix_world = world_mx

        self.report(
            {'INFO'},
            f"Baked {len(empties_info)} empties {fs}..{fe}, reparented={props.do_reparent}"
        )
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# REVERT OPERATOR
# ---------------------------------------------------------------------------

class EDMTOOLS_OT_revert_bake(bpy.types.Operator):
    bl_idname = "edmtools.revert_bake"
    bl_label = "Revert Bake"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        arm = get_active_armature(context)
        if not arm:
            self.report({'ERROR'}, "Active object must be an Armature to revert")
            return {'CANCELLED'}

        prefix = f"CTRL_{arm.name}_"

        # 1) Find all empties that belong to THIS armature's bake pass
        empties_for_arm = []
        for obj in list(context.scene.objects):
            if (
                obj.type == 'EMPTY' and
                obj.name.startswith(prefix)
            ):
                empties_for_arm.append(obj)

        if not empties_for_arm:
            self.report({'WARNING'}, "No baked empties found for this armature")
            return {'CANCELLED'}

        # Map empty -> bone_name
        empty_to_bone = {}
        for emp in empties_for_arm:
            bone_name = bone_name_from_empty_name(arm, emp)
            if bone_name:
                empty_to_bone[emp] = bone_name

        # 2) Reparent any objects currently parented to those empties back to the armature bone,
        #    and retarget constraints back at that armature bone.
        for obj in list(context.scene.objects):
            par = obj.parent
            if par in empty_to_bone and obj.type != 'EMPTY':
                bone_name = empty_to_bone[par]
                wmx = obj.matrix_world.copy()

                # Constraints that were pointing at that empty go back to arm+bone
                for con in list(obj.constraints):
                    if hasattr(con, "target") and hasattr(con, "subtarget"):
                        if con.target == par:
                            con.target = arm
                            con.subtarget = bone_name

                obj.parent = arm
                obj.parent_type = 'BONE'
                obj.parent_bone = bone_name
                obj.matrix_world = wmx

        # 3) Collect actions from those empties so we can try to free them
        actions_to_check = set()
        for emp in empties_for_arm:
            if emp.animation_data and emp.animation_data.action:
                actions_to_check.add(emp.animation_data.action)

        # 4) Delete the empties themselves
        for emp in empties_for_arm:
            bpy.data.objects.remove(emp, do_unlink=True)

        # 5) Purge any now-unreferenced Actions those empties had
        for act in actions_to_check:
            if act.users == 0:
                bpy.data.actions.remove(act, do_unlink=True)

        self.report({'INFO'}, f"Reverted bake for '{arm.name}' ({len(empties_for_arm)} empties removed)")
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Panel in the N sidebar (clean UI)
# ---------------------------------------------------------------------------

class VIEW3D_PT_edm_tools(bpy.types.Panel):
    bl_label = "EDM Tools"
    bl_category = "EDM Tools"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        props = scene.edm_tools

        box = layout.box()
        row = box.row()
        # Expand/collapse UI section
        row.prop(
            props,
            "ui_expand",
            text="Rig Helpers",
            icon='TRIA_DOWN' if props.ui_expand else 'TRIA_RIGHT',
            emboss=False
        )

        if not props.ui_expand:
            return

        col = box.column(align=True)

        arm = get_active_armature(context)
        col.label(text=f"Active Armature: {arm.name if arm else 'None'}")

        # Bone filter dropdown
        col.separator()
        col.label(text="Bone Filter:")
        col.prop(props, "which_bones", text="")

        # Frame range
        col.separator()
        col.label(text="Bake Range:")
        row_range = col.row(align=True)
        row_range.prop(props, "frame_start")
        row_range.prop(props, "frame_end")

        # Action naming (Number + Name on one row)
        col.separator()
        col.label(text="Action Naming:")
        row_name = col.row(align=True)
        row_name.prop(props, "action_number")
        row_name.prop(props, "action_name")

        # Options
        col.separator()
        col.prop(props, "create_parent_collection")
        col.prop(props, "do_reparent")

        # Buttons
        col.separator()
        col.operator(
            EDMTOOLS_OT_bake_empties_from_armature.bl_idname,
            icon='ACTION'
        )

        row_buttons = col.row(align=True)
        row_buttons.operator(
            EDMTOOLS_OT_revert_bake.bl_idname,
            icon='TRASH'
        )


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

classes = (
    EDMToolsProps,
    EDMTOOLS_OT_bake_pose_to_action,        # hidden / legacy
    EDMTOOLS_OT_bake_bones_to_empties,      # hidden / legacy
    EDMTOOLS_OT_bake_empties_from_armature, # main bake
    EDMTOOLS_OT_revert_bake,                # undo
    VIEW3D_PT_edm_tools,
)

def register():
    for c in classes:
        bpy.utils.register_class(c)

    bpy.types.Scene.edm_tools = PointerProperty(type=EDMToolsProps)


def unregister():
    for c in reversed(classes):
        bpy.utils.unregister_class(c)

    if hasattr(bpy.types.Scene, "edm_tools"):
        del bpy.types.Scene.edm_tools


if __name__ == "__main__":
    register()
