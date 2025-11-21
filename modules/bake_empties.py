# SPDX-License-Identifier: MIT
# EDM Tools – Bake Empties from Armature (modular subpanel)

import bpy
from bpy.props import BoolProperty, IntProperty, StringProperty, EnumProperty, PointerProperty, FloatProperty

# ---------------- Helpers ----------------

def get_active_armature(context):
    obj = context.object
    return obj if (obj and obj.type == 'ARMATURE') else None

def empty_name_for(arm_obj, bone_name): return f"CTRL_{arm_obj.name}_{bone_name}"

def ensure_only_in_collection(obj, target_coll):
    for c in list(obj.users_collection):
        if c != target_coll:
            c.objects.unlink(obj)
    if obj.name not in target_coll.objects:
        target_coll.objects.link(obj)

def get_or_create_empty_for_bone(context, arm_obj, pbone, coll=None):
    name = empty_name_for(arm_obj, pbone.name)
    existing = context.scene.objects.get(name)
    if existing:
        if coll: ensure_only_in_collection(existing, coll)
        return existing
    empty = bpy.data.objects.new(name, None)
    # position at bone-head world
    empty.matrix_world.translation = (arm_obj.matrix_world @ pbone.head)
    if coll: coll.objects.link(empty)
    else: context.scene.collection.objects.link(empty)
    return empty

def bone_is_visible(arm_obj, pbone):
    return any(a and b for a, b in zip(arm_obj.data.layers, pbone.bone.layers))

def filter_pose_bones(context, arm_obj, props):
    pbs = list(arm_obj.pose.bones)
    if props.which_bones == 'SELECTED' or props.only_selected_bones:
        bones = [pb for pb in pbs if pb.bone.select]
    elif props.which_bones == 'VISIBLE':
        bones = [pb for pb in pbs if bone_is_visible(arm_obj, pb)]
    else:
        bones = pbs
    if props.only_deform:
        bones = [pb for pb in bones if pb.bone.use_deform]
    return bones

def make_controls_collection_for_armature(context, arm_obj):
    # Choose a "base" collection: wherever the armature lives
    if arm_obj.users_collection:
        base_coll = arm_obj.users_collection[0]
    else:
        base_coll = context.scene.collection

    coll_name = f"EDM_ArmatureCtrls_{arm_obj.name}"

    coll = bpy.data.collections.get(coll_name)
    if coll is None:
        coll = bpy.data.collections.new(coll_name)
        base_coll.children.link(coll)
    else:
        # Ensure it's at least linked under the same base collection
        if coll not in base_coll.children:
            base_coll.children.link(coll)

    return coll


def bone_name_from_empty_name(arm_obj, empty_obj):
    p = f"CTRL_{arm_obj.name}_"
    return empty_obj.name[len(p):] if empty_obj.name.startswith(p) else None

# ---------------- Properties ----------------

class EDMToolsBakeProps(bpy.types.PropertyGroup):
    which_bones: EnumProperty(
        name="Bones",
        items=[('ALL',"All Bones",""),('VISIBLE',"Visible Bones",""),('SELECTED',"Selected Bones","")],
        default='ALL',
    )
    # Hidden but honored:
    only_deform: BoolProperty(default=True)
    only_selected_bones: BoolProperty(default=False)

    frame_start: IntProperty(name="Start", default=0)
    frame_end:   IntProperty(name="End",   default=200)

    action_number: IntProperty(name="Number", default=0, min=0)
    action_name:   StringProperty(name="Name", default="animation")

    empty_size: FloatProperty(
        name="Empty Size", default=0.1, min=0.01, max=1.0, subtype='FACTOR')

    create_parent_collection: BoolProperty(
        name="Group Empties in Collection", default=True)
    do_reparent: BoolProperty(
        name="Reparent Bone Children to Empties", default=True)

# ---------------- Operators ----------------

class EDMTOOLS_OT_bake_empties_from_armature(bpy.types.Operator):
    bl_idname = "edmtools.bake_empties_from_armature"
    bl_label  = "Bake Empties from Armature"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        arm = get_active_armature(context)
        if not arm:
            self.report({'ERROR'}, "Active object must be an Armature")
            return {'CANCELLED'}

        props = context.scene.edm_tools_bake
        fs, fe = props.frame_start, props.frame_end

        bones = filter_pose_bones(context, arm, props)
        if not bones:
            self.report({'WARNING'}, "No bones to process")
            return {'CANCELLED'}

        coll = make_controls_collection_for_armature(context, arm) if props.create_parent_collection else None
        pairs = []  # (pbone, empty)
        for pbone in bones:
            e = get_or_create_empty_for_bone(context, arm, pbone, coll)
            if coll: ensure_only_in_collection(e, coll)

            e.empty_display_type = 'PLAIN_AXES'
            e.empty_display_size = props.empty_size

            # Parent empties like the armature is parented (including bone parenting)
            saved = e.matrix_world.copy()
            if arm.parent:
                e.parent      = arm.parent
                e.parent_type = arm.parent_type
                if arm.parent_type == 'BONE':
                    e.parent_bone = arm.parent_bone
            else:
                e.parent = None
                e.parent_type = 'OBJECT'
                e.parent_bone = ""
            e.matrix_world = saved

            e.rotation_mode = 'QUATERNION'
            pairs.append((pbone, e))

        scene = context.scene
        cur = scene.frame_current
        deps = context.evaluated_depsgraph_get()

        try:
            for f in range(fs, fe + 1):
                scene.frame_set(f); deps.update()
                for pbone, e in pairs:
                    e.matrix_world = (arm.matrix_world @ pbone.matrix).copy()
                    e.keyframe_insert("location", frame=f)
                    e.keyframe_insert("rotation_quaternion", frame=f)
                    e.keyframe_insert("scale", frame=f)
        finally:
            scene.frame_set(cur)

        # Name actions: <number>_<name>_<bone>
        prefix = str(props.action_number)
        suffix = props.action_name.strip()
        common = f"{prefix}_{suffix}" if suffix else prefix
        for pbone, e in pairs:
            if e.animation_data and e.animation_data.action:
                e.animation_data.action.name = f"{common}_{pbone.name}"

        # Reparent bone-children
        if props.do_reparent:
            map_empty = {pb.name: e for pb, e in pairs}
            to_move = [
                o for o in context.scene.objects
                if o.parent == arm and o.parent_type == 'BONE' and o.parent_bone in map_empty
            ]
            for obj in to_move:
                old_bone = obj.parent_bone
                new_par = map_empty[old_bone]
                wmx = obj.matrix_world.copy()
                # retarget constraints aimed at arm+bone -> empty
                for con in list(obj.constraints):
                    if hasattr(con, "target") and hasattr(con, "subtarget"):
                        if con.target == arm and con.subtarget == old_bone:
                            con.target, con.subtarget = new_par, ""
                obj.parent = new_par
                obj.parent_type = 'OBJECT'
                obj.matrix_world = wmx

        self.report({'INFO'}, f"Baked {len(pairs)} empties ({fs}..{fe})")
        return {'FINISHED'}


class EDMTOOLS_OT_revert_bake(bpy.types.Operator):
    bl_idname = "edmtools.revert_bake"
    bl_label  = "UnBake Empties to Armature"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        arm = get_active_armature(context)
        if not arm:
            self.report({'ERROR'}, "Active object must be an Armature")
            return {'CANCELLED'}

        prefix = f"CTRL_{arm.name}_"
        empties = [o for o in context.scene.objects if o.type == 'EMPTY' and o.name.startswith(prefix)]
        if not empties:
            self.report({'WARNING'}, "No baked empties for this armature")
            return {'CANCELLED'}

        emp2bone = {e: bone_name_from_empty_name(arm, e) for e in empties}

        # Reparent objects back to armature bones
        for obj in list(context.scene.objects):
            if obj.parent in emp2bone and obj.type != 'EMPTY':
                bone = emp2bone[obj.parent]
                wmx = obj.matrix_world.copy()
                # retarget constraints back to arm+bone
                for con in list(obj.constraints):
                    if hasattr(con, "target") and hasattr(con, "subtarget"):
                        if con.target == obj.parent:
                            con.target, con.subtarget = arm, bone
                obj.parent = arm
                obj.parent_type = 'BONE'
                obj.parent_bone = bone
                obj.matrix_world = wmx

        # Collect & remove empty actions
        actions = set()
        for e in empties:
            if e.animation_data and e.animation_data.action:
                actions.add(e.animation_data.action)
        for e in empties:
            bpy.data.objects.remove(e, do_unlink=True)
        for a in actions:
            if a.users == 0:
                bpy.data.actions.remove(a, do_unlink=True)

        coll_name = f"EDM_ArmatureCtrls_{arm.name}"
        coll = bpy.data.collections.get(coll_name)
        if coll:
            # only remove if it's now empty (no objects, no child collections)
            if not coll.objects and not coll.children:
                # Unlink from Scene Collection if present
                sc_children = context.scene.collection.children
                for child in list(sc_children):
                    if child == coll:
                        sc_children.unlink(coll)
                        break

                # Unlink from any other parent collections
                for parent in bpy.data.collections:
                    for child in list(parent.children):
                        if child == coll:
                            parent.children.unlink(coll)
                            break

                # Finally remove the collection datablock
                bpy.data.collections.remove(coll)

        self.report({'INFO'}, f"Reverted bake for '{arm.name}' ({len(empties)} empties removed)")
        return {'FINISHED'}

# ---------------- UI (subpanel) ----------------

class EDMTOOLS_PT_bake_subpanel(bpy.types.Panel):
    bl_label = "Bake Empties"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "EDM Tools"
    bl_parent_id = "EDMTOOLS_PT_root"         # attach under the root panel
    bl_options = {'DEFAULT_CLOSED'}           # collapsible dropdown

    def draw(self, context):
        props = context.scene.edm_tools_bake
        layout = self.layout
        arm = get_active_armature(context)
        layout.label(text=f"Active Armature: {arm.name if arm else 'None'}")

        col = layout.column(align=True)
        col.label(text="Bone Filter:")
        col.prop(props, "which_bones", text="")

        col.separator()
        col.label(text="Bake Range:")
        r = col.row(align=True)
        r.prop(props, "frame_start")
        r.prop(props, "frame_end")

        col.separator()
        col.label(text="Action Naming:")
        r2 = col.row(align=True)
        r2.prop(props, "action_number")
        r2.prop(props, "action_name")

        col.separator()
        row = col.row(align=True)
        row.label(text="Empty Size:")
        row.prop(props, "empty_size", text="")


        col.separator()
        col.prop(props, "create_parent_collection")
        col.prop(props, "do_reparent")

        col.separator()
        col.operator(EDMTOOLS_OT_bake_empties_from_armature.bl_idname, icon='ACTION')
        col.operator(EDMTOOLS_OT_revert_bake.bl_idname, icon='TRASH')

# ---------------- Register ----------------

_classes = (
    EDMToolsBakeProps,
    EDMTOOLS_OT_bake_empties_from_armature,
    EDMTOOLS_OT_revert_bake,
    EDMTOOLS_PT_bake_subpanel,
)

def register():
    for c in _classes:
        bpy.utils.register_class(c)
    bpy.types.Scene.edm_tools_bake = PointerProperty(type=EDMToolsBakeProps)

def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
    if hasattr(bpy.types.Scene, "edm_tools_bake"):
        del bpy.types.Scene.edm_tools_bake
